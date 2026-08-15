from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from app.models.execution import (
    ExecutionManifest,
    ExecutionStageStatus,
    SceneExecutionRecord,
    StageExecutionRecord,
)
from app.models.motion import RenderedMotionAsset
from app.models.project import (
    DocumentPayload,
    JobStatus,
    ProjectManifest,
    ProjectSpec,
    ProjectStatus,
    RenderJob,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.broll import validate_rendered_clip
from app.services.broll_runner import run_broll_acquisition
from app.services.evidence_renderer import validate_rendered_evidence_clip
from app.services.evidence_runner import run_evidence_acquisition
from app.services.evidence_sources import compute_file_sha256, sanitize_secret_url
from app.services.motion_normalizer import normalize_motion_spec
from app.services.motion_runner import run_motion_render
from app.services.project_runner import ProjectRunError
from app.services.project_spec import load_project_spec, preflight_project, save_project_spec
from app.services.project_timeline_runner import run_project_plan
from app.services.remotion import render_scene_motion, validate_rendered_motion_clip
from app.utils import utils


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(file_path: Path, data: dict[str, Any]) -> None:
    file_path = Path(file_path).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    nonce = hashlib.md5(str(os.urandom(8)).encode()).hexdigest()[:6]
    temp_file = file_path.with_suffix(f".tmp.{os.getpid()}.{nonce}")
    try:
        temp_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        json.loads(temp_file.read_text(encoding="utf-8"))
        temp_file.replace(file_path)
    finally:
        if temp_file.exists():
            try:
                temp_file.unlink()
            except Exception:
                pass


def sanitize_error_message(msg: str | None) -> str | None:
    if not msg:
        return None
    cleaned = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]+", r"\1[REDACTED]", msg)
    cleaned = re.sub(r"(?i)(api[_\-]?key=)[A-Za-z0-9_\-\.]+", r"\1[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(token=)[A-Za-z0-9_\-\.]+", r"\1[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(sig=)[A-Za-z0-9_\-\.]+", r"\1[REDACTED]", cleaned)
    return cleaned


def compute_project_input_fingerprint(project_spec: ProjectSpec) -> str:
    """Compute deterministic SHA-256 fingerprint representing semantic project input configuration."""
    canonical: dict[str, Any] = {
        "schema_version": project_spec.schema_version,
        "project": {
            "title": project_spec.project.title,
            "language": project_spec.project.language,
            "aspect_ratio": project_spec.project.aspect_ratio.value
            if hasattr(project_spec.project.aspect_ratio, "value")
            else str(project_spec.project.aspect_ratio),
            "fps": project_spec.project.fps,
        },
        "script": {
            "subject": project_spec.script.subject,
            "script": project_spec.script.script,
            "search_terms": sorted(project_spec.script.search_terms or []),
        },
        "narration": {
            "mode": project_spec.narration.mode.value
            if hasattr(project_spec.narration.mode, "value")
            else str(project_spec.narration.mode),
            "voice_name": project_spec.narration.voice_name,
            "voice_volume": project_spec.narration.voice_volume,
            "voice_rate": project_spec.narration.voice_rate,
            "file": project_spec.narration.file,
            "timing_file": project_spec.narration.timing_file,
        },
        "production": project_spec.production.model_dump(mode="json"),
    }
    if project_spec.timeline_cues:
        canonical["timeline_cues"] = [
            {"id": c.id, "order": c.order, "start": c.start, "end": c.end, "narration": c.narration}
            for c in project_spec.timeline_cues
        ]
    if project_spec.visual_cues:
        canonical["visual_cues"] = [
            {
                "id": c.id,
                "order": c.order,
                "visual_type": c.visual_type.value
                if hasattr(c.visual_type, "value")
                else str(c.visual_type),
                "purpose": c.purpose.value
                if hasattr(c.purpose, "value")
                else (str(c.purpose) if c.purpose else None),
                "start": c.start,
                "end": c.end,
                "narration": c.narration,
                "payload": c.payload,
            }
            for c in project_spec.visual_cues
        ]

    dumped = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _is_planning_reusable(
    task_dir: Path,
    expected_fingerprint: str,
    project_spec: ProjectSpec,
) -> tuple[bool, str]:
    """Check whether existing planning stage artifacts can be reused safely."""
    planned_file = task_dir / "project.planned.json"
    visual_plan_file = task_dir / "visual_plan.json"
    timeline_file = task_dir / "timeline.json"

    if not (planned_file.exists() and visual_plan_file.exists() and timeline_file.exists()):
        return False, "Planning artifacts missing"

    try:
        planned_project = load_project_spec(planned_file)
    except Exception as exc:
        return False, f"project.planned.json parse failure: {exc}"

    if not planned_project.visual_cues:
        return False, "project.planned.json has no visual cues"

    if len(planned_project.visual_cues) != len(planned_project.timeline_cues):
        return False, "Mismatch between visual cues and timeline cues count"

    # Check audio file
    if not planned_project.narration.file:
        return False, "No narration audio file referenced in planning"
    audio_path = Path(planned_project.narration.file)
    if not (audio_path.exists() and audio_path.stat().st_size > 0):
        return False, f"Narration audio file is missing or empty: {audio_path}"

    # Check timing file
    if planned_project.narration.timing_file:
        timing_path = Path(planned_project.narration.timing_file)
        if not (timing_path.exists() and timing_path.stat().st_size > 0):
            return False, f"Timing file is missing or empty: {timing_path}"

    # Verify project parameters match
    if planned_project.project.fps != project_spec.project.fps:
        return False, "Project FPS mismatch"
    if planned_project.project.aspect_ratio != project_spec.project.aspect_ratio:
        return False, "Project aspect ratio mismatch"

    return True, "Valid planning artifacts present"


def _render_text_fallback_scene(
    cue: VisualCue,
    project: ProjectSpec,
    task_dir: Path,
) -> tuple[RenderJob, RenderedMotionAsset | None, str | None]:
    """Deterministically render G06 TEXT motion fallback for an optional DOCUMENT cue."""
    motion_dir = task_dir / "motion"
    motion_dir.mkdir(parents=True, exist_ok=True)

    payload = cue.payload or {}
    highlight_target = payload.get("highlight_target")
    if highlight_target and str(highlight_target).strip():
        headline = " ".join(str(highlight_target).strip().split())
    elif cue.narration and cue.narration.strip():
        headline = " ".join(cue.narration.strip().split())
    else:
        headline = "Key Evidence"

    headline = headline[:100].strip()

    fps = project.project.fps or 30
    start_frame = round((cue.start or 0.0) * fps)
    end_frame = round((cue.end or 0.0) * fps)
    duration_frames = max(1, end_frame - start_frame)
    aspect = project.project.aspect_ratio

    fallback_cue = VisualCue(
        id=cue.id,
        order=cue.order,
        visual_type=VisualType.text,
        purpose=cue.purpose or VisualPurpose.emphasis,
        start=cue.start,
        end=cue.end,
        narration=cue.narration,
        payload={"headline": headline, "subheadline": None},
    )

    try:
        scene_spec = normalize_motion_spec(fallback_cue, project)
        rendered_asset = render_scene_motion(scene_spec, task_directory=task_dir)
        render_job = RenderJob(
            id=f"job_fallback_{cue.id}",
            scene_id=cue.id,
            kind="text_fallback",
            status=JobStatus.ready,
            output=rendered_asset.output_file,
            duration=rendered_asset.duration_frames / float(rendered_asset.fps),
            metadata={
                "fallback_from": "document",
                "fallback_reason": "optional evidence unavailable",
                "spec_fingerprint": rendered_asset.metadata.get("spec_fingerprint"),
                "status_history": ["planned", "processing", "ready"],
            },
        )
        return render_job, rendered_asset, None
    except Exception as exc:
        err_msg = f"TEXT fallback rendering failed for scene {cue.id}: {exc}"
        logger.error(err_msg)
        render_job = RenderJob(
            id=f"job_fallback_{cue.id}",
            scene_id=cue.id,
            kind="text_fallback",
            status=JobStatus.failed,
            error=err_msg,
            metadata={
                "fallback_from": "document",
                "fallback_reason": "optional evidence unavailable",
                "status_history": ["planned", "processing", "failed"],
            },
        )
        return render_job, None, err_msg


def run_all_project(
    project_input: str | Path | ProjectSpec,
    task_id: str | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute end-to-end autonomous research and asset generation pipeline (G08).

    Stages:
    1. Preflight
    2. Planning
    3. B-roll Acquisition
    4. Motion Rendering
    5. Evidence Acquisition
    6. Fallback (Optional DOCUMENT -> TEXT)
    7. Final Validation
    8. Finalize & Manifest Reconciliation
    """
    created_at = _utc_now()

    # --- 1. PREFLIGHT ---
    source_project_file = ""
    project_parent_dir = Path.cwd()
    if isinstance(project_input, (str, Path)):
        source_path = Path(project_input).expanduser().resolve()
        source_project_file = str(source_path)
        project_parent_dir = source_path.parent
        project_spec = load_project_spec(source_path)
    else:
        project_spec = project_input
        source_path = None

    run_task_id = task_id or utils.get_uuid()
    task_dir = Path(utils.task_dir(run_task_id)).resolve()
    task_dir.mkdir(parents=True, exist_ok=True)

    project_fingerprint = compute_project_input_fingerprint(project_spec)

    # Check for sources.json
    source_registry_sha256 = None
    sources_candidate_1 = project_parent_dir / "sources.json"
    sources_candidate_2 = task_dir / "sources.json"
    if sources_candidate_1.exists():
        source_registry_sha256 = compute_file_sha256(sources_candidate_1)
    elif sources_candidate_2.exists():
        source_registry_sha256 = compute_file_sha256(sources_candidate_2)

    stages_records: list[StageExecutionRecord] = []

    def _notify(stage_name: str, status_str: str, progress: int) -> None:
        if on_progress:
            on_progress({"stage": stage_name, "status": status_str, "progress_percent": progress})

    _notify("preflight", "processing", 5)

    # Check for same-task fingerprint mismatch
    existing_exec_manifest = task_dir / "execution_manifest.json"
    if existing_exec_manifest.exists():
        try:
            saved_exec = json.loads(existing_exec_manifest.read_text(encoding="utf-8"))
            saved_fp = saved_exec.get("source_project_fingerprint")
            if saved_fp and saved_fp != project_fingerprint:
                err = f"Task '{run_task_id}' belongs to a different project input (fingerprint mismatch). Use a new task ID."
                logger.error(err)
                stages_records.append(
                    StageExecutionRecord(
                        name="preflight",
                        status=ExecutionStageStatus.failed,
                        started_at=created_at,
                        completed_at=_utc_now(),
                        error=err,
                    )
                )
                manifest = ExecutionManifest(
                    schema_version="1.0",
                    project_title=project_spec.project.title,
                    task_id=run_task_id,
                    source_project_file=source_project_file or str(task_dir / "project.json"),
                    source_project_fingerprint=project_fingerprint,
                    source_registry_sha256=source_registry_sha256,
                    status=ExecutionStageStatus.failed,
                    progress_percent=5,
                    stages=stages_records,
                    scenes=[],
                    ready_scene_count=0,
                    failed_scene_count=0,
                    created_at=created_at,
                    updated_at=_utc_now(),
                    error=err,
                )
                _atomic_write_json(task_dir / "execution_manifest.json", manifest.model_dump(mode="json"))
                raise ProjectRunError(err)
        except ProjectRunError:
            raise
        except Exception:
            pass

    # Run preflight validation
    try:
        preflight_project(project_spec, project_parent_dir)
        stages_records.append(
            StageExecutionRecord(
                name="preflight",
                status=ExecutionStageStatus.complete,
                started_at=created_at,
                completed_at=_utc_now(),
                metadata={"fingerprint": project_fingerprint},
            )
        )
    except Exception as exc:
        err = f"Preflight validation failed: {exc}"
        logger.error(err)
        stages_records.append(
            StageExecutionRecord(
                name="preflight",
                status=ExecutionStageStatus.failed,
                started_at=created_at,
                completed_at=_utc_now(),
                error=err,
            )
        )
        manifest = ExecutionManifest(
            schema_version="1.0",
            project_title=project_spec.project.title,
            task_id=run_task_id,
            source_project_file=source_project_file or str(task_dir / "project.json"),
            source_project_fingerprint=project_fingerprint,
            source_registry_sha256=source_registry_sha256,
            status=ExecutionStageStatus.failed,
            progress_percent=5,
            stages=stages_records,
            scenes=[],
            ready_scene_count=0,
            failed_scene_count=0,
            created_at=created_at,
            updated_at=_utc_now(),
            error=err,
        )
        _atomic_write_json(task_dir / "execution_manifest.json", manifest.model_dump(mode="json"))
        raise ProjectRunError(err) from exc

    # Save normalized project
    save_project_spec(project_spec, task_dir / "project.normalized.json")
    if source_path is None:
        source_path = task_dir / "project.json"
        save_project_spec(project_spec, source_path)

    # --- 2. PLANNING ---
    _notify("planning", "processing", 25)
    planning_start = _utc_now()
    can_reuse_plan, reuse_reason = _is_planning_reusable(task_dir, project_fingerprint, project_spec)

    try:
        if can_reuse_plan:
            logger.info(f"Reusing existing planning artifacts for task {run_task_id}: {reuse_reason}")
            planned_project = load_project_spec(task_dir / "project.planned.json")
            stages_records.append(
                StageExecutionRecord(
                    name="planning",
                    status=ExecutionStageStatus.complete,
                    started_at=planning_start,
                    completed_at=_utc_now(),
                    input_file=str((task_dir / "project.normalized.json").resolve()),
                    output_file=str((task_dir / "project.planned.json").resolve()),
                    manifest_file=str((task_dir / "visual_plan.json").resolve()),
                    ready_count=len(planned_project.visual_cues),
                    metadata={"reused": True, "reuse_reason": reuse_reason},
                )
            )
        else:
            logger.info(f"Running planning stage for task {run_task_id}")
            plan_res = run_project_plan(str(source_path), task_id=run_task_id)
            planned_project = load_project_spec(task_dir / "project.planned.json")
            stages_records.append(
                StageExecutionRecord(
                    name="planning",
                    status=ExecutionStageStatus.complete,
                    started_at=planning_start,
                    completed_at=_utc_now(),
                    input_file=str((task_dir / "project.normalized.json").resolve()),
                    output_file=str((task_dir / "project.planned.json").resolve()),
                    manifest_file=str((task_dir / "visual_plan.json").resolve()),
                    ready_count=len(planned_project.visual_cues),
                    metadata={"reused": False},
                )
            )
    except Exception as exc:
        err = f"Planning stage failed: {exc}"
        logger.error(err)
        stages_records.append(
            StageExecutionRecord(
                name="planning",
                status=ExecutionStageStatus.failed,
                started_at=planning_start,
                completed_at=_utc_now(),
                error=err,
            )
        )
        manifest = ExecutionManifest(
            schema_version="1.0",
            project_title=project_spec.project.title,
            task_id=run_task_id,
            source_project_file=source_project_file or str(source_path),
            source_project_fingerprint=project_fingerprint,
            source_registry_sha256=source_registry_sha256,
            status=ExecutionStageStatus.failed,
            progress_percent=25,
            stages=stages_records,
            scenes=[],
            ready_scene_count=0,
            failed_scene_count=0,
            created_at=created_at,
            updated_at=_utc_now(),
            error=err,
        )
        _atomic_write_json(task_dir / "execution_manifest.json", manifest.model_dump(mode="json"))
        return {
            "status": "failed",
            "task_id": run_task_id,
            "ready_scenes": 0,
            "failed_scenes": 0,
            "execution_manifest": str((task_dir / "execution_manifest.json").resolve()),
            "error": err,
        }

    # --- 3. B-ROLL ACQUISITION ---
    _notify("broll", "processing", 45)
    broll_start = _utc_now()
    has_broll = any(c.visual_type == VisualType.broll for c in planned_project.visual_cues)

    if has_broll:
        try:
            broll_res = run_broll_acquisition(str(task_dir / "project.planned.json"), task_id=run_task_id)
            broll_status = (
                ExecutionStageStatus.complete
                if broll_res.get("status") == "complete"
                else ExecutionStageStatus.failed
            )
            stages_records.append(
                StageExecutionRecord(
                    name="broll",
                    status=broll_status,
                    started_at=broll_start,
                    completed_at=_utc_now(),
                    input_file=str((task_dir / "project.planned.json").resolve()),
                    output_file=str((task_dir / "project.assets.json").resolve()),
                    manifest_file=str((task_dir / "broll_manifest.json").resolve()),
                    ready_count=broll_res.get("acquired_assets_count", 0),
                    failed_count=broll_res.get("failed_scenes_count", 0),
                    error=sanitize_error_message(broll_res.get("error")),
                )
            )
        except Exception as exc:
            err = f"B-roll stage exception: {exc}"
            logger.warning(err)
            stages_records.append(
                StageExecutionRecord(
                    name="broll",
                    status=ExecutionStageStatus.failed,
                    started_at=broll_start,
                    completed_at=_utc_now(),
                    error=sanitize_error_message(err),
                )
            )
    else:
        stages_records.append(
            StageExecutionRecord(
                name="broll",
                status=ExecutionStageStatus.complete,
                started_at=broll_start,
                completed_at=_utc_now(),
                ready_count=0,
                failed_count=0,
                skipped_count=0,
                metadata={"skipped_reason": "No BROLL visual cues in project"},
            )
        )

    # --- 4. MOTION RENDERING ---
    _notify("motion", "processing", 65)
    motion_start = _utc_now()
    has_motion = any(c.visual_type in (VisualType.data, VisualType.text) for c in planned_project.visual_cues)

    if has_motion:
        motion_input_file = (
            task_dir / "project.assets.json"
            if (task_dir / "project.assets.json").exists()
            else task_dir / "project.planned.json"
        )
        try:
            motion_res = run_motion_render(str(motion_input_file), task_id=run_task_id)
            m_status = (
                ExecutionStageStatus.complete
                if motion_res.get("status") == "complete"
                else ExecutionStageStatus.failed
            )
            stages_records.append(
                StageExecutionRecord(
                    name="motion",
                    status=m_status,
                    started_at=motion_start,
                    completed_at=_utc_now(),
                    input_file=str(motion_input_file.resolve()),
                    output_file=str((task_dir / "project.motion.json").resolve()),
                    manifest_file=str((task_dir / "motion" / "motion_manifest.json").resolve()),
                    ready_count=motion_res.get("rendered_scenes_count", 0),
                    failed_count=motion_res.get("failed_scenes_count", 0),
                    error=sanitize_error_message(motion_res.get("error")),
                )
            )
        except Exception as exc:
            err = f"Motion stage exception: {exc}"
            logger.warning(err)
            stages_records.append(
                StageExecutionRecord(
                    name="motion",
                    status=ExecutionStageStatus.failed,
                    started_at=motion_start,
                    completed_at=_utc_now(),
                    error=sanitize_error_message(err),
                )
            )
    else:
        stages_records.append(
            StageExecutionRecord(
                name="motion",
                status=ExecutionStageStatus.complete,
                started_at=motion_start,
                completed_at=_utc_now(),
                ready_count=0,
                failed_count=0,
                skipped_count=0,
                metadata={"skipped_reason": "No DATA or TEXT visual cues in project"},
            )
        )

    # --- 5. EVIDENCE ACQUISITION ---
    _notify("evidence", "processing", 85)
    evidence_start = _utc_now()
    has_evidence = any(c.visual_type == VisualType.document for c in planned_project.visual_cues)

    if has_evidence:
        if (task_dir / "project.motion.json").exists():
            ev_input_file = task_dir / "project.motion.json"
        elif (task_dir / "project.assets.json").exists():
            ev_input_file = task_dir / "project.assets.json"
        else:
            ev_input_file = task_dir / "project.planned.json"

        try:
            ev_res = run_evidence_acquisition(str(ev_input_file), task_id=run_task_id)
            ev_status = (
                ExecutionStageStatus.complete
                if ev_res.get("status") == "complete"
                else ExecutionStageStatus.failed
            )
            stages_records.append(
                StageExecutionRecord(
                    name="evidence",
                    status=ev_status,
                    started_at=evidence_start,
                    completed_at=_utc_now(),
                    input_file=str(ev_input_file.resolve()),
                    output_file=str((task_dir / "project.evidence.json").resolve()),
                    manifest_file=str((task_dir / "evidence" / "evidence_manifest.json").resolve()),
                    ready_count=ev_res.get("rendered_scenes_count", 0),
                    failed_count=ev_res.get("failed_scenes_count", 0),
                    skipped_count=ev_res.get("skipped_scenes_count", 0),
                    error=sanitize_error_message(ev_res.get("error")),
                )
            )
        except Exception as exc:
            err = f"Evidence stage exception: {exc}"
            logger.warning(err)
            stages_records.append(
                StageExecutionRecord(
                    name="evidence",
                    status=ExecutionStageStatus.failed,
                    started_at=evidence_start,
                    completed_at=_utc_now(),
                    error=sanitize_error_message(err),
                )
            )
    else:
        stages_records.append(
            StageExecutionRecord(
                name="evidence",
                status=ExecutionStageStatus.complete,
                started_at=evidence_start,
                completed_at=_utc_now(),
                ready_count=0,
                failed_count=0,
                skipped_count=0,
                metadata={"skipped_reason": "No DOCUMENT visual cues in project"},
            )
        )

    # --- 6. FALLBACK (Optional DOCUMENT -> TEXT) ---
    _notify("fallback", "processing", 95)
    fallback_start = _utc_now()
    fallback_ready_count = 0
    fallback_failed_count = 0

    # Load highest available state
    if (task_dir / "project.evidence.json").exists():
        current_project_file = task_dir / "project.evidence.json"
    elif (task_dir / "project.motion.json").exists():
        current_project_file = task_dir / "project.motion.json"
    elif (task_dir / "project.assets.json").exists():
        current_project_file = task_dir / "project.assets.json"
    else:
        current_project_file = task_dir / "project.planned.json"

    working_project = load_project_spec(current_project_file)

    for cue in working_project.visual_cues:
        if cue.visual_type == VisualType.document:
            payload = DocumentPayload.model_validate(cue.payload)
            if not payload.evidence_required:
                # Check if evidence output exists
                existing_doc_job = next((j for j in working_project.render_jobs if j.scene_id == cue.id), None)
                has_valid_evidence = (
                    existing_doc_job is not None
                    and existing_doc_job.status == JobStatus.ready
                    and existing_doc_job.output
                    and existing_doc_job.output != "skipped"
                    and Path(existing_doc_job.output).exists()
                )

                if not has_valid_evidence:
                    logger.info(f"Rendering TEXT fallback for optional DOCUMENT scene {cue.id}")
                    fb_job, fb_asset, fb_err = _render_text_fallback_scene(cue, working_project, task_dir)
                    # Replace or append render job
                    working_project.render_jobs = [j for j in working_project.render_jobs if j.scene_id != cue.id] + [fb_job]
                    if fb_job.status == JobStatus.ready:
                        fallback_ready_count += 1
                    else:
                        fallback_failed_count += 1

    stages_records.append(
        StageExecutionRecord(
            name="fallback",
            status=ExecutionStageStatus.complete if fallback_failed_count == 0 else ExecutionStageStatus.failed,
            started_at=fallback_start,
            completed_at=_utc_now(),
            ready_count=fallback_ready_count,
            failed_count=fallback_failed_count,
        )
    )

    # --- 7. FINAL VALIDATION & RECONCILIATION ---
    _notify("finalize", "processing", 98)
    finalize_start = _utc_now()

    sorted_cues = sorted(working_project.visual_cues, key=lambda c: c.order)
    scene_records: list[SceneExecutionRecord] = []
    fps = working_project.project.fps or 30
    aspect = working_project.project.aspect_ratio
    target_width, target_height = aspect.to_resolution()

    for cue in sorted_cues:
        start_frame = round((cue.start or 0.0) * fps)
        end_frame = round((cue.end or 0.0) * fps)
        duration_frames = max(1, end_frame - start_frame)
        expected_duration = duration_frames / float(fps)

        planned_type = cue.visual_type
        resolved_type = cue.visual_type
        fallback_from = None
        fallback_reason = None
        source_stage = None
        output_file = None
        asset_job_id = None
        render_job_id = None
        scene_status = "failed"
        scene_error = None

        if cue.visual_type == VisualType.broll:
            source_stage = "broll"
            broll_job = next((j for j in working_project.asset_jobs if j.scene_id == cue.id), None)
            if broll_job:
                asset_job_id = broll_job.id
                if broll_job.status == JobStatus.ready and broll_job.output:
                    output_file = broll_job.output

        elif cue.visual_type in (VisualType.data, VisualType.text):
            source_stage = "motion"
            motion_job = next((j for j in working_project.render_jobs if j.scene_id == cue.id), None)
            if motion_job:
                render_job_id = motion_job.id
                if motion_job.status == JobStatus.ready and motion_job.output:
                    output_file = motion_job.output

        elif cue.visual_type == VisualType.document:
            doc_job = next((j for j in working_project.render_jobs if j.scene_id == cue.id), None)
            if doc_job and doc_job.kind == "text_fallback":
                source_stage = "fallback"
                resolved_type = VisualType.text
                fallback_from = VisualType.document
                fallback_reason = doc_job.metadata.get("fallback_reason", "optional evidence unavailable")
                render_job_id = doc_job.id
                if doc_job.status == JobStatus.ready and doc_job.output:
                    output_file = doc_job.output
            elif doc_job:
                source_stage = "evidence"
                render_job_id = doc_job.id
                if doc_job.status == JobStatus.ready and doc_job.output and doc_job.output != "skipped":
                    output_file = doc_job.output

        # Validate media output file
        if output_file and output_file != "skipped" and Path(output_file).exists():
            p_out = Path(output_file).resolve()
            try:
                if resolved_type == VisualType.broll:
                    validate_rendered_clip(
                        rendered_path=p_out,
                        scene_duration=expected_duration,
                        target_width=target_width,
                        target_height=target_height,
                        target_fps=fps,
                    )
                elif resolved_type in (VisualType.data, VisualType.text):
                    validate_rendered_motion_clip(
                        rendered_path=p_out,
                        expected_duration_frames=duration_frames,
                        expected_width=target_width,
                        expected_height=target_height,
                        expected_fps=fps,
                    )
                elif resolved_type == VisualType.document:
                    validate_rendered_evidence_clip(
                        rendered_path=p_out,
                        expected_duration_frames=duration_frames,
                        expected_width=target_width,
                        expected_height=target_height,
                        expected_fps=fps,
                    )
                scene_status = "ready"
                cue.status = JobStatus.ready
            except Exception as v_exc:
                scene_status = "failed"
                cue.status = JobStatus.failed
                scene_error = f"Media validation failed: {v_exc}"
                logger.warning(f"Scene {cue.id} validation failed: {scene_error}")
        else:
            scene_status = "failed"
            cue.status = JobStatus.failed
            scene_error = f"Output file missing or not rendered for {cue.id}"

        scene_records.append(
            SceneExecutionRecord(
                scene_id=cue.id,
                order=cue.order,
                planned_visual_type=planned_type,
                resolved_visual_type=resolved_type,
                purpose=cue.purpose,
                start=cue.start,
                end=cue.end,
                start_frame=start_frame,
                end_frame=end_frame,
                duration_frames=duration_frames,
                status=scene_status,
                output_file=output_file if scene_status == "ready" else None,
                source_stage=source_stage,
                asset_job_id=asset_job_id,
                render_job_id=render_job_id,
                fallback_from=fallback_from,
                fallback_reason=fallback_reason,
                error=scene_error if scene_status == "failed" else None,
            )
        )

    # Sort jobs by scene order
    cue_order_map = {c.id: c.order for c in sorted_cues}
    working_project.asset_jobs = sorted(working_project.asset_jobs, key=lambda j: cue_order_map.get(j.scene_id, 0))
    working_project.render_jobs = sorted(working_project.render_jobs, key=lambda j: cue_order_map.get(j.scene_id, 0))

    ready_count = sum(1 for s in scene_records if s.status == "ready")
    failed_count = sum(1 for s in scene_records if s.status == "failed")
    overall_status = (
        ExecutionStageStatus.complete
        if (failed_count == 0 and ready_count == len(sorted_cues))
        else ExecutionStageStatus.failed
    )

    stages_records.append(
        StageExecutionRecord(
            name="finalize",
            status=ExecutionStageStatus.complete if overall_status == ExecutionStageStatus.complete else ExecutionStageStatus.failed,
            started_at=finalize_start,
            completed_at=_utc_now(),
            ready_count=ready_count,
            failed_count=failed_count,
        )
    )

    # Outputs mapping
    manifest_outputs: dict[str, Any] = {
        "planned_project_file": str((task_dir / "project.planned.json").resolve()),
        "timeline_file": str((task_dir / "timeline.json").resolve()),
        "visual_plan_file": str((task_dir / "visual_plan.json").resolve()),
        "executed_project_file": str((task_dir / "project.executed.json").resolve()),
    }
    if (task_dir / "broll_manifest.json").exists():
        manifest_outputs["broll_manifest_file"] = str((task_dir / "broll_manifest.json").resolve())
    if (task_dir / "motion" / "motion_manifest.json").exists():
        manifest_outputs["motion_manifest_file"] = str((task_dir / "motion" / "motion_manifest.json").resolve())
    if (task_dir / "evidence" / "evidence_manifest.json").exists():
        manifest_outputs["evidence_manifest_file"] = str((task_dir / "evidence" / "evidence_manifest.json").resolve())

    # Build and save execution manifest
    execution_manifest = ExecutionManifest(
        schema_version="1.0",
        project_title=project_spec.project.title,
        task_id=run_task_id,
        source_project_file=source_project_file or str(source_path),
        source_project_fingerprint=project_fingerprint,
        source_registry_sha256=source_registry_sha256,
        status=overall_status,
        progress_percent=100,
        stages=stages_records,
        scenes=scene_records,
        ready_scene_count=ready_count,
        failed_scene_count=failed_count,
        created_at=created_at,
        updated_at=_utc_now(),
        error=None if overall_status == ExecutionStageStatus.complete else f"{failed_count} scenes failed execution",
        outputs=manifest_outputs,
    )

    # Save project.executed.json and execution_manifest.json atomically
    save_project_spec(working_project, task_dir / "project.executed.json")
    _atomic_write_json(task_dir / "execution_manifest.json", execution_manifest.model_dump(mode="json"))

    # Reconcile project_manifest.json
    project_manifest_file = task_dir / "project_manifest.json"
    if project_manifest_file.exists():
        try:
            p_manifest = ProjectManifest.model_validate(json.loads(project_manifest_file.read_text(encoding="utf-8")))
            p_manifest.status = ProjectStatus.complete if overall_status == ExecutionStageStatus.complete else ProjectStatus.failed
            p_manifest.updated_at = datetime.now(timezone.utc)
            p_manifest.outputs["execution_manifest_file"] = str((task_dir / "execution_manifest.json").resolve())
            p_manifest.outputs["executed_project_file"] = str((task_dir / "project.executed.json").resolve())

            # Current stage errors
            current_stage_errors = [
                s.error for s in stages_records if s.error and s.status == ExecutionStageStatus.failed
            ]
            p_manifest.outputs["stage_errors"] = current_stage_errors
            p_manifest.error = None if overall_status == ExecutionStageStatus.complete else ("; ".join(current_stage_errors) if current_stage_errors else f"{failed_count} scenes failed")
            _atomic_write_json(project_manifest_file, p_manifest.model_dump(mode="json"))
        except Exception as pm_exc:
            logger.warning(f"project_manifest.json reconciliation warning: {pm_exc}")

    _notify("finalize", "complete" if overall_status == ExecutionStageStatus.complete else "failed", 100)

    return {
        "status": overall_status.value,
        "task_id": run_task_id,
        "ready_scenes": ready_count,
        "failed_scenes": failed_count,
        "execution_manifest": str((task_dir / "execution_manifest.json").resolve()),
        "project_executed": str((task_dir / "project.executed.json").resolve()),
    }
