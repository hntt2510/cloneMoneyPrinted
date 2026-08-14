from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from app.models.project import (
    AssetJob,
    BrollManifest,
    JobStatus,
    ProjectManifest,
    ProjectSpec,
    ProjectStatus,
    SelectedBrollAsset,
    VisualType,
)
from app.services.broll import BrollAcquisitionError, BrollSelectionContext, acquire_broll_scene
from app.services.project_spec import load_project_spec, preflight_project
from app.services.project_timeline_runner import run_project_plan
from app.utils import utils


def run_broll_acquisition(
    project_input: str | Path | ProjectSpec,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Execute autonomous B-roll acquisition pipeline for all BROLL VisualCues.

    Workflow:
    1. Resolve project spec and ensure task directory exists.
    2. Ensure planning stage (G03 + G04) is complete; run if needed.
    3. Filter VisualCues for BROLL type only (DATA, DOCUMENT, TEXT untouched).
    4. For each BROLL cue: search, score, download winner only, trim & normalize scene clip.
    5. Maintain truthful AssetJob lifecycle and status_history.
    6. Generate broll_manifest.json, project.assets.json, and update project_manifest.json.
    """
    if isinstance(project_input, (str, Path)):
        source_path = Path(project_input).expanduser().resolve()
        project = load_project_spec(source_path)
        preflight_project(project, source_path.parent)
    else:
        source_path = None
        project = project_input

    run_task_id = task_id or utils.get_uuid()
    task_directory = Path(utils.task_dir(run_task_id)).resolve()
    task_directory.mkdir(parents=True, exist_ok=True)

    planned_project_file = task_directory / "project.planned.json"
    visual_plan_file = task_directory / "visual_plan.json"

    # If planned project does not exist on disk, execute planning pipeline first
    if not planned_project_file.exists() or not visual_plan_file.exists():
        if source_path is None:
            source_path = task_directory / "project.json"
            source_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        logger.info(f"Planning artifacts not found for task {run_task_id}; running planning stage first")
        run_project_plan(str(source_path), task_id=run_task_id)

    # Load planned project
    planned_project = load_project_spec(planned_project_file)
    context = BrollSelectionContext()

    ready_assets: list[SelectedBrollAsset] = []
    failed_scenes: list[dict[str, Any]] = []
    broll_asset_jobs: list[AssetJob] = []

    # Process BROLL cues only - G05 creates AssetJobs ONLY for VisualType.broll
    broll_cues = [cue for cue in planned_project.visual_cues if cue.visual_type == VisualType.broll]
    logger.info(
        f"Starting autonomous B-roll acquisition for task {run_task_id} ({len(broll_cues)} B-roll scenes)"
    )

    for cue in broll_cues:
        job = AssetJob(
            id=f"A{cue.order:03d}",
            scene_id=cue.id,
            kind="broll",
            status=JobStatus.planned,
            attempts=0,
            metadata={"status_history": ["planned"]},
        )

        def make_progress_handler(target_job: AssetJob):
            def handle_progress(event: dict[str, Any]) -> None:
                new_status = event.get("status")
                if new_status:
                    status_str = new_status.value if hasattr(new_status, "value") else str(new_status)
                    target_job.status = new_status
                    history = target_job.metadata.setdefault("status_history", [])
                    if not history or history[-1] != status_str:
                        history.append(status_str)
                if "attempt" in event:
                    target_job.attempts = event["attempt"]
                if "provider" in event:
                    target_job.provider = event["provider"]
                if "query" in event:
                    target_job.query = event["query"]
                if "error" in event:
                    target_job.error = event["error"]
            return handle_progress

        progress_callback = make_progress_handler(job)

        try:
            selected_asset = acquire_broll_scene(
                cue=cue,
                project=planned_project,
                task_directory=task_directory,
                context=context,
                on_progress=progress_callback,
            )
            ready_assets.append(selected_asset)
            job.status = JobStatus.ready
            job.provider = selected_asset.provider
            job.query = selected_asset.query_used
            job.source = selected_asset.source_file
            job.output = selected_asset.rendered_file
            job.metadata.update(
                {
                    "score": selected_asset.score,
                    "score_breakdown": selected_asset.score_breakdown,
                    "source_duration": selected_asset.source_duration,
                    "trim_start": selected_asset.trim_start,
                    "trim_end": selected_asset.trim_end,
                    "scene_duration": selected_asset.scene_duration,
                    "candidate_metadata": selected_asset.metadata.get("candidate_metadata", {}),
                }
            )
        except Exception as exc:
            logger.error(f"B-roll acquisition failed for scene {cue.id}: {exc}")
            diag = exc.diagnostics if isinstance(exc, BrollAcquisitionError) else {}
            attempt_count = diag.get("attempt_count", job.attempts or 1)
            queries_searched = diag.get("queries_searched", [])
            providers_searched = diag.get("providers_searched", [])
            candidate_ids_attempted = diag.get("candidate_ids_attempted", [])
            errors = diag.get("errors", [str(exc)])

            failed_scenes.append(
                {
                    "scene_id": cue.id,
                    "order": cue.order,
                    "attempt_count": attempt_count,
                    "queries_searched": queries_searched,
                    "providers_searched": providers_searched,
                    "candidate_ids_attempted": candidate_ids_attempted,
                    "errors": errors,
                    "error": str(exc),
                }
            )
            job.status = JobStatus.failed
            job.attempts = attempt_count
            job.error = str(exc)
            job.metadata.update(diag)

        broll_asset_jobs.append(job)

    # In G05, project.assets.json contains ONLY BROLL asset jobs
    planned_project.asset_jobs = broll_asset_jobs

    # Save project.assets.json
    assets_project_file = task_directory / "project.assets.json"
    assets_project_file.write_text(
        json.dumps(planned_project.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Save broll_manifest.json
    manifest_status = ProjectStatus.complete if not failed_scenes else ProjectStatus.failed
    broll_manifest = BrollManifest(
        schema_version="1.0",
        project_title=planned_project.project.title,
        task_id=run_task_id,
        status=manifest_status,
        assets=ready_assets,
        failed_scenes=failed_scenes,
        error="One or more B-roll scenes failed acquisition" if failed_scenes else None,
    )
    broll_manifest_file = task_directory / "broll_manifest.json"
    broll_manifest_file.write_text(
        json.dumps(broll_manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Update project_manifest.json consistently with pipeline outcome
    project_manifest_file = task_directory / "project_manifest.json"
    if project_manifest_file.exists():
        try:
            p_manifest = ProjectManifest.model_validate_json(
                project_manifest_file.read_text(encoding="utf-8")
            )
            p_manifest.outputs["broll_manifest_file"] = str(broll_manifest_file.resolve())
            p_manifest.outputs["assets_project_file"] = str(assets_project_file.resolve())
            if failed_scenes:
                p_manifest.status = ProjectStatus.failed
                p_manifest.error = "One or more B-roll scenes failed acquisition"
            else:
                p_manifest.status = ProjectStatus.complete
                p_manifest.error = None

            project_manifest_file.write_text(
                json.dumps(p_manifest.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Could not update project_manifest.json: {exc}")

    logger.success(
        f"Completed B-roll acquisition for task {run_task_id}: {len(ready_assets)} ready, {len(failed_scenes)} failed"
    )

    return {
        "task_id": run_task_id,
        "broll_manifest_file": str(broll_manifest_file.resolve()),
        "assets_project_file": str(assets_project_file.resolve()),
        "ready_count": len(ready_assets),
        "failed_count": len(failed_scenes),
        "status": "complete" if not failed_scenes else "failed",
    }
