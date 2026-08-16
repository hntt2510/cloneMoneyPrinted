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


if __name__ == "__main__":
    unittest.main()
