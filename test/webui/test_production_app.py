from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path or sys.path[0] != str(ROOT_DIR):
    sys.path.insert(0, str(ROOT_DIR))

try:
    from streamlit.testing.v1 import AppTest
    HAS_APP_TEST = True
except ImportError:
    HAS_APP_TEST = False

from webui.production import render_production_workspace


class TestProductionApp(unittest.TestCase):
    @unittest.skipUnless(HAS_APP_TEST, "streamlit.testing.v1.AppTest not available")
    def test_production_workspace_renders_by_default(self):
        main_py = str(Path(__file__).parent.parent.parent / "webui" / "Main.py")
        at = AppTest.from_file(main_py)
        # Timeout safety
        at.run(timeout=10)

        # Check that no unhandled exceptions crashed the run
        self.assertFalse(at.exception)

        # Verify Workspace Mode radio in sidebar defaults to Production Workspace
        workspace_radios = [r for r in at.sidebar.radio if r.label == "Workspace Mode"]
        self.assertTrue(len(workspace_radios) > 0)
        self.assertEqual(workspace_radios[0].value, "Production Workspace")

        # Verify Production Workspace header rendered
        titles = [t.value for t in at.title]
        self.assertTrue(any("Production Video Workspace" in t for t in titles))

    @unittest.skipUnless(HAS_APP_TEST, "streamlit.testing.v1.AppTest not available")
    def test_production_form_inputs_exist(self):
        main_py = str(Path(__file__).parent.parent.parent / "webui" / "Main.py")
        at = AppTest.from_file(main_py)
        at.run(timeout=10)

        # Verify key production input fields
        text_areas = [ta.label for ta in at.text_area]
        self.assertTrue(any("Video Topic / Research Subject" in lbl for lbl in text_areas))

        # Verify Start Production button exists
        buttons = [b.label for b in at.button]
        self.assertTrue(any("Start Production Workflow" in lbl for lbl in buttons))

    @patch("webui.production.st")
    def test_direct_render_production_workspace_headless(self, mock_st):
        # Configure st mock to simulate interactive controls
        mock_st.session_state = {}
        mock_st.radio.side_effect = (
            lambda label, *args, **kwargs: "Mode A: Form Builder (Interactive)"
            if "Configuration" in label
            else "Final Video (G08 → G09 → G10 Assembly)"
        )
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.button.return_value = False
        mock_st.selectbox.return_value = "16:9"
        mock_st.number_input.return_value = 30
        mock_st.text_input.return_value = "Test"
        mock_st.text_area.return_value = "Test Subject"
        mock_st.checkbox.return_value = True
        mock_st.multiselect.return_value = ["pexels"]
        mock_st.file_uploader.return_value = None
        mock_st.expander.return_value.__enter__.return_value = MagicMock()
        mock_st.container.return_value.__enter__.return_value = MagicMock()

        # Should render cleanly without raising any exceptions
        render_production_workspace()
        mock_st.title.assert_called_once()
        self.assertIn("Production Video Workspace", mock_st.title.call_args[0][0])

    @patch("webui.production.st")
    def test_results_section_sanitizes_failed_workflow_error(self, mock_st):
        import json
        import shutil
        from app.services.production_workflow import ProductionWorkflowResult

        task_id = "test-task-secret-sanitization-1234"
        task_dir = Path(ROOT_DIR) / "storage" / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Create minimal execution_manifest.json so Results section is entered
            manifest_path = task_dir / "execution_manifest.json"
            manifest_path.write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "project_title": "Sanitization Test",
                    "task_id": task_id,
                    "status": "failed",
                    "fps": 30,
                    "scenes": [],
                }),
                encoding="utf-8",
            )

            # Set up session state with active_task_id and failed ProductionWorkflowResult
            wf_res = ProductionWorkflowResult(
                task_id=task_id,
                execution_status="failed",
                failed_stage="assembly",
                error="Final QC failed: token=secret123 and bearer secret_jwt_token",
            )
            mock_st.session_state = {
                "production_task_id": task_id,
                "production_run_result": wf_res,
            }
            mock_st.radio.side_effect = (
                lambda label, *args, **kwargs: "Mode A: Form Builder (Interactive)"
                if "Configuration" in label
                else "Final Video (G08 → G09 → G10 Assembly)"
            )
            mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
            mock_st.button.return_value = False
            mock_st.selectbox.return_value = "16:9"
            mock_st.number_input.return_value = 30
            mock_st.text_input.return_value = "Test"
            mock_st.text_area.return_value = "Test Subject"
            mock_st.checkbox.return_value = True
            mock_st.multiselect.return_value = ["pexels"]
            mock_st.file_uploader.return_value = None
            mock_st.expander.return_value.__enter__.return_value = MagicMock()
            mock_st.container.return_value.__enter__.return_value = MagicMock()

            # Execute render_production_workspace() - must not raise NameError
            render_production_workspace()

            # Assert st.error was called with sanitized message
            error_calls = [call[0][0] for call in mock_st.error.call_args_list]
            self.assertTrue(len(error_calls) > 0, "Expected st.error to be called for failed workflow")

            # Find the workflow error call
            wf_error_call = next((e for e in error_calls if "Production Workflow Incomplete" in e), None)
            self.assertIsNotNone(wf_error_call, f"Workflow error call not found in {error_calls}")

            # Assertions
            self.assertNotIn("token=secret123", wf_error_call)
            self.assertNotIn("secret_jwt_token", wf_error_call)
            self.assertIn("[REDACTED]", wf_error_call)
            self.assertIn(task_id, wf_error_call)
            self.assertIn("Final QC failed:", wf_error_call)
            self.assertIn("assembly", wf_error_call)
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


class TestModeCWorkspacePersistence(unittest.TestCase):
    """Regression tests for Mode C workspace persistence across st.rerun() and G09/G10 canonical paths."""

    def setUp(self):
        self.task_id = "c909e895-846a-4283-9ee2-70a9bc7e8a0d"
        self.task_dir = Path(ROOT_DIR) / "storage" / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.proj_file = self.task_dir / "project.json"
        self.proj_file.write_text(
            json.dumps({
                "schema_version": "1.0",
                "project": {"title": "Why Electric Cars Feel So Fast"},
                "script": {"subject": "EV acceleration and instant torque physics"},
                "narration": {"mode": "tts"},
            }),
            encoding="utf-8-sig",
        )
        self.manifest_file = self.task_dir / "execution_manifest.json"
        self.manifest_file.write_text(
            json.dumps({
                "schema_version": "1.0",
                "project_title": "Why Electric Cars Feel So Fast",
                "task_id": self.task_id,
                "status": "failed",
                "fps": 30,
                "scenes": [
                    {
                        "scene_id": "S001",
                        "start_frame": 0,
                        "end_frame": 90,
                        "visual_type": "DATA",
                        "status": "completed",
                    }
                ],
            }),
            encoding="utf-8-sig",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.task_dir, ignore_errors=True)

    def _setup_mock_st(self, mock_st):
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.selectbox.return_value = f"{self.task_id} — Why Electric Cars Feel So Fast"
        mock_st.file_uploader.return_value = None
        mock_st.text_input.return_value = "Test"
        mock_st.text_area.return_value = "Test Subject"
        mock_st.checkbox.return_value = True
        mock_st.multiselect.return_value = ["pexels"]
        mock_st.number_input.return_value = 30
        mock_st.expander.return_value.__enter__.return_value = MagicMock()
        mock_st.container.return_value.__enter__.return_value = MagicMock()

    @patch("webui.production.st")
    def test_mode_c_load_survives_rerun_and_shows_banner(self, mock_st):
        """Mode C loaded state in session_state re-hydrates spec on every render."""
        self._setup_mock_st(mock_st)
        mock_st.session_state = {
            "production_task_id": self.task_id,
            "production_loaded_project_path": str(self.proj_file),
            "production_workspace_loaded": True,
        }
        mock_st.radio.side_effect = (
            lambda label, *args, **kwargs: "Mode C: Reopen Task Workspace"
            if "Configuration" in label
            else "Final Video (G08 → G09 → G10 Assembly)"
        )
        mock_st.button.return_value = False

        # Render workspace (simulates post-st.rerun render cycle)
        render_production_workspace()

        # Assert success banner was rendered with project details
        success_calls = [call[0][0] for call in mock_st.success.call_args_list]
        self.assertTrue(any("Workspace Loaded ✅" in s for s in success_calls))
        self.assertTrue(any("Why Electric Cars Feel So Fast" in s for s in success_calls))
        self.assertTrue(any("FAILED" in s for s in success_calls))

    @patch("webui.production.run_production_workflow")
    @patch("webui.production.st")
    def test_mode_c_start_production_workflow_uses_same_task_id_and_resolved_path(self, mock_st, mock_run_wf):
        """Start Production Workflow for Mode C passes the reopened active_project_path and same task_id."""
        from app.services.production_workflow import ProductionWorkflowResult

        self._setup_mock_st(mock_st)
        mock_run_wf.return_value = ProductionWorkflowResult(
            task_id=self.task_id,
            execution_status="completed",
            final_video=str(self.task_dir / "final_video.mp4"),
        )
        mock_st.session_state = {
            "production_task_id": self.task_id,
            "production_loaded_project_path": str(self.proj_file),
            "production_workspace_loaded": True,
        }
        mock_st.radio.side_effect = (
            lambda label, *args, **kwargs: "Mode C: Reopen Task Workspace"
            if "Configuration" in label
            else "Final Video (G08 → G09 → G10 Assembly)"
        )
        mock_st.button.side_effect = lambda label, *args, **kwargs: "Start Production Workflow" in label
        mock_st.progress.return_value = MagicMock()

        render_production_workspace()

        # Verify run_production_workflow called with original task_id and proj_file (NOT project_inputs)
        mock_run_wf.assert_called_once()
        _, kwargs = mock_run_wf.call_args
        self.assertEqual(kwargs.get("task_id"), self.task_id)
        self.assertEqual(Path(kwargs.get("project_path")).resolve(), self.proj_file.resolve())

    @patch("webui.production.export_editor_package")
    @patch("webui.production.assemble_final_video")
    @patch("webui.production.st")
    def test_g09_and_g10_buttons_use_canonical_active_project_path(self, mock_st, mock_ass, mock_exp):
        """Re-export and Assemble buttons pass the canonical active_project_path."""
        self._setup_mock_st(mock_st)
        mock_exp.return_value = MagicMock(export_dir=str(self.task_dir / "editor_export"))
        mock_ass.return_value = MagicMock(master_video=str(self.task_dir / "final.mp4"), qc_report_file=None)

        mock_st.session_state = {
            "production_task_id": self.task_id,
            "production_loaded_project_path": str(self.proj_file),
            "production_workspace_loaded": True,
        }
        mock_st.radio.side_effect = (
            lambda label, *args, **kwargs: "Mode C: Reopen Task Workspace"
            if "Configuration" in label
            else "Final Video (G08 → G09 → G10 Assembly)"
        )

        # Trigger Re-export Editor Package
        mock_st.button.side_effect = lambda label, *args, **kwargs: "Re-export Editor Package" in label
        render_production_workspace()
        mock_exp.assert_called_once()
        exp_proj_arg = mock_exp.call_args[0][0]
        self.assertEqual(Path(exp_proj_arg).resolve(), self.proj_file.resolve())

        # Trigger Assemble Final Video
        mock_st.button.side_effect = lambda label, *args, **kwargs: "Assemble Final Video" in label
        render_production_workspace()
        mock_ass.assert_called_once()
        ass_proj_arg = mock_ass.call_args[0][0]
        self.assertEqual(Path(ass_proj_arg).resolve(), self.proj_file.resolve())

    @patch("webui.production.st")
    def test_results_render_immediately_without_pressing_start(self, mock_st):
        """Loading a task immediately renders manifest and scenes without pressing start."""
        self._setup_mock_st(mock_st)
        mock_st.session_state = {
            "production_task_id": self.task_id,
            "production_loaded_project_path": str(self.proj_file),
            "production_workspace_loaded": True,
        }
        mock_st.radio.side_effect = (
            lambda label, *args, **kwargs: "Mode C: Reopen Task Workspace"
            if "Configuration" in label
            else "Final Video (G08 → G09 → G10 Assembly)"
        )
        mock_st.button.return_value = False

        render_production_workspace()

        # Assert Task Results & Review header rendered in results
        headers = [call[0][0] for call in mock_st.header.call_args_list]
        self.assertTrue(any("Task Results & Review" in h for h in headers))

        subheaders = [call[0][0] for call in mock_st.subheader.call_args_list]
        self.assertTrue(any("Scene Asset Grid" in sh for sh in subheaders))


if __name__ == "__main__":
    unittest.main()
