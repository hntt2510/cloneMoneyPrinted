from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from app.models.export import EditorPackageStatus
from app.services.assembly_runner import assemble_final_video
from app.services.export_runner import export_editor_package
from app.services.project_runner import ProjectRunError
from app.services.project_spec import load_project_spec
from app.services.scene_orchestrator import run_all_project
from app.utils import utils


@dataclass
class ProductionWorkflowResult:
    task_id: str
    execution_status: str = "not_run"  # "success", "failed", "partial", "not_run"
    execution_manifest: dict[str, Any] | None = None
    executed_project: dict[str, Any] | None = None
    export_status: str = "not_run"  # "success", "failed", "partial", "not_run"
    edit_manifest: dict[str, Any] | None = None
    export_directory: str | None = None
    assembly_status: str = "not_run"  # "success", "failed", "not_run"
    final_video: str | None = None
    qc_report: dict[str, Any] | None = None
    error: str | None = None
    failed_stage: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None and self.failed_stage is None


def run_production_workflow(
    project_path: str | Path,
    task_id: str | None = None,
    output_target: str = "final_video",  # "scene_assets", "editor_package", "final_video"
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> ProductionWorkflowResult:
    """Coordinate the full autonomous video production workflow (G08 -> G09 -> G10).

    Target levels:
    - "scene_assets": Runs G08 Scene Orchestrator only.
    - "editor_package": Runs G08 Scene Orchestrator -> G09 Editor Package Export.
    - "final_video": Runs G08 Scene Orchestrator -> G09 Editor Package Export -> G10 Final Video Assembly.
    """
    resolved_path = Path(project_path).expanduser().resolve()
    run_task_id = task_id or utils.get_uuid()
    task_dir = Path(utils.task_dir(run_task_id)).resolve()

    result = ProductionWorkflowResult(task_id=run_task_id)

    # -------------------------------------------------------------
    # Stage 1: G08 Scene Orchestrator (Asset & Scene Generation)
    # -------------------------------------------------------------
    try:
        if on_progress:
            on_progress({"stage": "orchestrator", "status": "processing", "progress_percent": 5})

        orchestrator_res = run_all_project(
            project_input=resolved_path,
            task_id=run_task_id,
            on_progress=on_progress,
        )

        # Load execution manifest and executed project if available
        exec_manifest_file = task_dir / "execution_manifest.json"
        if exec_manifest_file.exists():
            try:
                result.execution_manifest = json.loads(exec_manifest_file.read_text(encoding="utf-8-sig"))
            except Exception as e:
                logger.warning(f"Could not load execution_manifest.json: {e}")

        executed_proj_file = task_dir / "project.executed.json"
        if executed_proj_file.exists():
            try:
                result.executed_project = json.loads(executed_proj_file.read_text(encoding="utf-8-sig"))
            except Exception as e:
                logger.warning(f"Could not load project.executed.json: {e}")

        status_str = orchestrator_res.get("status", "")
        ready_scenes = orchestrator_res.get("ready_scenes", 0)
        failed_scenes = orchestrator_res.get("failed_scenes", 0)

        if status_str == "complete" and failed_scenes == 0:
            result.execution_status = "success"
        elif ready_scenes > 0:
            result.execution_status = "partial"
        else:
            result.execution_status = "failed"
            result.failed_stage = "execution"
            result.error = f"Orchestrator failed: 0 of {ready_scenes + failed_scenes} scenes ready"
            return result

    except Exception as exc:
        err = f"Scene orchestration failed: {exc}"
        logger.error(err)
        result.execution_status = "failed"
        result.failed_stage = "execution"
        result.error = err
        return result

    # Stop here if only scene assets requested
    if output_target == "scene_assets":
        return result

    # -------------------------------------------------------------
    # Stage 2: G09 Editor Package Export
    # -------------------------------------------------------------
    try:
        if on_progress:
            on_progress({"stage": "export", "status": "processing", "progress_percent": 90})

        export_res = export_editor_package(
            project_input=resolved_path,
            task_id=run_task_id,
        )

        result.export_directory = export_res.export_dir
        if export_res.edit_manifest_file and Path(export_res.edit_manifest_file).exists():
            try:
                result.edit_manifest = json.loads(
                    Path(export_res.edit_manifest_file).read_text(encoding="utf-8-sig")
                )
            except Exception as e:
                logger.warning(f"Could not load edit_manifest.json: {e}")

        if export_res.status == EditorPackageStatus.complete.value:
            result.export_status = "success"
        elif export_res.status == EditorPackageStatus.partial.value:
            result.export_status = "partial"
        else:
            result.export_status = "failed"
            result.failed_stage = "export"
            result.error = export_res.error or "Editor package export failed"
            return result

    except Exception as exc:
        err = f"Editor package export failed: {exc}"
        logger.error(err)
        result.export_status = "failed"
        result.failed_stage = "export"
        result.error = err
        return result

    # Stop here if only editor package requested
    if output_target == "editor_package":
        return result

    # -------------------------------------------------------------
    # Stage 3: G10 Final Video Assembly
    # -------------------------------------------------------------
    try:
        if on_progress:
            on_progress({"stage": "assembly", "status": "processing", "progress_percent": 95})

        assembly_res = assemble_final_video(
            project_input=resolved_path,
            task_id=run_task_id,
        )

        result.final_video = assembly_res.final_video_file
        if assembly_res.qc_report_file and Path(assembly_res.qc_report_file).exists():
            try:
                result.qc_report = json.loads(
                    Path(assembly_res.qc_report_file).read_text(encoding="utf-8-sig")
                )
            except Exception as e:
                logger.warning(f"Could not load qc_report.json: {e}")

        if result.qc_report and not result.qc_report.get("is_valid", True):
            result.assembly_status = "failed"
            result.failed_stage = "assembly"
            qc_errs = "; ".join(result.qc_report.get("errors", []))
            result.error = f"Final QC failed: {qc_errs}"
            return result

        if assembly_res.status == "complete" or (assembly_res.final_video_file and Path(assembly_res.final_video_file).exists()):
            result.assembly_status = "success"
        else:
            result.assembly_status = "failed"
            result.failed_stage = "assembly"
            result.error = assembly_res.error or "Final video file was not generated"

    except Exception as exc:
        err = f"Final video assembly failed: {exc}"
        logger.error(err)
        result.assembly_status = "failed"
        result.failed_stage = "assembly"
        result.error = err

    return result
