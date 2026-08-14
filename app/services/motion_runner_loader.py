from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.models.project import ProjectSpec
from app.services.project_spec import load_project_spec, preflight_project
from app.services.project_timeline_runner import run_project_plan
from app.utils import utils


def resolve_project_workspace(
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

    # Determine task_id
    run_task_id = task_id
    if not run_task_id and source_path is not None:
        # Check if source_path is inside a task dir
        parent_name = source_path.parent.name
        if source_path.parent.parent.name == "tasks" and parent_name:
            run_task_id = parent_name

    if not run_task_id:
        run_task_id = utils.get_uuid()

    task_directory = Path(utils.task_dir(run_task_id)).resolve()
    task_directory.mkdir(parents=True, exist_ok=True)

    assets_project_file = task_directory / "project.assets.json"
    planned_project_file = task_directory / "project.planned.json"
    visual_plan_file = task_directory / "visual_plan.json"

    # Prefer project.assets.json (preserves B-roll stage results)
    if assets_project_file.exists():
        logger.info(f"Loading project from assets stage: {assets_project_file.name}")
        project = load_project_spec(assets_project_file)
        return project, task_directory, run_task_id

    # Fallback to project.planned.json
    if planned_project_file.exists() and visual_plan_file.exists():
        logger.info(f"Loading project from planned stage: {planned_project_file.name}")
        project = load_project_spec(planned_project_file)
        return project, task_directory, run_task_id

    # If neither exists and input has visual_cues already, use as is
    if project.visual_cues:
        return project, task_directory, run_task_id

    # Run planning stage if needed
    if source_path is None:
        source_path = task_directory / "project.json"
        source_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")

    logger.info(f"Planning artifacts not found for task {run_task_id}; running planning stage first")
    run_project_plan(str(source_path), task_id=run_task_id)

    if planned_project_file.exists():
        project = load_project_spec(planned_project_file)

    return project, task_directory, run_task_id
