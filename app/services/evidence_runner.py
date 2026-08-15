from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from PIL import Image

from app.models.evidence import (
    EvidenceBBox,
    EvidenceCandidate,
    EvidenceManifest,
    EvidenceSource,
    EvidenceSourceKind,
    EvidenceSourceRegistry,
    EvidenceSourceTrust,
    SelectedEvidenceAsset,
)
from app.models.project import (
    AssetJob,
    DocumentPayload,
    JobStatus,
    ProjectManifest,
    ProjectSpec,
    ProjectStatus,
    RenderJob,
    VisualCue,
    VisualType,
)
from app.services.evidence_renderer import (
    apply_highlight_overlay,
    compose_document_frame,
    compose_excerpt_card_frame,
    compute_evidence_spec_fingerprint,
    render_evidence_scene_video,
    render_pdf_page_to_image,
    validate_rendered_evidence_clip,
)
from app.services.evidence_selector import (
    extract_webpage_evidence_passage,
    inspect_and_extract_pdf_evidence,
    rank_and_select_candidate,
    score_evidence_candidate,
)
from app.services.evidence_sources import (
    compute_file_sha256,
    download_evidence_file,
    sanitize_secret_url,
    search_wikimedia_evidence,
)
from app.services.project_spec import load_project_spec, preflight_project
from app.services.project_timeline_runner import run_project_plan
from app.utils import utils


def resolve_evidence_workspace(
    project_input: str | Path | ProjectSpec,
    task_id: str | None = None,
) -> tuple[ProjectSpec, Path, str]:
    """Resolve project spec and ensure task directory with planning artifacts is ready."""
    source_path: Path | None = None
    if isinstance(project_input, (str, Path)):
        source_path = Path(project_input).expanduser().resolve()
        project = load_project_spec(source_path)
        preflight_project(project, source_path.parent)
    else:
        project = project_input

    run_task_id = task_id
    if not run_task_id and source_path is not None:
        parent_name = source_path.parent.name
        if source_path.parent.parent.name == "tasks" and parent_name:
            run_task_id = parent_name

    if not run_task_id:
        run_task_id = utils.get_uuid()

    if source_path is not None and (source_path.parent.name == run_task_id or source_path.parent.name.startswith("task_")):
        task_directory = source_path.parent
    else:
        task_directory = Path(utils.task_dir(run_task_id)).resolve()

    task_directory.mkdir(parents=True, exist_ok=True)

    motion_project_file = task_directory / "project.motion.json"
    assets_project_file = task_directory / "project.assets.json"
    planned_project_file = task_directory / "project.planned.json"
    visual_plan_file = task_directory / "visual_plan.json"

    # Stage priority: project.motion.json -> project.assets.json -> project.planned.json
    if motion_project_file.exists():
        logger.info(f"Loading project from motion stage: {motion_project_file.name}")
        project = load_project_spec(motion_project_file)
        return project, task_directory, run_task_id

    if assets_project_file.exists():
        logger.info(f"Loading project from assets stage: {assets_project_file.name}")
        project = load_project_spec(assets_project_file)
        return project, task_directory, run_task_id

    if planned_project_file.exists() and visual_plan_file.exists():
        logger.info(f"Loading project from planned stage: {planned_project_file.name}")
        project = load_project_spec(planned_project_file)
        return project, task_directory, run_task_id

    if project.visual_cues:
        return project, task_directory, run_task_id

    if source_path is None:
        source_path = task_directory / "project.json"
        source_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")

    logger.info(f"Planning artifacts not found for task {run_task_id}; running planning stage first")
    run_project_plan(str(source_path), task_id=run_task_id)

    if planned_project_file.exists():
        project = load_project_spec(planned_project_file)

    return project, task_directory, run_task_id


def discover_source_registry(
    task_directory: Path,
    project_input_dir: Path | None = None,
) -> tuple[EvidenceSourceRegistry, Path | None]:
    """Look for sources.json in project input directory or task workspace."""
    candidate_paths: list[Path] = []
    if project_input_dir and (project_input_dir / "sources.json").exists():
        candidate_paths.append(project_input_dir / "sources.json")
    if (task_directory / "sources.json").exists():
        candidate_paths.append(task_directory / "sources.json")

    for p in candidate_paths:
        try:
            raw_text = p.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            registry = EvidenceSourceRegistry.model_validate(data)
            logger.info(f"Loaded source registry with {len(registry.sources)} sources from {p.name}")
            return registry, p
        except Exception as exc:
            logger.warning(f"Failed to load sources.json from {p}: {exc}")
            raise exc

    # Return empty registry if no sources.json found
    return EvidenceSourceRegistry(sources=[]), None


def _transition_job(
    job: AssetJob | RenderJob,
    new_status: JobStatus,
    error: str | None = None,
    output: str | None = None,
    duration: float | None = None,
) -> None:
    job.status = new_status
    if error is not None:
        job.error = error
    if output is not None:
        job.output = output
    if duration is not None:
        job.duration = duration
    history = job.metadata.setdefault("status_history", [])
    history.append(new_status.value)


def run_evidence_acquisition(
    project_input: str | Path | ProjectSpec,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Execute G07 autonomous document & evidence acquisition and rendering pipeline."""
    project_dir: Path | None = None
    if isinstance(project_input, (str, Path)):
        project_dir = Path(project_input).expanduser().resolve().parent

    project, task_dir, current_task_id = resolve_evidence_workspace(project_input, task_id)
    evidence_dir = task_dir / "evidence"
    cache_dir = evidence_dir / "cache"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = evidence_dir / "evidence_manifest.json"
    project_evidence_path = task_dir / "project.evidence.json"
    project_manifest_path = task_dir / "project_manifest.json"
    sources_norm_path = evidence_dir / "sources.normalized.json"

    # Discover and normalize sources.json
    registry, registry_source_path = discover_source_registry(task_dir, project_dir)
    sources_norm_path.write_text(json.dumps(registry.model_dump(mode="json"), indent=2), encoding="utf-8")

    # Filter DOCUMENT cues
    doc_cues = [
        cue for cue in sorted(project.visual_cues, key=lambda c: c.order)
        if cue.visual_type == VisualType.document
    ]

    # Handle zero DOCUMENT cues scenario
    if not doc_cues:
        logger.info(f"Task {current_task_id} contains zero DOCUMENT visual cues; completing evidence stage.")
        empty_manifest = EvidenceManifest(
            project_title=project.project.title,
            task_id=current_task_id,
            status=ProjectStatus.complete,
            assets=[],
            failed_scenes=[],
            skipped_scenes=[],
            source_registry_file=str(sources_norm_path.resolve()) if registry.sources else None,
        )
        manifest_path.write_text(json.dumps(empty_manifest.model_dump(mode="json"), indent=2), encoding="utf-8")
        project_evidence_path.write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")

        if project_manifest_path.exists():
            try:
                p_man = ProjectManifest.model_validate_json(project_manifest_path.read_text(encoding="utf-8"))
                p_man.outputs["evidence_manifest_file"] = str(manifest_path.resolve())
                p_man.outputs["evidence_project_file"] = str(project_evidence_path.resolve())
                if registry.sources:
                    p_man.outputs["source_registry_file"] = str(sources_norm_path.resolve())
                p_man.updated_at = datetime.now(timezone.utc)
                if p_man.status != ProjectStatus.failed:
                    p_man.status = ProjectStatus.complete
                project_manifest_path.write_text(json.dumps(p_man.model_dump(mode="json"), indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning(f"Could not update project_manifest.json: {exc}")

        return {
            "status": "complete",
            "task_id": current_task_id,
            "evidence_count": 0,
            "failed_count": 0,
            "manifest": str(manifest_path.resolve()),
            "project_evidence": str(project_evidence_path.resolve()),
        }

    # Initialize AssetJobs and RenderJobs for DOCUMENT cues
    # Preserve existing BROLL AssetJobs and G06 RenderJobs
    asset_jobs_by_id = {j.scene_id: j for j in project.asset_jobs}
    render_jobs_by_id = {j.scene_id: j for j in project.render_jobs}

    for cue in doc_cues:
        a_job_id = f"A{cue.order:03d}"
        r_job_id = f"R{cue.order:03d}"

        a_job = AssetJob(
            id=a_job_id,
            scene_id=cue.id,
            kind="document",
            status=JobStatus.planned,
            attempts=0,
            metadata={"status_history": ["planned"]},
        )
        r_job = RenderJob(
            id=r_job_id,
            scene_id=cue.id,
            kind="document",
            status=JobStatus.planned,
            attempts=0,
            metadata={"status_history": ["planned"]},
        )
        asset_jobs_by_id[cue.id] = a_job
        render_jobs_by_id[cue.id] = r_job

    fps = project.project.fps
    is_portrait = project.project.aspect_ratio == "9:16"
    target_w = 1080 if is_portrait else 1920
    target_h = 1920 if is_portrait else 1080

    rendered_assets: list[SelectedEvidenceAsset] = []
    failed_scenes: list[dict[str, Any]] = []
    skipped_scenes: list[dict[str, Any]] = []

    # Process each DOCUMENT cue
    for cue in doc_cues:
        a_job = asset_jobs_by_id[cue.id]
        r_job = render_jobs_by_id[cue.id]
        _transition_job(a_job, JobStatus.queued)
        _transition_job(r_job, JobStatus.queued)

        payload_dict = cue.payload if isinstance(cue.payload, dict) else {}
        try:
            payload = DocumentPayload.model_validate(payload_dict)
        except Exception as exc:
            err = f"Malformed DocumentPayload for scene {cue.id}: {exc}"
            logger.error(err)
            _transition_job(a_job, JobStatus.failed, error=err)
            _transition_job(r_job, JobStatus.failed, error=err)
            failed_scenes.append({"scene_id": cue.id, "error": err})
            continue

        _transition_job(a_job, JobStatus.processing)
        a_job.attempts += 1

        start_f = round(cue.start * fps)
        end_f = round(cue.end * fps)
        duration_f = max(1, end_f - start_f)

        # 1. Resolve eligible sources
        eligible_sources: list[tuple[EvidenceSource, bool]] = []
        # A. Explicitly pinned source_ids
        pinned_set = set(payload.source_ids)
        for s in registry.sources:
            if s.id in pinned_set:
                eligible_sources.append((s, True))

        # B. Matching sources from registry
        for s in registry.sources:
            if s.id not in pinned_set and s.allowed_for_evidence:
                # Include if query / hint has any match
                eligible_sources.append((s, False))

        # C. Autonomous Wikimedia discovery if registry has no candidates or no pinned matches
        wikimedia_sources: list[EvidenceSource] = []
        if not pinned_set:
            try:
                wiki_results = search_wikimedia_evidence(payload.search_query, limit=4)
                for idx, wr in enumerate(wiki_results):
                    w_source = EvidenceSource(
                        id=f"WIKI_{cue.id}_{idx+1}",
                        kind=EvidenceSourceKind.wikimedia,
                        url=wr["image_url"],
                        title=wr["title"],
                        publisher=wr.get("author") or "Wikimedia Commons",
                        trust=EvidenceSourceTrust.public_domain if wr.get("license") and "public domain" in wr.get("license", "").lower() else EvidenceSourceTrust.licensed,
                        license=wr.get("license"),
                        tags=wr.get("categories", []),
                        metadata={"description_url": wr.get("source_url")},
                    )
                    wikimedia_sources.append(w_source)
            except Exception as w_exc:
                logger.warning(f"Wikimedia search error for {cue.id}: {w_exc}")

        all_candidate_sources = eligible_sources + [(ws, False) for ws in wikimedia_sources]

        # 2. Acquire and evaluate candidates
        candidates: list[EvidenceCandidate] = []
        for source, is_pinned in all_candidate_sources:
            source_cache_dir = cache_dir / source.id
            source_cache_dir.mkdir(parents=True, exist_ok=True)

            local_source_file: Path | None = None
            source_sha256: str | None = None

            # Download or load local source bytes
            try:
                if source.local_file:
                    # Resolve local file
                    p_loc = Path(source.local_file).expanduser()
                    if not p_loc.is_absolute() and project_dir:
                        p_loc = project_dir / p_loc
                    if not p_loc.exists() and (task_dir / source.local_file).exists():
                        p_loc = task_dir / source.local_file
                    if not p_loc.exists():
                        continue
                    dest_file = source_cache_dir / p_loc.name
                    if not dest_file.exists():
                        shutil.copy2(p_loc, dest_file)
                    local_source_file = dest_file
                    source_sha256 = compute_file_sha256(dest_file)

                elif source.url:
                    parsed_url = source.url.split("?")[0]
                    ext = Path(parsed_url).suffix or ".bin"
                    dest_file = source_cache_dir / f"source{ext}"
                    if dest_file.exists() and dest_file.stat().st_size > 0:
                        local_source_file = dest_file
                        source_sha256 = compute_file_sha256(dest_file)
                    else:
                        sha, _ = download_evidence_file(source.url, dest_file)
                        local_source_file = dest_file
                        source_sha256 = sha

            except Exception as src_err:
                logger.warning(f"Could not load source {source.id} ({source.title}): {src_err}")
                continue

            if not local_source_file or not local_source_file.exists():
                continue

            # Process source content by kind
            try:
                if source.kind == EvidenceSourceKind.pdf:
                    p_num, p_count, matched_txt, m_type, bboxes = inspect_and_extract_pdf_evidence(
                        pdf_path=local_source_file,
                        highlight_target=payload.highlight_target,
                        quote_hint=source.quote_hint,
                        page_hint=source.page_hint,
                        search_query=payload.search_query,
                    )
                    score, breakdown = score_evidence_candidate(
                        cue=cue,
                        payload=payload,
                        source=source,
                        match_type=m_type,
                        matched_text=matched_txt,
                        page_number=p_num,
                        is_pinned_source=is_pinned,
                    )
                    cand = EvidenceCandidate(
                        id=f"{source.id}_p{p_num}",
                        source_id=source.id,
                        kind=source.kind,
                        title=source.title,
                        publisher=source.publisher,
                        trust=source.trust,
                        license=source.license,
                        source_url=sanitize_secret_url(source.url),
                        local_file=str(local_source_file),
                        query=payload.search_query,
                        page_number=p_num,
                        page_count=p_count,
                        matched_text=matched_txt,
                        match_type=m_type,
                        highlight_boxes=bboxes,
                        score=score,
                        score_breakdown=breakdown,
                        metadata={"source_sha256": source_sha256},
                    )
                    candidates.append(cand)

                elif source.kind == EvidenceSourceKind.webpage:
                    html_content = local_source_file.read_text(encoding="utf-8", errors="replace")
                    w_title, w_pub, full_txt, snippet, m_type = extract_webpage_evidence_passage(
                        html_text=html_content,
                        source_url=source.url,
                        highlight_target=payload.highlight_target,
                        quote_hint=source.quote_hint,
                        search_query=payload.search_query,
                    )
                    score, breakdown = score_evidence_candidate(
                        cue=cue,
                        payload=payload,
                        source=source,
                        match_type=m_type,
                        matched_text=snippet,
                        is_pinned_source=is_pinned,
                    )
                    cand = EvidenceCandidate(
                        id=f"{source.id}_web",
                        source_id=source.id,
                        kind=source.kind,
                        title=w_title or source.title,
                        publisher=w_pub or source.publisher,
                        trust=source.trust,
                        license=source.license,
                        source_url=sanitize_secret_url(source.url),
                        local_file=str(local_source_file),
                        query=payload.search_query,
                        matched_text=snippet,
                        match_type=m_type,
                        highlight_boxes=[],
                        score=score,
                        score_breakdown=breakdown,
                        metadata={"source_sha256": source_sha256, "full_text": full_txt},
                    )
                    candidates.append(cand)

                elif source.kind in (EvidenceSourceKind.image, EvidenceSourceKind.wikimedia):
                    # Check if valid image
                    with Image.open(local_source_file) as im:
                        im_w, im_h = im.size

                    boxes = [source.bbox_hint] if source.bbox_hint else []
                    m_type = "exact_target" if boxes else "query_relevance"
                    score, breakdown = score_evidence_candidate(
                        cue=cue,
                        payload=payload,
                        source=source,
                        match_type=m_type,
                        matched_text=source.title,
                        is_pinned_source=is_pinned,
                    )
                    cand = EvidenceCandidate(
                        id=f"{source.id}_img",
                        source_id=source.id,
                        kind=source.kind,
                        title=source.title,
                        publisher=source.publisher,
                        trust=source.trust,
                        license=source.license,
                        source_url=sanitize_secret_url(source.url),
                        local_file=str(local_source_file),
                        query=payload.search_query,
                        matched_text=source.title,
                        match_type=m_type,
                        highlight_boxes=boxes,
                        width=im_w,
                        height=im_h,
                        score=score,
                        score_breakdown=breakdown,
                        metadata={"source_sha256": source_sha256},
                    )
                    candidates.append(cand)

            except Exception as cand_err:
                logger.warning(f"Error evaluating candidate from {source.id}: {cand_err}")

        # 3. Rank and select best candidate
        selected_cand, fail_reason = rank_and_select_candidate(
            candidates,
            evidence_required=payload.evidence_required,
            min_score_threshold=35.0,
        )

        if selected_cand is None:
            if payload.evidence_required:
                logger.error(f"Scene {cue.id} evidence acquisition failed: {fail_reason}")
                _transition_job(a_job, JobStatus.failed, error=fail_reason)
                _transition_job(r_job, JobStatus.failed, error=fail_reason)
                failed_scenes.append({"scene_id": cue.id, "error": fail_reason})
            else:
                logger.info(f"Scene {cue.id} optional evidence skipped: {fail_reason}")
                _transition_job(a_job, JobStatus.ready, output="skipped")
                _transition_job(r_job, JobStatus.ready, output="skipped")
                skipped_scenes.append({
                    "scene_id": cue.id,
                    "reason": fail_reason,
                    "fallback_recommendation": "text",
                })
            continue

        _transition_job(a_job, JobStatus.ready, output=selected_cand.local_file)

        # 4. Render Scene Video
        _transition_job(r_job, JobStatus.processing)
        r_job.attempts += 1

        scene_out_dir = evidence_dir / cue.id
        scene_out_dir.mkdir(parents=True, exist_ok=True)

        video_filename = f"{cue.id}_DOCUMENT.mp4"
        video_out_path = scene_out_dir / video_filename
        scene_meta_path = scene_out_dir / "metadata.json"
        page_png_path = scene_out_dir / "page.png"
        annotated_png_path = scene_out_dir / "annotated.png"

        render_mode = "excerpt_card" if selected_cand.kind == EvidenceSourceKind.webpage else "document_page"
        source_sha = selected_cand.metadata.get("source_sha256", "")

        spec_fp = compute_evidence_spec_fingerprint(
            scene_id=cue.id,
            search_query=payload.search_query,
            highlight_target=payload.highlight_target,
            source_id=selected_cand.source_id,
            source_sha256=source_sha,
            page_number=selected_cand.page_number,
            match_type=selected_cand.match_type,
            highlight_boxes=selected_cand.highlight_boxes,
            duration_frames=duration_f,
            fps=fps,
            width=target_w,
            height=target_h,
            render_mode=render_mode,
        )

        # Safe Resumability Check
        if video_out_path.exists() and scene_meta_path.exists():
            try:
                saved_asset_data = json.loads(scene_meta_path.read_text(encoding="utf-8"))
                saved_asset = SelectedEvidenceAsset.model_validate(saved_asset_data)
                if saved_asset.spec_fingerprint == spec_fp and saved_asset.scene_id == cue.id:
                    validate_rendered_evidence_clip(
                        rendered_path=video_out_path,
                        expected_duration_frames=duration_f,
                        expected_width=target_w,
                        expected_height=target_h,
                        expected_fps=fps,
                    )
                    logger.info(f"Reusing validated evidence asset for {cue.id}")
                    _transition_job(r_job, JobStatus.ready, output=str(video_out_path), duration=round(duration_f / float(fps), 4))
                    rendered_assets.append(saved_asset)
                    continue
            except Exception as res_err:
                logger.info(f"Resumption validation failed for {cue.id} ({res_err}); re-rendering.")

        # Execute Frame Generation & Render with 1 Retry
        render_success = False
        last_render_err: Exception | None = None

        for attempt in range(1, 3):
            if attempt > 1:
                _transition_job(r_job, JobStatus.retrying)
                _transition_job(r_job, JobStatus.processing)
                r_job.attempts += 1

            try:
                if render_mode == "document_page":
                    # Generate Base & Highlighted Images
                    if selected_cand.kind == EvidenceSourceKind.pdf:
                        raw_page_img = render_pdf_page_to_image(
                            pdf_path=selected_cand.local_file,
                            page_number=selected_cand.page_number or 1,
                        )
                    else:
                        raw_page_img = Image.open(selected_cand.local_file).convert("RGB")

                    raw_page_img.save(page_png_path, format="PNG")
                    annotated_page_img = apply_highlight_overlay(
                        raw_page_img,
                        selected_cand.highlight_boxes,
                    )
                    annotated_page_img.save(annotated_png_path, format="PNG")

                    composite_frame = compose_document_frame(
                        annotated_page_img=annotated_page_img,
                        width=target_w,
                        height=target_h,
                        title=selected_cand.title,
                        publisher=selected_cand.publisher,
                        trust=selected_cand.trust.value,
                        license_info=selected_cand.license,
                    )
                else:
                    # Excerpt Card Mode
                    composite_frame = compose_excerpt_card_frame(
                        width=target_w,
                        height=target_h,
                        title=selected_cand.title,
                        publisher=selected_cand.publisher,
                        excerpt_text=selected_cand.matched_text or "",
                        highlight_target=payload.highlight_target,
                        trust=selected_cand.trust.value,
                        license_info=selected_cand.license,
                    )
                    composite_frame.save(annotated_png_path, format="PNG")

                # Render MP4
                render_evidence_scene_video(
                    composite_image=composite_frame,
                    output_mp4_path=video_out_path,
                    duration_frames=duration_f,
                    fps=fps,
                    width=target_w,
                    height=target_h,
                )

                # Validate Output
                validate_rendered_evidence_clip(
                    rendered_path=video_out_path,
                    expected_duration_frames=duration_f,
                    expected_width=target_w,
                    expected_height=target_h,
                    expected_fps=fps,
                )

                render_success = True
                break

            except Exception as r_exc:
                last_render_err = r_exc
                logger.warning(f"Render attempt {attempt} failed for evidence scene {cue.id}: {r_exc}")
                if video_out_path.exists():
                    try:
                        video_out_path.unlink()
                    except Exception:
                        pass

        if not render_success:
            err_msg = f"Evidence video rendering failed for {cue.id}: {last_render_err}"
            logger.error(err_msg)
            _transition_job(r_job, JobStatus.failed, error=err_msg)
            failed_scenes.append({"scene_id": cue.id, "error": err_msg})
            continue

        _transition_job(
            r_job,
            JobStatus.ready,
            output=str(video_out_path),
            duration=round(duration_f / float(fps), 4),
        )

        asset = SelectedEvidenceAsset(
            scene_id=cue.id,
            source_id=selected_cand.source_id,
            source_kind=selected_cand.kind.value,
            title=selected_cand.title,
            publisher=selected_cand.publisher,
            trust=selected_cand.trust.value,
            source_url=selected_cand.source_url,
            local_source_file=selected_cand.local_file,
            source_sha256=source_sha,
            page_number=selected_cand.page_number,
            matched_text=selected_cand.matched_text,
            match_type=selected_cand.match_type,
            highlight_boxes=[b.model_dump(mode="json") for b in selected_cand.highlight_boxes],
            score=selected_cand.score,
            score_breakdown=selected_cand.score_breakdown,
            render_mode=render_mode,
            source_file=selected_cand.local_file,
            page_image_file=str(page_png_path.resolve()) if page_png_path.exists() else None,
            annotated_image_file=str(annotated_png_path.resolve()) if annotated_png_path.exists() else None,
            rendered_file=str(video_out_path.resolve()),
            license=selected_cand.license,
            spec_fingerprint=spec_fp,
            metadata={
                "attempts": r_job.attempts,
                "duration_frames": duration_f,
                "fps": fps,
                "width": target_w,
                "height": target_h,
            },
        )

        scene_meta_path.write_text(json.dumps(asset.model_dump(mode="json"), indent=2), encoding="utf-8")
        rendered_assets.append(asset)
        logger.success(f"Rendered evidence scene {cue.id}: {video_out_path.name}")

    # Synchronize project state
    project.asset_jobs = list(asset_jobs_by_id.values())
    project.render_jobs = list(render_jobs_by_id.values())

    stage_status = ProjectStatus.failed if failed_scenes else ProjectStatus.complete
    evidence_manifest = EvidenceManifest(
        project_title=project.project.title,
        task_id=current_task_id,
        status=stage_status,
        assets=rendered_assets,
        failed_scenes=failed_scenes,
        skipped_scenes=skipped_scenes,
        source_registry_file=str(sources_norm_path.resolve()) if registry.sources else None,
        error=f"{len(failed_scenes)} evidence scenes failed" if failed_scenes else None,
    )

    manifest_path.write_text(json.dumps(evidence_manifest.model_dump(mode="json"), indent=2), encoding="utf-8")
    project_evidence_path.write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")

    # Synchronize project_manifest.json (preserving prior failures)
    if project_manifest_path.exists():
        try:
            p_man = ProjectManifest.model_validate_json(project_manifest_path.read_text(encoding="utf-8"))
            p_man.outputs["evidence_manifest_file"] = str(manifest_path.resolve())
            p_man.outputs["evidence_project_file"] = str(project_evidence_path.resolve())
            if registry.sources:
                p_man.outputs["source_registry_file"] = str(sources_norm_path.resolve())
            p_man.updated_at = datetime.now(timezone.utc)
            if failed_scenes:
                p_man.status = ProjectStatus.failed
                ev_err = f"Evidence acquisition failed for {len(failed_scenes)} scenes"
                if p_man.error:
                    if ev_err not in p_man.error:
                        p_man.error = f"{p_man.error}; {ev_err}"
                else:
                    p_man.error = ev_err
                stage_errors = p_man.outputs.setdefault("stage_errors", {})
                stage_errors["evidence"] = ev_err
            elif p_man.status != ProjectStatus.failed:
                p_man.status = ProjectStatus.complete
            project_manifest_path.write_text(json.dumps(p_man.model_dump(mode="json"), indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Could not update project_manifest.json: {exc}")

    return {
        "status": stage_status.value,
        "task_id": current_task_id,
        "evidence_count": len(rendered_assets),
        "failed_count": len(failed_scenes),
        "skipped_count": len(skipped_scenes),
        "manifest": str(manifest_path.resolve()),
        "project_evidence": str(project_evidence_path.resolve()),
    }
