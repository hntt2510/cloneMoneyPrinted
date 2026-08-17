from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
)

from app.models.assembly import (
    AssemblyConfig,
    AssemblyManifest,
    AssemblyResult,
    AssemblyScene,
    AssemblyStatus,
    AudioMixConfig,
    FinalQCReport,
    SubtitleBurnConfig,
)
from app.models.export import EditManifest, EditorPackageStatus
from app.models.project import ProjectSpec
from app.services.evidence_sources import compute_file_sha256
from app.services.export_runner import (
    copy_file_verified,
    export_editor_package,
    probe_media_frames,
    slugify_project_title,
)
from app.services.project_runner import ProjectRunError
from app.services.project_spec import load_project_spec
from app.services.scene_orchestrator import compute_project_input_fingerprint
from app.services.visual_planner import validate_scene_timeline_coverage


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_assembly_fingerprint(
    export_fingerprint: str,
    scene_shas: list[str],
    narration_sha: str | None,
    subtitle_sha: str | None,
    config: AssemblyConfig,
) -> str:
    """Compute deterministic SHA-256 fingerprint for final assembly."""
    canonical = {
        "schema_version": "1.0",
        "export_fingerprint": export_fingerprint,
        "scene_shas": scene_shas,
        "narration_sha": narration_sha,
        "subtitle_sha": subtitle_sha,
        "fps": config.fps,
        "resolution": config.resolution,
        "aspect_ratio": config.aspect_ratio,
        "audio_mix": config.audio_mix.model_dump(mode="json"),
        "subtitles": config.subtitles.model_dump(mode="json"),
        "transition": config.transition,
        "video_codec": config.video_codec,
        "audio_codec": config.audio_codec,
        "audio_bitrate": config.audio_bitrate,
        "preset": config.preset,
        "crf": config.crf,
    }
    dumped = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def validate_and_inspect_final_video(
    video_path: Path,
    expected_fps: int,
    expected_resolution: list[int],
    expected_duration: float,
    require_audio: bool = True,
    duration_tolerance: float = 0.5,
) -> FinalQCReport:
    """Inspect and perform quality gate checks on final MP4 video."""
    video_path = Path(video_path).resolve()
    checks_passed: list[str] = []
    errors: list[str] = []

    if not video_path.exists() or not video_path.is_file():
        errors.append(f"Final video file does not exist: {video_path}")
        return FinalQCReport(
            is_valid=False,
            final_video_file=str(video_path),
            file_size_bytes=0,
            sha256="",
            duration_seconds=0.0,
            fps=0.0,
            resolution=[0, 0],
            has_video_stream=False,
            has_audio_stream=False,
            checks_passed=[],
            errors=errors,
        )

    file_size = video_path.stat().st_size
    if file_size == 0:
        errors.append("Final video file size is 0 bytes")

    file_sha = compute_file_sha256(video_path)

    dur = 0.0
    actual_fps = 0.0
    w, h = 0, 0
    has_audio = False
    has_video = False

    clip: VideoFileClip | None = None
    try:
        clip = VideoFileClip(str(video_path))
        has_video = True
        dur = float(clip.duration or 0.0)
        actual_fps = float(clip.fps or 0.0)
        w, h = int(clip.w or 0), int(clip.h or 0)
        has_audio = clip.audio is not None
        checks_passed.append("video_stream_decoded")
    except Exception as exc:
        errors.append(f"Failed to open video with media decoder: {exc}")
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass

    if has_video:
        # Check resolution
        if [w, h] == expected_resolution:
            checks_passed.append("resolution_matches")
        else:
            errors.append(f"Resolution mismatch: expected {expected_resolution}, got [{w}, {h}]")

        # Check fps
        if abs(actual_fps - expected_fps) <= 1.0:
            checks_passed.append("fps_matches")
        else:
            errors.append(f"FPS mismatch: expected {expected_fps}, got {actual_fps}")

        # Check duration
        if expected_duration > 0:
            if abs(dur - expected_duration) <= duration_tolerance:
                checks_passed.append("duration_matches")
            else:
                errors.append(
                    f"Duration mismatch: expected ~{expected_duration:.2f}s, got {dur:.2f}s (tolerance: {duration_tolerance}s)"
                )

        # Check audio
        if require_audio:
            if has_audio:
                checks_passed.append("audio_stream_present")
            else:
                errors.append("Expected audio stream in final assembly, but no audio stream found")
        else:
            checks_passed.append("audio_stream_optional")

    is_valid = len(errors) == 0 and has_video

    return FinalQCReport(
        is_valid=is_valid,
        final_video_file=str(video_path),
        file_size_bytes=file_size,
        sha256=file_sha,
        duration_seconds=dur,
        fps=actual_fps,
        resolution=[w, h],
        has_video_stream=has_video,
        has_audio_stream=has_audio,
        video_codec="h264",
        audio_codec="aac" if has_audio else None,
        frame_count=round(dur * actual_fps) if dur and actual_fps else None,
        checks_passed=checks_passed,
        errors=errors,
    )


def assemble_final_video(
    project_input: str | Path | dict[str, Any] | ProjectSpec,
    task_id: str | None = None,
    output_dir: str | Path | None = None,
    config: AssemblyConfig | None = None,
) -> AssemblyResult:
    """Assemble final.mp4 from G09 editor package / edit_manifest.json with QC validation.

    Preserves clean per-scene assets and creates exports/<project-slug>/final/ (or custom output_dir/final/).
    """
    if config is None:
        config = AssemblyConfig()

    source_project_path: Path | None = None
    edit_manifest: EditManifest | None = None
    export_dir: Path | None = None

    # Check if project_input is directly an edit_manifest.json file
    if isinstance(project_input, (str, Path)):
        p = Path(project_input).resolve()
        if p.is_file() and p.name == "edit_manifest.json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                edit_manifest = EditManifest.model_validate(data)
                export_dir = p.parent
            except Exception as exc:
                raise ProjectRunError(f"Invalid edit_manifest.json: {exc}")
        elif p.is_dir() and (p / "edit_manifest.json").exists():
            try:
                data = json.loads((p / "edit_manifest.json").read_text(encoding="utf-8"))
                edit_manifest = EditManifest.model_validate(data)
                export_dir = p
            except Exception as exc:
                raise ProjectRunError(f"Invalid edit_manifest.json in directory: {exc}")

    # If edit_manifest not directly provided, load project spec and find/create export package
    if edit_manifest is None:
        if isinstance(project_input, (str, Path)):
            p = Path(project_input).resolve()
            if p.is_file():
                source_project_path = p
        working_project = load_project_spec(project_input)
        run_task_id = task_id or working_project.project.task_id or "default-assembly-task"

        # Look for existing export package
        project_slug = slugify_project_title(working_project.project.title)
        candidate_paths = []
        if output_dir:
            candidate_paths.append(Path(output_dir).resolve())
        candidate_paths.extend([
            Path("exports") / project_slug,
            Path("tasks") / run_task_id / "exports" / project_slug,
            Path("tasks") / run_task_id,
        ])
        if source_project_path:
            candidate_paths.append(source_project_path.parent / "exports" / project_slug)

        for cp in candidate_paths:
            manifest_file = cp / "edit_manifest.json"
            if manifest_file.exists() and manifest_file.is_file():
                try:
                    data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    edit_manifest = EditManifest.model_validate(data)
                    export_dir = cp
                    break
                except Exception:
                    pass

        # If still not found, run export_editor_package
        if edit_manifest is None:
            logger.info("No existing edit_manifest found. Running export_editor_package first...")
            exp_res = export_editor_package(
                project_input=project_input,
                task_id=run_task_id,
                output_dir=output_dir,
            )
            if exp_res.status not in (EditorPackageStatus.complete.value, EditorPackageStatus.partial.value):
                raise ProjectRunError(f"Cannot assemble final video: editor package export failed ({exp_res.error})")
            export_dir = Path(exp_res.export_dir)
            edit_manifest_file = Path(exp_res.edit_manifest_file)
            data = json.loads(edit_manifest_file.read_text(encoding="utf-8"))
            edit_manifest = EditManifest.model_validate(data)

    assert edit_manifest is not None
    assert export_dir is not None

    # Validate failure policy: if package status is failed or missing scenes exist
    if edit_manifest.package_status == EditorPackageStatus.failed:
        raise ProjectRunError(f"Cannot assemble final video: package status is failed for {edit_manifest.project_slug}")

    if edit_manifest.missing_scenes or not edit_manifest.scenes:
        raise ProjectRunError(
            f"Cannot assemble final video: missing required scenes {edit_manifest.missing_scenes}"
        )

    for sc in edit_manifest.scenes:
        if not sc.exported_file:
            raise ProjectRunError(f"Missing scene exported file for scene {sc.scene_id}")
        scene_path = export_dir / sc.exported_file
        if not scene_path.exists():
            raise ProjectRunError(f"Scene video file does not exist: {scene_path}")
        actual_frames = probe_media_frames(scene_path, fps=edit_manifest.fps)
        if actual_frames > 0 and abs(actual_frames - sc.duration_frames) > 2:
            raise ProjectRunError(
                f"Final assembly blocked: stale scene media detected. {sc.scene_id}: "
                f"expected {sc.duration_frames} frames, actual {actual_frames} frames. Resume Production is required."
            )

    # Defense-in-depth: Validate complete timeline coverage before rendering
    is_valid_coverage, coverage_errors = validate_scene_timeline_coverage(
        edit_manifest.scenes,
        expected_duration_frames=edit_manifest.duration_frames,
        fps=edit_manifest.fps,
    )
    if not is_valid_coverage:
        err_msg = f"Timeline coverage validation failed: {'; '.join(coverage_errors)}"
        logger.error(err_msg)
        raise ProjectRunError(err_msg)

    # Prepare final output directory
    final_dir = export_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_mp4 = final_dir / "final.mp4"
    assembly_manifest_file = final_dir / "assembly_manifest.json"
    qc_report_file = final_dir / "qc_report.json"
    render_log_file = final_dir / "render.log"

    # Synchronize resolution & fps from edit_manifest if default
    config.resolution = edit_manifest.resolution
    config.fps = edit_manifest.fps
    config.aspect_ratio = edit_manifest.aspect_ratio

    # Calculate assembly fingerprint
    edit_manifest_file = export_dir / "edit_manifest.json"
    edit_manifest_sha = compute_file_sha256(edit_manifest_file)
    scene_shas = [sc.sha256 or "" for sc in edit_manifest.scenes]

    narration_sha = edit_manifest.narration_sha256
    subtitle_sha = edit_manifest.subtitle_sha256

    assembly_fp = compute_assembly_fingerprint(
        export_fingerprint=edit_manifest.export_fingerprint,
        scene_shas=scene_shas,
        narration_sha=narration_sha,
        subtitle_sha=subtitle_sha,
        config=config,
    )

    # Check for idempotent reuse
    if final_mp4.exists() and assembly_manifest_file.exists() and qc_report_file.exists():
        try:
            existing_manifest_data = json.loads(assembly_manifest_file.read_text(encoding="utf-8"))
            existing_qc_data = json.loads(qc_report_file.read_text(encoding="utf-8"))
            if (
                existing_manifest_data.get("assembly_fingerprint") == assembly_fp
                and existing_qc_data.get("is_valid") is True
                and compute_file_sha256(final_mp4) == existing_manifest_data.get("final_video_sha256")
            ):
                logger.info("Reusing existing validated final assembly output.")
                return AssemblyResult(
                    status=AssemblyStatus.complete.value,
                    task_id=edit_manifest.task_id,
                    final_dir=str(final_dir.resolve()),
                    final_video_file=str(final_mp4.resolve()),
                    assembly_manifest_file=str(assembly_manifest_file.resolve()),
                    qc_report_file=str(qc_report_file.resolve()),
                    error=None,
                )
        except Exception as exc:
            logger.warning(f"Could not reuse existing assembly manifest: {exc}")

    # Build AssemblyScenes list
    assembly_scenes: list[AssemblyScene] = []
    for sc in edit_manifest.scenes:
        assert sc.exported_file is not None
        assembly_scenes.append(
            AssemblyScene(
                scene_id=sc.scene_id,
                order=sc.order,
                video_file=sc.exported_file,
                sha256=sc.sha256 or compute_file_sha256(export_dir / sc.exported_file),
                duration_frames=sc.duration_frames,
                duration_seconds=sc.duration_frames / float(config.fps),
                start_frame=sc.start_frame,
                end_frame=sc.end_frame,
            )
        )

    # Perform Assembly
    render_log_lines: list[str] = [
        f"[{_utc_now()}] Starting final assembly for {edit_manifest.project_slug}",
        f"Scenes to concatenate: {len(assembly_scenes)}",
    ]

    opened_clips: list[Any] = []
    video_concat: Any = None
    final_clip: Any = None
    narration_audio: Any = None
    bgm_audio: Any = None
    mixed_audio: Any = None

    nonce = hashlib.md5(str(os.urandom(8)).encode()).hexdigest()[:6]
    tmp_final = final_dir / f"final.mp4.tmp.{os.getpid()}.{nonce}.mp4"

    try:
        # 1. Load and concatenate scene video clips in order
        scene_clips = []
        for asc in assembly_scenes:
            sc_path = export_dir / asc.video_file
            clip = VideoFileClip(str(sc_path))
            opened_clips.append(clip)
            # Verify dimensions
            if [clip.w, clip.h] != config.resolution:
                render_log_lines.append(
                    f"Warning: resizing scene {asc.scene_id} from [{clip.w}, {clip.h}] to {config.resolution}"
                )
                if hasattr(clip, "resized"):
                    clip = clip.resized(width=config.resolution[0], height=config.resolution[1])
                elif hasattr(clip, "resize"):
                    clip = clip.resize(newsize=(config.resolution[0], config.resolution[1]))
                opened_clips.append(clip)
            scene_clips.append(clip)

        if not scene_clips:
            raise ProjectRunError("No video clips available for concatenation")

        video_concat = concatenate_videoclips(scene_clips, method="compose")
        opened_clips.append(video_concat)
        total_video_duration = float(video_concat.duration or edit_manifest.duration_seconds)
        render_log_lines.append(f"Concatenated video duration: {total_video_duration:.2f}s")

        # 2. Process Audio Tracks (Narration Backbone + Optional BGM)
        audio_tracks: list[Any] = []

        if edit_manifest.narration_file:
            narr_path = export_dir / edit_manifest.narration_file
            if narr_path.exists():
                narration_audio = AudioFileClip(str(narr_path))
                opened_clips.append(narration_audio)
                narr_dur = float(narration_audio.duration or 0.0)
                if narr_dur > total_video_duration:
                    if hasattr(narration_audio, "subclipped"):
                        narration_audio = narration_audio.subclipped(0, total_video_duration)
                    elif hasattr(narration_audio, "subclip"):
                        narration_audio = narration_audio.subclip(0, total_video_duration)
                    opened_clips.append(narration_audio)
                if config.audio_mix.narration_volume != 1.0:
                    if hasattr(narration_audio, "with_volume_scaled"):
                        narration_audio = narration_audio.with_volume_scaled(config.audio_mix.narration_volume)
                    elif hasattr(narration_audio, "volumex"):
                        narration_audio = narration_audio.volumex(config.audio_mix.narration_volume)
                    opened_clips.append(narration_audio)
                audio_tracks.append(narration_audio)
                render_log_lines.append(f"Loaded narration track: {narr_path.name}")

        # Optional BGM
        if config.audio_mix.bgm_file:
            bgm_path = Path(config.audio_mix.bgm_file).resolve()
            if bgm_path.exists() and bgm_path.is_file():
                bgm_audio = AudioFileClip(str(bgm_path))
                opened_clips.append(bgm_audio)
                bgm_dur = float(bgm_audio.duration or 0.0)

                # Loop if needed
                if bgm_dur > 0 and bgm_dur < total_video_duration:
                    if hasattr(afx, "audio_loop"):
                        bgm_audio = afx.audio_loop(bgm_audio, duration=total_video_duration)
                    elif hasattr(bgm_audio, "loop"):
                        bgm_audio = bgm_audio.loop(duration=total_video_duration)
                    opened_clips.append(bgm_audio)

                # Subclip to video duration
                if hasattr(bgm_audio, "subclipped"):
                    bgm_audio = bgm_audio.subclipped(0, total_video_duration)
                elif hasattr(bgm_audio, "subclip"):
                    bgm_audio = bgm_audio.subclip(0, total_video_duration)
                opened_clips.append(bgm_audio)

                # Volume and ducking
                effective_vol = config.audio_mix.bgm_volume
                if narration_audio is not None:
                    effective_vol *= config.audio_mix.ducking_factor

                if hasattr(bgm_audio, "with_volume_scaled"):
                    bgm_audio = bgm_audio.with_volume_scaled(effective_vol)
                elif hasattr(bgm_audio, "volumex"):
                    bgm_audio = bgm_audio.volumex(effective_vol)
                opened_clips.append(bgm_audio)

                audio_tracks.append(bgm_audio)
                render_log_lines.append(f"Loaded BGM track: {bgm_path.name} with volume {effective_vol}")

        # Combine audio
        if audio_tracks:
            if len(audio_tracks) == 1:
                mixed_audio = audio_tracks[0]
            else:
                mixed_audio = CompositeAudioClip(audio_tracks)
                opened_clips.append(mixed_audio)

            if hasattr(video_concat, "with_audio"):
                final_clip = video_concat.with_audio(mixed_audio)
            elif hasattr(video_concat, "set_audio"):
                final_clip = video_concat.set_audio(mixed_audio)
            else:
                final_clip = video_concat
            opened_clips.append(final_clip)
        else:
            final_clip = video_concat

        # 3. Render final video to temporary file
        render_log_lines.append(f"Rendering final MP4 to temp file: {tmp_final.name}")
        ffmpeg_params = ["-crf", str(config.crf)]

        final_clip.write_videofile(
            str(tmp_final),
            fps=config.fps,
            codec=config.video_codec,
            audio_codec=config.audio_codec,
            audio_bitrate=config.audio_bitrate,
            preset=config.preset,
            ffmpeg_params=ffmpeg_params,
            threads=2,
            logger=None,
        )

        render_log_lines.append("Render finished. Running Final QC Quality Gate...")

        # 4. Perform Final QC check
        qc_report = validate_and_inspect_final_video(
            video_path=tmp_final,
            expected_fps=config.fps,
            expected_resolution=config.resolution,
            expected_duration=edit_manifest.duration_seconds,
            require_audio=bool(edit_manifest.narration_file),
            duration_tolerance=0.6,
        )

        if not qc_report.is_valid:
            render_log_lines.append(f"QC GATE FAILED: {qc_report.errors}")
            qc_report_file.write_text(
                json.dumps(qc_report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            render_log_file.write_text("\n".join(render_log_lines) + "\n", encoding="utf-8")
            return AssemblyResult(
                status=AssemblyStatus.failed.value,
                task_id=edit_manifest.task_id,
                final_dir=str(final_dir.resolve()),
                final_video_file=None,
                assembly_manifest_file=None,
                qc_report_file=str(qc_report_file.resolve()),
                error=f"Final QC verification failed: {'; '.join(qc_report.errors)}",
            )

        # 5. Atomic placement to canonical final.mp4
        if final_mp4.exists():
            final_mp4.unlink()
        tmp_final.replace(final_mp4)

        final_video_sha = compute_file_sha256(final_mp4)
        qc_report.final_video_file = str(final_mp4.resolve())
        qc_report.sha256 = final_video_sha

        # 6. Build and write assembly_manifest.json
        now_iso = _utc_now()
        assembly_manifest = AssemblyManifest(
            schema_version="1.0",
            project_title=edit_manifest.project_title,
            project_slug=edit_manifest.project_slug,
            task_id=edit_manifest.task_id,
            source_project_fingerprint=edit_manifest.source_project_fingerprint,
            edit_manifest_sha256=edit_manifest_sha,
            assembly_fingerprint=assembly_fp,
            status=AssemblyStatus.complete,
            final_video_file=str(final_mp4.resolve()),
            final_video_sha256=final_video_sha,
            duration_seconds=qc_report.duration_seconds,
            duration_frames=round(qc_report.duration_seconds * config.fps),
            fps=config.fps,
            resolution=config.resolution,
            scenes=assembly_scenes,
            audio_mix=config.audio_mix,
            subtitles=config.subtitles,
            qc_report=qc_report,
            created_at=now_iso,
            updated_at=now_iso,
            outputs={
                "final_dir": str(final_dir.resolve()),
                "final_mp4": str(final_mp4.resolve()),
                "assembly_manifest_file": str(assembly_manifest_file.resolve()),
                "qc_report_file": str(qc_report_file.resolve()),
                "render_log_file": str(render_log_file.resolve()),
            },
        )

        assembly_manifest_file.write_text(
            json.dumps(assembly_manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        qc_report_file.write_text(
            json.dumps(qc_report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        render_log_lines.append(f"Final assembly complete and QC validated: {final_mp4.name} (SHA: {final_video_sha[:12]})")
        render_log_file.write_text("\n".join(render_log_lines) + "\n", encoding="utf-8")

        return AssemblyResult(
            status=AssemblyStatus.complete.value,
            task_id=edit_manifest.task_id,
            final_dir=str(final_dir.resolve()),
            final_video_file=str(final_mp4.resolve()),
            assembly_manifest_file=str(assembly_manifest_file.resolve()),
            qc_report_file=str(qc_report_file.resolve()),
            error=None,
        )

    finally:
        # Cleanup clips safely
        for c in opened_clips:
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass
        if tmp_final.exists():
            try:
                tmp_final.unlink()
            except Exception:
                pass
