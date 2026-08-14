from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.project import ProjectManifest, ProjectStatus
from app.services import task as tm
from app.services.project_spec import (
    json_safe,
    load_project_spec,
    preflight_project,
    project_to_video_params,
    save_project_spec,
)
from app.utils import utils


class ProjectRunError(RuntimeError):
    """The project could not be executed by the existing task pipeline."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _save_manifest(manifest: ProjectManifest, task_directory: Path) -> Path:
    destination = task_directory / "project_manifest.json"
    destination.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination


def run_project(
    project_path: str,
    *,
    task_id: str | None = None,
    stop_at: str = "video",
) -> dict[str, Any]:
    source = Path(project_path).expanduser().resolve()
    project = load_project_spec(source)
    project_dir = source.parent
    preflight_project(project, project_dir)

    run_task_id = task_id or utils.get_uuid()
    task_directory = Path(utils.task_dir(run_task_id))
    normalized_path = task_directory / "project.normalized.json"
    save_project_spec(project, normalized_path)

    created_at = _utc_now()
    manifest = ProjectManifest(
        schema_version=project.schema_version,
        project_title=project.project.title,
        project_file=str(source),
        task_id=run_task_id,
        status=ProjectStatus.processing,
        fps=project.project.fps,
        aspect_ratio=project.project.aspect_ratio,
        created_at=created_at,
        updated_at=created_at,
    )
    _save_manifest(manifest, task_directory)

    params = project_to_video_params(project, project_dir)
    try:
        result = tm.start(task_id=run_task_id, params=params, stop_at=stop_at)
        if not result:
            raise ProjectRunError("project pipeline returned no result")
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
        manifest.status = ProjectStatus.failed
        manifest.error = error
        manifest.updated_at = _utc_now()
        _save_manifest(manifest, task_directory)
        if isinstance(exc, ProjectRunError):
            raise
        raise ProjectRunError(f"Project pipeline failed: {error}") from exc

    manifest.status = ProjectStatus.complete
    manifest.outputs = json_safe(result)
    manifest.updated_at = _utc_now()
    _save_manifest(manifest, task_directory)
    return {
        "task_id": run_task_id,
        "result": json_safe(result),
        "manifest": manifest.model_dump(mode="json"),
    }


run_project_file = run_project
