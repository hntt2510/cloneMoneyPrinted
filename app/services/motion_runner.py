from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from app.models.motion import (
    MotionGroupSpec,
    MotionManifest,
    MotionSceneSpec,
    RenderedMotionAsset,
)
from app.models.project import (
    JobStatus,
    ProjectManifest,
    ProjectSpec,
    ProjectStatus,
    RenderJob,
    VisualCue,
    VisualType,
)
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.motion_runner_loader import resolve_project_workspace
from app.services.remotion import render_group_motion, render_scene_motion


def _transition_job(
    job: RenderJob,
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


def run_motion_render(
    project_input: str | Path | ProjectSpec,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Execute G06 deterministic Remotion motion rendering for DATA and TEXT VisualCues.

    BROLL and DOCUMENT cues are strictly ignored.
    """
    project, task_dir, current_task_id = resolve_project_workspace(project_input, task_id)
    motion_dir = task_dir / "motion"
    motion_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = motion_dir / "motion_manifest.json"
    project_motion_path = task_dir / "project.motion.json"
    project_manifest_path = task_dir / "project_manifest.json"

    # Filter DATA and TEXT visual cues
    motion_cues = [
        cue
        for cue in sorted(project.visual_cues, key=lambda c: c.order)
        if cue.visual_type in (VisualType.data, VisualType.text)
    ]

    # Handle zero motion cues scenario gracefully
    if not motion_cues:
        logger.info(f"Task {current_task_id} contains no DATA or TEXT visual cues; completing motion stage with zero renders.")
        empty_manifest = MotionManifest(
            project_title=project.project.title,
            task_id=current_task_id,
            status=ProjectStatus.complete,
            assets=[],
            failed_scenes=[],
        )
        manifest_path.write_text(json.dumps(empty_manifest.model_dump(mode="json"), indent=2), encoding="utf-8")
        project_motion_path.write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")

        if project_manifest_path.exists():
            try:
                p_man = ProjectManifest.model_validate_json(project_manifest_path.read_text(encoding="utf-8"))
                p_man.outputs["motion_manifest_file"] = str(manifest_path.resolve())
                p_man.outputs["motion_project_file"] = str(project_motion_path.resolve())
                p_man.updated_at = datetime.now(timezone.utc)
                if p_man.status != ProjectStatus.failed:
                    p_man.status = ProjectStatus.complete
                project_manifest_path.write_text(json.dumps(p_man.model_dump(mode="json"), indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning(f"Could not update project_manifest.json: {exc}")

        return {
            "status": "complete",
            "task_id": current_task_id,
            "motion_count": 0,
            "manifest": str(manifest_path.resolve()),
            "project_motion": str(project_motion_path.resolve()),
        }

    # Initialize RenderJobs strictly for DATA and TEXT
    render_jobs: dict[str, RenderJob] = {}
    for cue in motion_cues:
        job_id = f"R{cue.order:03d}"
        job = RenderJob(
            id=job_id,
            scene_id=cue.id,
            kind=cue.visual_type.value,
            status=JobStatus.planned,
            attempts=0,
            metadata={"status_history": ["planned"]},
        )
        render_jobs[cue.id] = job

    # Normalize specs
    scene_specs = [normalize_motion_spec(cue, project) for cue in motion_cues]
    grouped_items = form_motion_groups(scene_specs)

    rendered_assets: list[RenderedMotionAsset] = []
    failed_scenes: list[dict[str, Any]] = []

    for item in grouped_items:
        if isinstance(item, MotionGroupSpec):
            # Lifecycle transitions for all scenes in group
            for s in item.scenes:
                job = render_jobs[s.scene_id]
                _transition_job(job, JobStatus.queued)

            def _on_group_progress(data: dict[str, Any]) -> None:
                st = data.get("status")
                att = data.get("attempt", 1)
                if st == JobStatus.processing:
                    for s in item.scenes:
                        j = render_jobs[s.scene_id]
                        _transition_job(j, JobStatus.processing)
                        j.attempts = att
                elif st == JobStatus.retrying:
                    for s in item.scenes:
                        j = render_jobs[s.scene_id]
                        _transition_job(j, JobStatus.retrying)
                        _transition_job(j, JobStatus.processing)
                        j.attempts = att

            try:
                assets = render_group_motion(item, task_dir, on_progress=_on_group_progress)
                rendered_assets.extend(assets)
                for asset in assets:
                    job = render_jobs[asset.scene_id]
                    job.attempts = asset.metadata.get("attempts", job.attempts)
                    _transition_job(
                        job,
                        JobStatus.ready,
                        output=asset.output_file,
                        duration=round(asset.duration_frames / float(asset.fps), 4),
                    )
            except Exception as exc:
                logger.error(f"Group motion render failed for {item.group_id}: {exc}")
                for s in item.scenes:
                    job = render_jobs[s.scene_id]
                    _transition_job(job, JobStatus.failed, error=str(exc))
                    failed_scenes.append({"scene_id": s.scene_id, "error": str(exc), "group_id": item.group_id})

        else:
            # Single MotionSceneSpec
            scene_spec = item
            job = render_jobs[scene_spec.scene_id]
            _transition_job(job, JobStatus.queued)

            def _on_scene_progress(data: dict[str, Any]) -> None:
                st = data.get("status")
                att = data.get("attempt", 1)
                if st == JobStatus.processing:
                    _transition_job(job, JobStatus.processing)
                    job.attempts = att
                elif st == JobStatus.retrying:
                    _transition_job(job, JobStatus.retrying)
                    _transition_job(job, JobStatus.processing)
                    job.attempts = att

            try:
                asset = render_scene_motion(scene_spec, task_dir, on_progress=_on_scene_progress)
                rendered_assets.append(asset)
                job.attempts = asset.metadata.get("attempts", job.attempts)
                _transition_job(
                    job,
                    JobStatus.ready,
                    output=asset.output_file,
                    duration=round(asset.duration_frames / float(asset.fps), 4),
                )
            except Exception as exc:
                logger.error(f"Motion render failed for scene {scene_spec.scene_id}: {exc}")
                _transition_job(job, JobStatus.failed, error=str(exc))
                failed_scenes.append({"scene_id": scene_spec.scene_id, "error": str(exc)})

    # Update project render_jobs list (preserving existing BROLL asset_jobs)
    project.render_jobs = list(render_jobs.values())

    stage_status = ProjectStatus.failed if failed_scenes else ProjectStatus.complete
    motion_manifest = MotionManifest(
        project_title=project.project.title,
        task_id=current_task_id,
        status=stage_status,
        assets=rendered_assets,
        failed_scenes=failed_scenes,
        error=f"{len(failed_scenes)} motion scenes failed to render" if failed_scenes else None,
    )

    manifest_path.write_text(json.dumps(motion_manifest.model_dump(mode="json"), indent=2), encoding="utf-8")
    project_motion_path.write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")

    # Synchronize project_manifest.json (preserving prior stage failures)
    if project_manifest_path.exists():
        try:
            p_man = ProjectManifest.model_validate_json(project_manifest_path.read_text(encoding="utf-8"))
            p_man.outputs["motion_manifest_file"] = str(manifest_path.resolve())
            p_man.outputs["motion_project_file"] = str(project_motion_path.resolve())
            p_man.updated_at = datetime.now(timezone.utc)
            if failed_scenes:
                p_man.status = ProjectStatus.failed
                motion_err = f"Motion rendering failed for {len(failed_scenes)} scenes"
                if p_man.error:
                    if motion_err not in p_man.error:
                        p_man.error = f"{p_man.error}; {motion_err}"
                else:
                    p_man.error = motion_err
                stage_errors = p_man.outputs.setdefault("stage_errors", {})
                stage_errors["motion"] = motion_err
            elif p_man.status != ProjectStatus.failed:
                p_man.status = ProjectStatus.complete
            project_manifest_path.write_text(json.dumps(p_man.model_dump(mode="json"), indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Could not update project_manifest.json: {exc}")

    return {
        "status": stage_status.value,
        "task_id": current_task_id,
        "motion_count": len(rendered_assets),
        "failed_count": len(failed_scenes),
        "manifest": str(manifest_path.resolve()),
        "project_motion": str(project_motion_path.resolve()),
    }
