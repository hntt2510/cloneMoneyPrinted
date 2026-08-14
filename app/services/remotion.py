from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.models.motion import (
    MotionGroupSpec,
    MotionSceneSpec,
    RenderedMotionAsset,
)
from app.models.project import JobStatus
from app.utils import utils


class MotionRenderValidationError(ValueError):
    """Raised when rendered motion output fails resolution, fps, duration, or audio checks."""


def validate_rendered_motion_clip(
    rendered_path: Path | str,
    expected_duration_frames: int,
    expected_width: int,
    expected_height: int,
    expected_fps: int = 30,
) -> float:
    """Strictly validate rendered motion clip against target resolution, fps, duration, and audio absence."""
    dest = Path(rendered_path).resolve()
    if not dest.exists() or dest.stat().st_size == 0:
        raise MotionRenderValidationError(f"Rendered file is missing or empty: {dest}")

    clip = None
    try:
        clip = VideoFileClip(str(dest))
        actual_duration = float(clip.duration or 0.0)
        actual_w, actual_h = clip.size
        actual_fps = float(clip.fps or 0.0)
        has_audio = clip.audio is not None

        if actual_duration <= 0 or actual_fps <= 0:
            raise MotionRenderValidationError(
                f"Decoded clip has invalid duration ({actual_duration}) or fps ({actual_fps})"
            )

        if actual_w != expected_width or actual_h != expected_height:
            raise MotionRenderValidationError(
                f"Resolution mismatch: expected {expected_width}x{expected_height}, got {actual_w}x{actual_h}"
            )

        if abs(actual_fps - expected_fps) > 2.0:
            raise MotionRenderValidationError(
                f"FPS mismatch: expected ~{expected_fps}, got {actual_fps:.2f}"
            )

        expected_duration = expected_duration_frames / float(expected_fps)
        tolerance = max(1.0 / expected_fps, 0.05)
        duration_diff = abs(actual_duration - expected_duration)
        if duration_diff > tolerance:
            raise MotionRenderValidationError(
                f"Duration mismatch: expected {expected_duration:.3f}s ({expected_duration_frames} frames), "
                f"got {actual_duration:.3f}s (diff {duration_diff:.3f}s > tolerance {tolerance:.3f}s)"
            )

        if has_audio:
            raise MotionRenderValidationError("Motion clip must not contain an audio stream")

        return actual_duration
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass


def _invoke_node_renderer(
    spec_path: Path,
    output_path: Path,
    composition_id: str,
) -> None:
    """Invoke Node Remotion rendering script via safe list arguments (shell=False)."""
    root_dir = Path(__file__).resolve().parent.parent.parent
    render_script = root_dir / "remotion" / "scripts" / "render.mjs"

    if not render_script.exists():
        raise RuntimeError(f"Remotion render script not found at {render_script}")

    cmd = [
        "node",
        str(render_script),
        "--spec",
        str(spec_path.resolve()),
        "--output",
        str(output_path.resolve()),
        "--composition",
        composition_id,
    ]

    logger.info(f"Executing Remotion render: composition={composition_id}, output={output_path.name}")

    result = subprocess.run(
        cmd,
        cwd=str(root_dir / "remotion"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        err_output = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Remotion renderer failed (exit {result.returncode}): {err_output}")


def render_scene_motion(
    scene_spec: MotionSceneSpec,
    task_directory: Path | str,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> RenderedMotionAsset:
    """Render a single ungrouped MotionSceneSpec to MP4 with 1 retry on validation failure."""
    task_dir = Path(task_directory).resolve()
    motion_dir = task_dir / "motion"
    meta_dir = motion_dir / "metadata"
    motion_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    output_filename = f"{scene_spec.scene_id}_{scene_spec.visual_type.upper()}.mp4"
    output_path = motion_dir / output_filename
    meta_path = meta_dir / f"{scene_spec.scene_id}.json"
    spec_path = meta_dir / f"{scene_spec.scene_id}_spec.json"

    # Resumability check
    if output_path.exists() and meta_path.exists():
        try:
            saved_data = json.loads(meta_path.read_text(encoding="utf-8"))
            asset = RenderedMotionAsset.model_validate(saved_data)
            if asset.scene_id == scene_spec.scene_id:
                if on_progress:
                    on_progress({"status": JobStatus.processing, "attempt": 0})
                validate_rendered_motion_clip(
                    rendered_path=output_path,
                    expected_duration_frames=scene_spec.duration_frames,
                    expected_width=scene_spec.width,
                    expected_height=scene_spec.height,
                    expected_fps=scene_spec.fps,
                )
                logger.info(f"Reusing existing validated motion asset for scene {scene_spec.scene_id}")
                if on_progress:
                    on_progress({"status": JobStatus.ready, "attempt": 0, "asset": asset})
                return asset
        except Exception as resume_exc:
            logger.warning(
                f"Existing motion artifact for {scene_spec.scene_id} is invalid ({resume_exc}); re-rendering."
            )
            if output_path.exists():
                output_path.unlink()
            if meta_path.exists():
                meta_path.unlink()

    # Prepare spec JSON for Remotion
    spec_dict = {
        "scene_id": scene_spec.scene_id,
        "visual_type": scene_spec.visual_type,
        "template": scene_spec.rendered_template,
        "props": scene_spec.props,
        "duration_in_frames": scene_spec.duration_frames,
        "fps": scene_spec.fps,
        "width": scene_spec.width,
        "height": scene_spec.height,
    }
    spec_path.write_text(json.dumps(spec_dict, indent=2), encoding="utf-8")

    attempts = 0
    max_attempts = 2
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        if on_progress:
            on_progress(
                {
                    "status": JobStatus.processing if attempt == 1 else JobStatus.retrying,
                    "attempt": attempts,
                    "template": scene_spec.rendered_template,
                }
            )

        try:
            _invoke_node_renderer(spec_path, output_path, composition_id="Scene")

            validate_rendered_motion_clip(
                rendered_path=output_path,
                expected_duration_frames=scene_spec.duration_frames,
                expected_width=scene_spec.width,
                expected_height=scene_spec.height,
                expected_fps=scene_spec.fps,
            )

            asset = RenderedMotionAsset(
                scene_id=scene_spec.scene_id,
                visual_type=scene_spec.visual_type,
                requested_template=scene_spec.requested_template,
                rendered_template=scene_spec.rendered_template,
                fallback_reason=scene_spec.fallback_reason,
                start=scene_spec.start_time,
                end=scene_spec.end_time,
                start_frame=scene_spec.start_frame,
                end_frame=scene_spec.end_frame,
                duration_frames=scene_spec.duration_frames,
                fps=scene_spec.fps,
                width=scene_spec.width,
                height=scene_spec.height,
                output_file=str(output_path.resolve()),
                visual_group_id=scene_spec.visual_group_id,
                status=JobStatus.ready,
                metadata={
                    "attempts": attempts,
                    "headline": scene_spec.props.get("headline"),
                },
            )

            meta_path.write_text(json.dumps(asset.model_dump(mode="json"), indent=2), encoding="utf-8")
            logger.success(f"Rendered motion scene {scene_spec.scene_id}: {output_path.name}")

            if on_progress:
                on_progress({"status": JobStatus.ready, "attempt": attempts, "asset": asset})

            return asset

        except Exception as exc:
            last_error = exc
            logger.warning(f"Render attempt {attempt} failed for scene {scene_spec.scene_id}: {exc}")
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass

    if on_progress:
        on_progress(
            {
                "status": JobStatus.failed,
                "attempt": attempts,
                "error": str(last_error),
            }
        )

    raise RuntimeError(
        f"Motion rendering failed for scene {scene_spec.scene_id} after {attempts} attempts: {last_error}"
    ) from last_error


def render_group_motion(
    group_spec: MotionGroupSpec,
    task_directory: Path | str,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[RenderedMotionAsset]:
    """Render a continuous visual group master MP4 and slice frame-accurate individual scene clips."""
    task_dir = Path(task_directory).resolve()
    motion_dir = task_dir / "motion"
    groups_dir = motion_dir / "groups" / group_spec.group_id
    meta_dir = motion_dir / "metadata"

    motion_dir.mkdir(parents=True, exist_ok=True)
    groups_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    master_path = groups_dir / "master.mp4"
    group_spec_path = groups_dir / "spec.json"

    # Write group spec JSON for Remotion
    group_dict = {
        "group_id": group_spec.group_id,
        "duration_in_frames": group_spec.duration_frames,
        "fps": group_spec.fps,
        "width": group_spec.width,
        "height": group_spec.height,
        "scenes": [
            {
                "scene_id": s.scene_id,
                "visual_type": s.visual_type,
                "template": s.rendered_template,
                "props": s.props,
                "start_frame": s.start_frame,
                "end_frame": s.end_frame,
                "duration_frames": s.duration_frames,
            }
            for s in group_spec.scenes
        ],
    }
    group_spec_path.write_text(json.dumps(group_dict, indent=2), encoding="utf-8")

    # Render group master if not already valid
    master_valid = False
    if master_path.exists():
        try:
            validate_rendered_motion_clip(
                rendered_path=master_path,
                expected_duration_frames=group_spec.duration_frames,
                expected_width=group_spec.width,
                expected_height=group_spec.height,
                expected_fps=group_spec.fps,
            )
            master_valid = True
            logger.info(f"Reusing existing validated group master for {group_spec.group_id}")
        except Exception:
            master_valid = False

    if not master_valid:
        if on_progress:
            on_progress({"status": JobStatus.processing, "group_id": group_spec.group_id, "attempt": 1})
        _invoke_node_renderer(group_spec_path, master_path, composition_id="Group")
        validate_rendered_motion_clip(
            rendered_path=master_path,
            expected_duration_frames=group_spec.duration_frames,
            expected_width=group_spec.width,
            expected_height=group_spec.height,
            expected_fps=group_spec.fps,
        )

    # Slice group master into individual scene clips with FFmpeg
    ffmpeg_bin = utils.get_ffmpeg_binary()
    rendered_assets: list[RenderedMotionAsset] = []
    base_start_frame = group_spec.start_frame

    for scene in group_spec.scenes:
        output_filename = f"{scene.scene_id}_{scene.visual_type.upper()}.mp4"
        scene_output_path = motion_dir / output_filename
        scene_meta_path = meta_dir / f"{scene.scene_id}.json"

        rel_start_frames = scene.start_frame - base_start_frame
        rel_start_time = rel_start_frames / float(group_spec.fps)
        scene_duration = scene.duration_frames / float(group_spec.fps)

        slice_cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{rel_start_time:.4f}",
            "-t",
            f"{scene_duration:.4f}",
            "-i",
            str(master_path.resolve()),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(scene_output_path.resolve()),
        ]

        subprocess.run(slice_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

        validate_rendered_motion_clip(
            rendered_path=scene_output_path,
            expected_duration_frames=scene.duration_frames,
            expected_width=scene.width,
            expected_height=scene.height,
            expected_fps=scene.fps,
        )

        asset = RenderedMotionAsset(
            scene_id=scene.scene_id,
            visual_type=scene.visual_type,
            requested_template=scene.requested_template,
            rendered_template=scene.rendered_template,
            fallback_reason=scene.fallback_reason,
            start=scene.start_time,
            end=scene.end_time,
            start_frame=scene.start_frame,
            end_frame=scene.end_frame,
            duration_frames=scene.duration_frames,
            fps=scene.fps,
            width=scene.width,
            height=scene.height,
            output_file=str(scene_output_path.resolve()),
            visual_group_id=group_spec.group_id,
            group_master_file=str(master_path.resolve()),
            status=JobStatus.ready,
            metadata={
                "group_id": group_spec.group_id,
                "relative_start_frame": rel_start_frames,
                "attempts": 1,
            },
        )

        scene_meta_path.write_text(json.dumps(asset.model_dump(mode="json"), indent=2), encoding="utf-8")
        rendered_assets.append(asset)

        if on_progress:
            on_progress({"status": JobStatus.ready, "scene_id": scene.scene_id, "asset": asset})

    return rendered_assets
