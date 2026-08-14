from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from cli import parse_args, run_cli


class TestCliMotion(unittest.TestCase):
    def test_render_motion_only_requires_project(self):
        with self.assertRaises(SystemExit), patch("sys.stderr", new_callable=io.StringIO):
            parse_args(["--render-motion-only"])

    def test_render_motion_only_mutual_exclusion(self):
        with self.assertRaises(SystemExit), patch("sys.stderr", new_callable=io.StringIO):
            parse_args(["--project", "project.json", "--render-motion-only", "--validate-only"])

        with self.assertRaises(SystemExit), patch("sys.stderr", new_callable=io.StringIO):
            parse_args(["--project", "project.json", "--render-motion-only", "--plan-only"])

        with self.assertRaises(SystemExit), patch("sys.stderr", new_callable=io.StringIO):
            parse_args(["--project", "project.json", "--render-motion-only", "--acquire-broll-only"])

        with self.assertRaises(SystemExit), patch("sys.stderr", new_callable=io.StringIO):
            parse_args(["--project", "project.json", "--render-motion-only", "--stop-at", "terms"])

    def test_render_motion_only_dispatch(self):
        with patch("cli.load_project_spec"), \
             patch("cli.preflight_project"), \
             patch("app.services.motion_runner.run_motion_render", return_value={"status": "complete", "motion_count": 1}) as mock_runner, \
             patch("builtins.print") as mock_print:
            exit_code = run_cli(["--project", "project.json", "--render-motion-only", "--task-id", "motion-task-1"])
            self.assertEqual(exit_code, 0)
            mock_runner.assert_called_once_with("project.json", task_id="motion-task-1")
            mock_print.assert_called_once()


if __name__ == "__main__":
    unittest.main()
