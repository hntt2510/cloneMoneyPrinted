from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
