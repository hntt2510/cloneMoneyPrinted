from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.project import ProjectManifest, ProjectStatus, NarrationMode
from app.services import task as tm
from app.services.project_runner import ProjectRunError, _save_manifest, _utc_now
from app.services.project_spec import (
    load_project_spec,
    preflight_project,
    project_to_video_params,
    resolve_project_path,
    save_project_spec,
)
from app.services.timeline import (
    acquire_timing_file,
    build_timeline_cues,
    build_timeline_plan,
    is_reliable_tts_submaker,
    save_timeline_plan,
)
from app.services.visual_planner import plan_visuals, save_visual_plan
from app.services import voice
from app.utils import utils


def _save_json(value: Any, destination: Path) -> Path:
    destination.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def run_timeline_plan(
    project_path: str,
    *,
    task_id: str | None = None,
    _include_visuals: bool = False,
) -> dict[str, Any]:
    source = Path(project_path).expanduser().resolve()
    project = load_project_spec(source)
    preflight_project(project, source.parent)
    run_task_id = task_id or utils.get_uuid()
    task_directory = Path(utils.task_dir(run_task_id))
    save_project_spec(project, task_directory / "project.normalized.json")

    now = _utc_now()
    manifest = ProjectManifest(
        schema_version=project.schema_version,
        project_title=project.project.title,
        project_file=str(source),
        task_id=run_task_id,
        status=ProjectStatus.processing,
        fps=project.project.fps,
        aspect_ratio=project.project.aspect_ratio,
        created_at=now,
        updated_at=now,
    )
    _save_manifest(manifest, task_directory)

    try:
        params = project_to_video_params(project, source.parent)
        
        if project.narration.mode == NarrationMode.file:
            raw_file = project.narration.file
            if not raw_file:
                raise ProjectRunError("External narration requires a WAV/MP3 file.")
            audio_file = str(resolve_project_path(source.parent, raw_file))
            if not Path(audio_file).exists():
                raise ProjectRunError(f"External narration audio file not found: {audio_file}")
            duration = voice.get_audio_duration(audio_file) or 0.0
            if duration <= 0:
                raise ProjectRunError("External narration audio has zero or invalid duration.")
            sub_maker = None
            script = project.script.script
            if not script.strip() and project.narration.timing_file:
                srt_path = resolve_project_path(source.parent, project.narration.timing_file)
                from app.services.timeline import parse_srt_file
                derived_cues = parse_srt_file(srt_path)
                script = " ".join(c.text for c in derived_cues)
        else:
            script = tm.generate_script(run_task_id, params)
            if not script or "Error: " in script:
                raise ProjectRunError("script generation failed")
            audio_file, reported_duration, sub_maker = tm.generate_audio(
                run_task_id, params, script
            )
            if not audio_file:
                raise ProjectRunError("narration audio generation failed")
            duration = voice.get_audio_duration(audio_file) or float(reported_duration or 0)
            if duration <= 0:
                raise ProjectRunError("narration audio duration could not be determined")

        source_timing = (
            resolve_project_path(source.parent, project.narration.timing_file)
            if project.narration.timing_file
            else None
        )
        timing_file, srt_cues, timing_source = acquire_timing_file(
            source_timing_file=source_timing,
            task_directory=task_directory,
            audio_file=audio_file,
            script=script,
            duration=duration,
            sub_maker=sub_maker,
            reliable_tts_timing=is_reliable_tts_submaker(
                sub_maker, project.narration.voice_name
            ),
        )
        timeline_cues = build_timeline_cues(srt_cues, script)
        timeline_plan = build_timeline_plan(
            project_title=project.project.title,
            audio_file=str(Path(audio_file).resolve()),
            timing_file=str(Path(timing_file).resolve()),
            duration=duration,
            cues=timeline_cues,
            timing_source=timing_source,
        )
        timeline_path = save_timeline_plan(
            timeline_plan, task_directory / "timeline.json"
        )
        planned_project = project.model_copy(
            update={
                "script": project.script.model_copy(update={"script": script}),
                "timeline_cues": timeline_cues,
            }
        )
        planned_project = type(project).model_validate(
            planned_project.model_dump(mode="json")
        )
        visual_path = None
        if _include_visuals:
            visual_cues = plan_visuals(
                planned_project,
                timeline_cues,
                total_duration_seconds=duration,
            )
            visual_path = save_visual_plan(
                project.project.title, visual_cues, task_directory / "visual_plan.json"
            )
            planned_project = type(project).model_validate(
                planned_project.model_copy(update={"visual_cues": visual_cues}).model_dump(
                    mode="json"
                )
            )
        planned_path = save_project_spec(
            planned_project, task_directory / "project.planned.json"
        )

        manifest.status = ProjectStatus.complete
        manifest.updated_at = _utc_now()
        manifest.outputs = {
            "audio_file": str(Path(audio_file).resolve()),
            "timing_file": str(Path(timing_file).resolve()),
            "timing_source": timing_source,
            "timeline_file": str(timeline_path.resolve()),
            "planned_project_file": str(planned_path.resolve()),
        }
        if visual_path:
            manifest.outputs["visual_plan_file"] = str(visual_path.resolve())
        _save_manifest(manifest, task_directory)
        result = {
            "task_id": run_task_id,
            "audio_file": manifest.outputs["audio_file"],
            "timing_file": manifest.outputs["timing_file"],
            "timeline_file": manifest.outputs["timeline_file"],
            "planned_project_file": manifest.outputs["planned_project_file"],
            "manifest": manifest.model_dump(mode="json"),
        }
        if visual_path:
            result["visual_plan_file"] = manifest.outputs["visual_plan_file"]
        return result
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
        manifest.status = ProjectStatus.failed
        manifest.error = error
        manifest.updated_at = _utc_now()
        _save_manifest(manifest, task_directory)
        if isinstance(exc, ProjectRunError):
            raise
        raise ProjectRunError(f"Timeline planning failed: {error}") from exc


def run_project_plan(project_path: str, *, task_id: str | None = None) -> dict[str, Any]:
    return run_timeline_plan(project_path, task_id=task_id, _include_visuals=True)
