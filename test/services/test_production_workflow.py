from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.assembly import AssemblyResult, FinalQCReport
from app.models.export import EditManifest, EditorPackageStatus, ExportResult
from app.services.production_workflow import ProductionWorkflowResult, run_production_workflow


class TestProductionWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.proj_file = Path(self.tmp_dir.name) / "project.json"
        self.proj_file.write_text('{"schema_version": "1.0", "project": {"title": "Test"}}', encoding="utf-8")

    def tearDown(self):
        self.tmp_dir.cleanup()

    @patch("app.services.production_workflow.run_all_project")
    @patch("app.services.production_workflow.export_editor_package")
    @patch("app.services.production_workflow.assemble_final_video")
    def test_stage_sequence_scene_assets(self, mock_assembly, mock_export, mock_orchestrator):
        mock_orchestrator.return_value = {
            "status": "complete",
            "task_id": "task-123",
            "ready_scenes": 3,
            "failed_scenes": 0,
        }

        res = run_production_workflow(
            project_path=self.proj_file,
            task_id="task-123",
            output_target="scene_assets",
        )

        mock_orchestrator.assert_called_once()
        _, kwargs = mock_orchestrator.call_args
        self.assertEqual(kwargs.get("task_id"), "task-123")
        mock_export.assert_not_called()
        mock_assembly.assert_not_called()

        self.assertEqual(res.task_id, "task-123")
        self.assertEqual(res.execution_status, "success")
        self.assertEqual(res.export_status, "not_run")
        self.assertEqual(res.assembly_status, "not_run")
        self.assertTrue(res.is_success)

    @patch("app.services.production_workflow.run_all_project")
    @patch("app.services.production_workflow.export_editor_package")
    @patch("app.services.production_workflow.assemble_final_video")
    def test_stage_sequence_editor_package(self, mock_assembly, mock_export, mock_orchestrator):
        mock_orchestrator.return_value = {
            "status": "complete",
            "task_id": "task-abc",
            "ready_scenes": 2,
            "failed_scenes": 0,
        }
        mock_export.return_value = ExportResult(
            status=EditorPackageStatus.complete.value,
            task_id="task-abc",
            export_dir="exports/test-project",
            edit_manifest_file="",
            readme_file="",
            ready_scene_count=2,
            missing_scene_count=0,
        )

        res = run_production_workflow(
            project_path=self.proj_file,
            task_id="task-abc",
            output_target="editor_package",
        )

        mock_orchestrator.assert_called_once()
        mock_export.assert_called_once()
        mock_assembly.assert_not_called()

        self.assertEqual(res.task_id, "task-abc")
        self.assertEqual(res.execution_status, "success")
        self.assertEqual(res.export_status, "success")
        self.assertEqual(res.assembly_status, "not_run")
        self.assertTrue(res.is_success)

    @patch("app.services.production_workflow.run_all_project")
    @patch("app.services.production_workflow.export_editor_package")
    @patch("app.services.production_workflow.assemble_final_video")
    def test_stage_sequence_final_video(self, mock_assembly, mock_export, mock_orchestrator):
        mock_orchestrator.return_value = {
            "status": "complete",
            "task_id": "task-xyz",
            "ready_scenes": 4,
            "failed_scenes": 0,
        }
        mock_export.return_value = ExportResult(
            status=EditorPackageStatus.complete.value,
            task_id="task-xyz",
            export_dir="exports/test-project",
            edit_manifest_file="",
            readme_file="",
            ready_scene_count=4,
            missing_scene_count=0,
        )
        fake_video = Path(self.tmp_dir.name) / "final.mp4"
        fake_video.write_bytes(b"dummy")
        qc_file = Path(self.tmp_dir.name) / "qc_report.json"
        qc_file.write_text(json.dumps({
            "is_valid": True,
            "final_video_file": str(fake_video),
            "file_size_bytes": 100,
            "sha256": "sha",
            "duration_seconds": 10.0,
            "fps": 30.0,
            "resolution": [1920, 1080],
            "has_video_stream": True,
            "has_audio_stream": True,
            "checks_passed": ["duration", "resolution"],
            "errors": [],
        }), encoding="utf-8")

        mock_assembly.return_value = AssemblyResult(
            status="complete",
            task_id="task-xyz",
            final_dir=str(self.tmp_dir.name),
            final_video_file=str(fake_video),
            assembly_manifest_file="",
            qc_report_file=str(qc_file),
        )

        res = run_production_workflow(
            project_path=self.proj_file,
            task_id="task-xyz",
            output_target="final_video",
        )

        mock_orchestrator.assert_called_once()
        mock_export.assert_called_once()
        mock_assembly.assert_called_once()

        self.assertEqual(res.task_id, "task-xyz")
        self.assertEqual(res.execution_status, "success")
        self.assertEqual(res.export_status, "success")
        self.assertEqual(res.assembly_status, "success")
        self.assertEqual(res.final_video, str(fake_video))
        self.assertTrue(res.is_success)

    @patch("app.services.production_workflow.run_all_project")
    @patch("app.services.production_workflow.export_editor_package")
    @patch("app.services.production_workflow.assemble_final_video")
    def test_assembly_qc_failure(self, mock_assembly, mock_export, mock_orchestrator):
        mock_orchestrator.return_value = {
            "status": "complete",
            "task_id": "task-qc-fail",
            "ready_scenes": 2,
            "failed_scenes": 0,
        }
        mock_export.return_value = ExportResult(
            status=EditorPackageStatus.complete.value,
            task_id="task-qc-fail",
            export_dir="exports/test-project",
            edit_manifest_file="",
            readme_file="",
            ready_scene_count=2,
            missing_scene_count=0,
        )
        fake_video = Path(self.tmp_dir.name) / "bad_final.mp4"
        fake_video.write_bytes(b"dummy")
        qc_file = Path(self.tmp_dir.name) / "bad_qc.json"
        qc_file.write_text(json.dumps({
            "is_valid": False,
            "final_video_file": str(fake_video),
            "file_size_bytes": 100,
            "sha256": "sha",
            "duration_seconds": 10.0,
            "fps": 30.0,
            "resolution": [1920, 1080],
            "has_video_stream": True,
            "has_audio_stream": False,
            "checks_passed": [],
            "errors": ["Missing audio stream"],
        }), encoding="utf-8")

        mock_assembly.return_value = AssemblyResult(
            status="failed",
            task_id="task-qc-fail",
            final_dir=str(self.tmp_dir.name),
            final_video_file=str(fake_video),
            assembly_manifest_file="",
            qc_report_file=str(qc_file),
            error="QC check failed",
        )

        res = run_production_workflow(
            project_path=self.proj_file,
            task_id="task-qc-fail",
            output_target="final_video",
        )

        self.assertEqual(res.assembly_status, "failed")
        self.assertEqual(res.failed_stage, "assembly")
        self.assertFalse(res.is_success)
        self.assertIn("Final QC failed", str(res.error))

    @patch("app.services.production_workflow.run_all_project")
    @patch("app.services.production_workflow.export_editor_package")
    def test_orchestrator_failure_halts_workflow(self, mock_export, mock_orchestrator):
        mock_orchestrator.side_effect = RuntimeError("Orchestration network timeout")

        res = run_production_workflow(
            project_path=self.proj_file,
            task_id="task-fail",
            output_target="final_video",
        )

        self.assertEqual(res.execution_status, "failed")
        self.assertEqual(res.failed_stage, "execution")
        self.assertIn("Orchestration network timeout", str(res.error))
        mock_export.assert_not_called()
        self.assertFalse(res.is_success)

    @patch("app.services.production_workflow.run_all_project")
    @patch("app.services.production_workflow.export_editor_package")
    @patch("app.services.production_workflow.assemble_final_video")
    def test_export_failure_halts_workflow(self, mock_assembly, mock_export, mock_orchestrator):
        mock_orchestrator.return_value = {
            "status": "complete",
            "task_id": "task-exp-fail",
            "ready_scenes": 2,
            "failed_scenes": 0,
        }
        mock_export.return_value = ExportResult(
            status=EditorPackageStatus.failed.value,
            task_id="task-exp-fail",
            export_dir="",
            edit_manifest_file="",
            readme_file="",
            ready_scene_count=0,
            missing_scene_count=2,
            error="Asset corruption in scene 1",
        )

        res = run_production_workflow(
            project_path=self.proj_file,
            task_id="task-exp-fail",
            output_target="final_video",
        )

        self.assertEqual(res.execution_status, "success")
        self.assertEqual(res.export_status, "failed")
        self.assertEqual(res.failed_stage, "export")
        mock_assembly.assert_not_called()
        self.assertFalse(res.is_success)


if __name__ == "__main__":
    unittest.main()
