from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from app.models.evidence import EvidenceSourceRegistry
from app.models.execution import ExecutionManifest
from app.models.export import (
    EditManifest,
    EditorPackageStatus,
    EditorSceneEntry,
    EditorSourceEntry,
    ExportResult,
)
from app.models.project import (
    JobStatus,
    ProjectSpec,
    TimelinePlan,
    VisualType,
)
from app.services.evidence_sources import compute_file_sha256, sanitize_secret_url
from app.services.project_runner import ProjectRunError
from app.services.project_spec import load_project_spec
from app.services.scene_orchestrator import compute_project_input_fingerprint, resolve_final_render_job
from app.services.visual_planner import (
    normalize_visual_cue_boundaries,
    validate_scene_timeline_coverage,
)
from app.utils import utils


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_project_title(title: str) -> str:
    """Generate deterministic Windows-safe filesystem slug from project title."""
    if not title or not title.strip():
        return "untitled-project"
    cleaned = title.strip().lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"[\s_-]+", "-", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned[:64] or "project"


def copy_file_verified(src: Path, dest: Path) -> str:
    """Copy file safely with temporary write, SHA-256 verification, and atomic rename.

    Returns the verified SHA-256 hash.
    """
    src = Path(src).resolve()
    dest = Path(dest).resolve()

    if not src.exists() or not src.is_file():
        raise FileNotFoundError(f"Source file does not exist: {src}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    src_sha = compute_file_sha256(src)

    # Check if dest already exists and matches hash
    if dest.exists() and dest.is_file():
        if compute_file_sha256(dest) == src_sha:
            return src_sha

    nonce = hashlib.md5(str(os.urandom(8)).encode()).hexdigest()[:6]
    tmp_dest = dest.with_suffix(dest.suffix + f".tmp.{os.getpid()}.{nonce}")
    try:
        shutil.copy2(src, tmp_dest)
        dest_sha = compute_file_sha256(tmp_dest)
        if dest_sha != src_sha:
            raise IOError(f"SHA-256 mismatch during copy: {src_sha} vs {dest_sha}")
        tmp_dest.replace(dest)
        return dest_sha
    finally:
        if tmp_dest.exists():
            try:
                tmp_dest.unlink()
            except Exception:
                pass


def format_seconds_to_srt_time(seconds: float) -> str:
    """Convert float seconds to SRT time format HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    ms = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def convert_timing_to_srt(timing_path: Path, dest_srt: Path) -> bool:
    """Deterministically convert structured timing JSON/SRT to standard SRT format without LLM rewrite."""
    timing_path = Path(timing_path).resolve()
    if not timing_path.exists() or timing_path.stat().st_size == 0:
        return False

    # If already an SRT file
    if timing_path.suffix.lower() == ".srt":
        copy_file_verified(timing_path, dest_srt)
        return True

    # Try parsing JSON timing
    try:
        raw_text = timing_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except Exception:
        return False

    segments: list[dict[str, Any]] = []
    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict):
        if "segments" in data and isinstance(data["segments"], list):
            segments = data["segments"]
        elif "cues" in data and isinstance(data["cues"], list):
            segments = data["cues"]

    if not segments:
        return False

    srt_entries: list[str] = []
    index = 1

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        start = seg.get("start")
        end = seg.get("end")
        text = seg.get("text") or seg.get("narration") or seg.get("word") or ""
        text = str(text).strip()

        if start is None or end is None or not text:
            continue

        try:
            start_f = float(start)
            end_f = float(end)
            if end_f <= start_f:
                continue
        except (ValueError, TypeError):
            continue

        start_str = format_seconds_to_srt_time(start_f)
        end_str = format_seconds_to_srt_time(end_f)

        srt_entries.append(f"{index}\n{start_str} --> {end_str}\n{text}\n")
        index += 1

    if not srt_entries:
        return False

    dest_srt.parent.mkdir(parents=True, exist_ok=True)
    nonce = hashlib.md5(str(os.urandom(8)).encode()).hexdigest()[:6]
    tmp_srt = dest_srt.with_suffix(dest_srt.suffix + f".tmp.{os.getpid()}.{nonce}")
    try:
        tmp_srt.write_text("\n".join(srt_entries).strip() + "\n", encoding="utf-8")
        tmp_srt.replace(dest_srt)
        return True
    finally:
        if tmp_srt.exists():
            try:
                tmp_srt.unlink()
            except Exception:
                pass


def generate_readme_edit(manifest: EditManifest) -> str:
    """Generate deterministic edit instructions markdown for NLE editors."""
    res_str = f"{manifest.resolution[0]}x{manifest.resolution[1]}" if len(manifest.resolution) == 2 else "1920x1080"
    lines = [
        f"# Edit Package: {manifest.project_title}",
        "",
        "## Technical Specifications",
        f"- **Project Slug**: `{manifest.project_slug}`",
        f"- **Task ID**: `{manifest.task_id}`",
        f"- **Package Status**: `{manifest.package_status.value.upper()}`",
        f"- **Resolution**: `{res_str}`",
        f"- **Aspect Ratio**: `{manifest.aspect_ratio}`",
        f"- **Target Frame Rate**: `{manifest.fps} FPS`",
        f"- **Total Duration**: `{manifest.duration_seconds:.2f}s` (`{manifest.duration_frames}` frames)",
        "",
        "## Audio & Subtitle Tracks",
    ]

    if manifest.narration_file:
        lines.append(f"- **Narration Audio**: `{manifest.narration_file}` (SHA-256: `{manifest.narration_sha256}`)")
    else:
        lines.append("- **Narration Audio**: None / Not Available")

    if manifest.subtitle_file:
        lines.append(f"- **Subtitle File**: `{manifest.subtitle_file}` (SHA-256: `{manifest.subtitle_sha256}`)")
    else:
        reason = manifest.missing_subtitle_reason or "No subtitle timing file found"
        lines.append(f"- **Subtitle File**: None ({reason})")

    lines.extend([
        "",
        "## Clean Scene Assets",
        "> [!IMPORTANT]",
        "> All scene MP4 video files in `scenes/` are **intentionally silent** clean visual tracks.",
        "> Narration audio is provided as a continuous track in `narration/`.",
        "",
        "| Scene ID | Order | File | Planned Type | Resolved Type | Duration | Status | Notes |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for sc in manifest.scenes:
        fname = f"`{sc.exported_file}`" if sc.exported_file else "*MISSING*"
        dur_str = f"{sc.duration_frames}f ({sc.duration_frames / manifest.fps:.2f}s)" if sc.duration_frames else "N/A"
        notes = []
        if sc.fallback_from:
            notes.append(f"Fallback from {sc.fallback_from.value.upper()} ({sc.fallback_reason or 'optional evidence unavailable'})")
        if sc.provenance_reference and "source_title" in sc.provenance_reference:
            notes.append(f"Source: {sc.provenance_reference['source_title']}")
        notes_str = "; ".join(notes) if notes else "-"
        status_str = "READY" if sc.exported_file else "MISSING"

        lines.append(
            f"| `{sc.scene_id}` | {sc.order} | {fname} | {sc.planned_visual_type.value.upper()} | {sc.resolved_visual_type.value.upper()} | {dur_str} | {status_str} | {notes_str} |"
        )

    lines.extend([
        "",
        "## NLE Timeline Assembly Guide",
        "1. **Video Track 1**: Place scene video files sequentially from `scenes/` in exact numerical order (`S001`, `S002`, ...). Each clip is trimmed to exact frame duration.",
        "2. **Audio Track 1**: Align `narration/narration.<ext>` to start at timeline `00:00:00:00`.",
        "3. **Subtitle Track**: Import `narration/subtitle.srt` if present.",
        "4. **BGM / Transitions**: Apply cross-scene transitions or background music at timeline edit boundaries if desired.",
        "",
        "---",
        f"*Generated automatically on {manifest.created_at} by Video Research & Asset Builder.*",
    ])

    return "\n".join(lines) + "\n"


def compute_export_fingerprint(
    source_project_fingerprint: str,
    scene_shas: list[str | None],
    narration_sha: str | None,
    subtitle_sha: str | None,
    fps: int,
    resolution: list[int],
) -> str:
    """Compute deterministic SHA-256 fingerprint for export package contents and configuration."""
    canonical = {
        "schema_version": "1.0",
        "source_project_fingerprint": source_project_fingerprint,
        "scene_shas": scene_shas,
        "narration_sha": narration_sha,
        "subtitle_sha": subtitle_sha,
        "fps": fps,
        "resolution": resolution,
    }
    dumped = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def probe_media_frames(video_file: Path | str, fps: int = 30) -> int:
    """Probe physical video frame count using ffprobe or VideoFileClip fallback."""
    video_file = Path(video_file).resolve()
    if not video_file.exists() or video_file.stat().st_size == 0:
        return 0
    fps = max(1, fps)
    ffmpeg_bin = utils.get_ffmpeg_binary()
    ffprobe_bin = ffmpeg_bin.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg", "ffprobe") if ffmpeg_bin else "ffprobe"
    try:
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration:stream=nb_frames,duration,r_frame_rate",
            "-of", "json",
            str(video_file),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            for stm in streams:
                if "nb_frames" in stm and stm["nb_frames"].isdigit():
                    return int(stm["nb_frames"])
                if "duration" in stm:
                    try:
                        return round(float(stm["duration"]) * fps)
                    except (ValueError, TypeError):
                        pass
            if "format" in data and "duration" in data["format"]:
                return round(float(data["format"]["duration"]) * fps)
    except Exception:
        pass

    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip
        clip = VideoFileClip(str(video_file))
        dur = float(clip.duration or 0.0)
        clip.close()
        return round(dur * fps)
    except Exception:
        return 0


def _resolve_file_path(p_str: str | Path | None, base_dir: Path) -> Path | None:
    """Resolve file path against base_dir if relative or if base_dir has it."""
    if not p_str or str(p_str) == "skipped":
        return None
    p = Path(p_str)
    if p.is_absolute() and p.exists() and p.is_file():
        return p
    candidate = (base_dir / p).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate
    if p.exists() and p.is_file():
        return p.resolve()
    return None


def export_editor_package(
    project_input: str | Path | ProjectSpec,
    task_id: str | None = None,
    output_dir: str | Path | None = None,
) -> ExportResult:
    """Convert an executed task workspace into a deterministic, portable editor package (G09).

    Does NOT assemble final.mp4.
    """
    # 1. Resolve project input and task directory
    if isinstance(project_input, (str, Path)):
        source_project_path = Path(project_input).expanduser().resolve()
        project_spec = load_project_spec(source_project_path)
    else:
        source_project_path = None
        project_spec = project_input

    run_task_id = task_id or utils.get_uuid()
    task_dir = Path(utils.task_dir(run_task_id)).resolve()

    source_project_fingerprint = compute_project_input_fingerprint(project_spec)
    project_slug = slugify_project_title(project_spec.project.title)

    # 2. Determine export output directory
    if output_dir:
        export_path = Path(output_dir).expanduser().resolve()
    else:
        export_path = Path.cwd() / "exports" / project_slug

    export_path.mkdir(parents=True, exist_ok=True)
    narration_dir = export_path / "narration"
    scenes_dir = export_path / "scenes"
    sources_dir = export_path / "sources"

    narration_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)

    # 3. Load runtime state
    executed_project_file = task_dir / "project.executed.json"
    if not executed_project_file.exists():
        if (task_dir / "project.evidence.json").exists():
            executed_project_file = task_dir / "project.evidence.json"
        elif (task_dir / "project.motion.json").exists():
            executed_project_file = task_dir / "project.motion.json"
        elif (task_dir / "project.assets.json").exists():
            executed_project_file = task_dir / "project.assets.json"
        elif (task_dir / "project.planned.json").exists():
            executed_project_file = task_dir / "project.planned.json"
        else:
            executed_project_file = task_dir / "project.json"

    if executed_project_file.exists():
        working_project = load_project_spec(executed_project_file)
    else:
        working_project = project_spec

    exec_manifest_file = task_dir / "execution_manifest.json"
    exec_manifest: ExecutionManifest | None = None
    if exec_manifest_file.exists():
        try:
            exec_manifest = ExecutionManifest.model_validate_json(exec_manifest_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Could not parse execution_manifest.json: {exc}")

    timeline_file = task_dir / "timeline.json"
    timeline_plan: TimelinePlan | None = None
    if timeline_file.exists():
        try:
            timeline_plan = TimelinePlan.model_validate_json(timeline_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Could not parse timeline.json: {exc}")

    # 4. Resolve technical parameters
    fps = working_project.project.fps or 30
    aspect = working_project.project.aspect_ratio
    width, height = aspect.to_resolution()
    aspect_str = aspect.value if hasattr(aspect, "value") else str(aspect)

    # 5. Export Narration
    exported_narration_rel: str | None = None
    exported_narration_sha: str | None = None

    narration_src: Path | None = None
    if timeline_plan and timeline_plan.audio_file:
        narration_src = _resolve_file_path(timeline_plan.audio_file, task_dir)
    elif working_project.narration.file:
        narration_src = _resolve_file_path(working_project.narration.file, task_dir)
    elif (task_dir / "narration.mp3").exists():
        narration_src = task_dir / "narration.mp3"

    if narration_src and narration_src.exists() and narration_src.stat().st_size > 0:
        ext = narration_src.suffix or ".mp3"
        dest_narration = narration_dir / f"narration{ext}"
        exported_narration_sha = copy_file_verified(narration_src, dest_narration)
        exported_narration_rel = f"narration/narration{ext}"

    # 6. Export Subtitle
    exported_subtitle_rel: str | None = None
    exported_subtitle_sha: str | None = None
    missing_sub_reason: str | None = None

    timing_src: Path | None = None
    if timeline_plan and timeline_plan.timing_file:
        timing_src = _resolve_file_path(timeline_plan.timing_file, task_dir)
    elif working_project.narration.timing_file:
        timing_src = _resolve_file_path(working_project.narration.timing_file, task_dir)
    elif (task_dir / "subtitle.srt").exists():
        timing_src = task_dir / "subtitle.srt"
    elif (task_dir / "timing.json").exists():
        timing_src = task_dir / "timing.json"

    if timing_src and timing_src.exists() and timing_src.stat().st_size > 0:
        dest_srt = narration_dir / "subtitle.srt"
        if convert_timing_to_srt(timing_src, dest_srt):
            exported_subtitle_sha = compute_file_sha256(dest_srt)
            exported_subtitle_rel = "narration/subtitle.srt"
        else:
            missing_sub_reason = f"Timing file could not be parsed into SRT: {timing_src.name}"
    else:
        missing_sub_reason = "No subtitle or timing file found in workspace"

    # 7. Export Scenes
    sorted_cues = sorted(working_project.visual_cues or [], key=lambda c: c.order)
    if sorted_cues:
        sorted_cues = normalize_visual_cue_boundaries(
            sorted_cues,
            fps=fps,
            total_duration_seconds=timeline_plan.duration if timeline_plan else None,
        )
    exported_scenes: list[EditorSceneEntry] = []
    missing_scene_ids: list[str] = []
    scene_shas: list[str | None] = []

    total_duration_frames = 0

    for cue in sorted_cues:
        start_frame = round((cue.start or 0.0) * fps)
        end_frame = round((cue.end or 0.0) * fps)
        duration_frames = max(1, end_frame - start_frame)
        total_duration_frames = max(total_duration_frames, end_frame)

        planned_type = cue.visual_type
        resolved_type = cue.visual_type
        fallback_from = None
        fallback_reason = None
        source_stage = None
        output_src_file: Path | None = None
        provenance_ref: dict[str, Any] = {}

        # Check AssetJobs (BROLL)
        if cue.visual_type == VisualType.broll:
            source_stage = "broll"
            broll_job = next((j for j in working_project.asset_jobs if j.scene_id == cue.id), None)
            if broll_job and broll_job.status == JobStatus.ready and broll_job.output:
                output_src_file = _resolve_file_path(broll_job.output, task_dir)
                if output_src_file and broll_job.metadata:
                    provenance_ref["query"] = broll_job.metadata.get("query")
                    provenance_ref["provider"] = broll_job.metadata.get("provider")
                    if broll_job.metadata.get("asset_url"):
                        provenance_ref["asset_url"] = sanitize_secret_url(broll_job.metadata["asset_url"])

        # Check RenderJobs (Motion, Document, Fallback)
        else:
            resolved_job = resolve_final_render_job(cue.id, working_project.render_jobs)
            if resolved_job:
                if resolved_job.kind == "text_fallback":
                    source_stage = "fallback"
                    resolved_type = VisualType.text
                    fallback_from = VisualType.document
                    fallback_reason = resolved_job.metadata.get("fallback_reason", "optional evidence unavailable")
                    if resolved_job.status == JobStatus.ready and resolved_job.output:
                        output_src_file = _resolve_file_path(resolved_job.output, task_dir)
                elif resolved_job.kind in ("motion", "data", "text"):
                    source_stage = "motion"
                    if resolved_job.status == JobStatus.ready and resolved_job.output:
                        output_src_file = _resolve_file_path(resolved_job.output, task_dir)
                elif resolved_job.kind == "document":
                    source_stage = "evidence"
                    if resolved_job.status == JobStatus.ready and resolved_job.output and resolved_job.output != "skipped":
                        output_src_file = _resolve_file_path(resolved_job.output, task_dir)
                        if resolved_job.metadata:
                            provenance_ref["source_id"] = resolved_job.metadata.get("selected_source_id")
                            provenance_ref["source_title"] = resolved_job.metadata.get("source_title")
                            provenance_ref["page_number"] = resolved_job.metadata.get("page_number")
                else:
                    source_stage = "motion"
                    if resolved_job.status == JobStatus.ready and resolved_job.output:
                        output_src_file = _resolve_file_path(resolved_job.output, task_dir)

        scene_rel_path: str | None = None
        scene_sha: str | None = None

        if output_src_file and output_src_file.exists():
            dest_scene_filename = f"S{cue.order:03d}_{resolved_type.value.upper()}.mp4"
            dest_scene_file = scenes_dir / dest_scene_filename
            scene_sha = copy_file_verified(output_src_file, dest_scene_file)
            scene_rel_path = f"scenes/{dest_scene_filename}"
        else:
            missing_scene_ids.append(cue.id)

        scene_shas.append(scene_sha)

        exported_scenes.append(
            EditorSceneEntry(
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
                exported_file=scene_rel_path,
                sha256=scene_sha,
                source_stage=source_stage,
                fallback_from=fallback_from,
                fallback_reason=fallback_reason,
                provenance_reference=provenance_ref,
            )
        )

    # 8. Export Source Provenance (`sources/source_manifest.json`)
    source_provenance_entries: list[EditorSourceEntry] = []

    # Check for sources.json
    sources_reg_path = task_dir / "sources.json"
    if not sources_reg_path.exists() and source_project_path:
        sources_reg_path = source_project_path.parent / "sources.json"

    if sources_reg_path.exists():
        try:
            reg_data = json.loads(sources_reg_path.read_text(encoding="utf-8"))
            reg = EvidenceSourceRegistry.model_validate(reg_data)
            for src in reg.sources:
                used_scenes = [
                    c.id for c in sorted_cues
                    if c.visual_type == VisualType.document and (c.payload or {}).get("source_ids") and src.id in (c.payload or {}).get("source_ids", [])
                ]
                source_provenance_entries.append(
                    EditorSourceEntry(
                        source_id=src.id,
                        kind=src.kind.value if hasattr(src.kind, "value") else str(src.kind),
                        title=src.title,
                        publisher=src.publisher,
                        trust=src.trust.value if hasattr(src.trust, "value") else str(src.trust),
                        license=src.license,
                        url=sanitize_secret_url(src.url) if src.url else None,
                        local_file=src.local_file,
                        sha256=compute_file_sha256(Path(src.local_file)) if (src.local_file and Path(src.local_file).exists()) else None,
                        used_in_scenes=used_scenes,
                        metadata=src.metadata,
                    )
                )
        except Exception as exc:
            logger.warning(f"Could not aggregate sources.json into source manifest: {exc}")

    # Write sources/source_manifest.json
    source_manifest_file = sources_dir / "source_manifest.json"
    source_manifest_data = {
        "schema_version": "1.0",
        "project_title": working_project.project.title,
        "task_id": run_task_id,
        "sources": [s.model_dump(mode="json") for s in source_provenance_entries],
        "created_at": _utc_now(),
    }
    source_manifest_file.write_text(json.dumps(source_manifest_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 9. Copy project specs and execution manifest to root
    if (task_dir / "project.json").exists():
        copy_file_verified(task_dir / "project.json", export_path / "project.json")
    elif source_project_path and source_project_path.exists():
        copy_file_verified(source_project_path, export_path / "project.json")

    if (task_dir / "project.executed.json").exists():
        copy_file_verified(task_dir / "project.executed.json", export_path / "project.executed.json")
    elif executed_project_file.exists():
        copy_file_verified(executed_project_file, export_path / "project.executed.json")

    if exec_manifest_file.exists():
        copy_file_verified(exec_manifest_file, export_path / "execution_manifest.json")

    # 10. Determine package status
    ready_count = sum(1 for s in exported_scenes if s.exported_file is not None)
    total_scenes = len(exported_scenes)
    if total_scenes == 0 or ready_count == 0:
        pkg_status = EditorPackageStatus.failed
    elif ready_count == total_scenes:
        pkg_status = EditorPackageStatus.complete
    else:
        pkg_status = EditorPackageStatus.partial

    export_error: str | None = None

    # Invariant: A COMPLETE editor package must not contain hidden timeline holes or stale physical media.
    if pkg_status == EditorPackageStatus.complete:
        is_cov_valid, cov_errors = validate_scene_timeline_coverage(
            exported_scenes,
            expected_duration_frames=total_duration_frames,
            fps=fps,
        )
        if not is_cov_valid:
            export_error = f"Timeline coverage validation failed: {'; '.join(cov_errors)}"
            logger.error(f"Editor package timeline coverage validation failed: {cov_errors}")
            pkg_status = EditorPackageStatus.failed
        else:
            # Physical media duration validation against manifest duration_frames
            for sc in exported_scenes:
                if sc.exported_file:
                    sc_video_path = export_path / sc.exported_file
                    actual_frames = probe_media_frames(sc_video_path, fps=fps)
                    if actual_frames > 0 and abs(actual_frames - sc.duration_frames) > 2:
                        pkg_status = EditorPackageStatus.failed
                        export_error = (
                            f"Stale scene asset {sc.scene_id}: expected {sc.duration_frames} frames, "
                            f"media contains {actual_frames} frames. Resume production to rerender scene assets."
                        )
                        logger.error(export_error)
                        break

    duration_seconds = total_duration_frames / float(fps) if fps else 0.0

    export_fp = compute_export_fingerprint(
        source_project_fingerprint=source_project_fingerprint,
        scene_shas=scene_shas,
        narration_sha=exported_narration_sha,
        subtitle_sha=exported_subtitle_sha,
        fps=fps,
        resolution=[width, height],
    )

    # 11. Build and write edit_manifest.json
    now_iso = _utc_now()
    edit_manifest = EditManifest(
        schema_version="1.0",
        project_title=working_project.project.title,
        project_slug=project_slug,
        task_id=run_task_id,
        source_project_fingerprint=source_project_fingerprint,
        export_fingerprint=export_fp,
        package_status=pkg_status,
        fps=fps,
        resolution=[width, height],
        aspect_ratio=aspect_str,
        duration_frames=total_duration_frames,
        duration_seconds=duration_seconds,
        narration_file=exported_narration_rel,
        narration_sha256=exported_narration_sha,
        subtitle_file=exported_subtitle_rel,
        subtitle_sha256=exported_subtitle_sha,
        missing_subtitle_reason=missing_sub_reason,
        scenes=exported_scenes,
        source_provenance=source_provenance_entries,
        missing_scenes=missing_scene_ids,
        created_at=now_iso,
        updated_at=now_iso,
        outputs={
            "export_dir": str(export_path.resolve()),
            "narration_dir": str(narration_dir.resolve()),
            "scenes_dir": str(scenes_dir.resolve()),
            "sources_dir": str(sources_dir.resolve()),
            "source_manifest_file": str(source_manifest_file.resolve()),
        },
    )
    
    if timeline_plan:
        edit_manifest.outputs["timing_source"] = timeline_plan.timing_source
        if timeline_plan.timing_source == "user_srt":
            edit_manifest.outputs["audio_source"] = "external"

    edit_manifest_file = export_path / "edit_manifest.json"
    edit_manifest_file.write_text(json.dumps(edit_manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 12. Build and write README_EDIT.md
    readme_file = export_path / "README_EDIT.md"
    readme_content = generate_readme_edit(edit_manifest)
    readme_file.write_text(readme_content, encoding="utf-8")

    # Ensure NO final.mp4 is created
    assert not (export_path / "final.mp4").exists(), "G09 must not assemble final.mp4"

    return ExportResult(
        status=pkg_status.value,
        task_id=run_task_id,
        export_dir=str(export_path.resolve()),
        edit_manifest_file=str(edit_manifest_file.resolve()),
        readme_file=str(readme_file.resolve()),
        ready_scene_count=ready_count,
        missing_scene_count=len(missing_scene_ids),
        error=None if pkg_status != EditorPackageStatus.failed else (export_error or f"No scenes exported for project {project_slug}"),
    )
