from __future__ import annotations

import ast
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from app.utils.utils import check_ffmpeg_available, check_node_available


class TestDependencyAudit(unittest.TestCase):
    """G12.7 Dependency Audit Tests.

    Validates dependency lock reproducibility, actionable tool detection error messages
    (FFmpeg, Node.js), and absence of undeclared runtime downloads.
    """

    def test_uv_lock_reproducible(self) -> None:
        """Requirement 1: Dependency lock file is up-to-date and reproducible (uv lock --check)."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        # Locate uv executable
        uv_bin = shutil.which("uv")
        if not uv_bin:
            # Check standard uv path or fallback to python -m uv
            self.skipTest("uv executable not found in PATH for local test")

        res = subprocess.run(
            [uv_bin, "lock", "--check"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"uv lock --check failed (exit {res.returncode}):\n{res.stderr}\n{res.stdout}",
        )

    def test_ffmpeg_detection_error_message(self) -> None:
        """Requirement 2: Actionable error message provided when FFmpeg is not found."""
        with patch("app.utils.utils.get_ffmpeg_binary", return_value="nonexistent_ffmpeg_binary_xyz"), \
             patch("shutil.which", return_value=None):
            is_avail, msg = check_ffmpeg_available()
            self.assertFalse(is_avail)
            self.assertIn("FFmpeg", msg)
            self.assertIn("IMAGEIO_FFMPEG_EXE", msg)

    def test_node_detection_error_message(self) -> None:
        """Requirement 3: Actionable error message provided when Node.js is not found."""
        with patch("shutil.which", return_value=None):
            is_avail, msg = check_node_available()
            self.assertFalse(is_avail)
            self.assertIn("Node.js", msg)
            self.assertIn("Remotion", msg)

    def test_no_undeclared_runtime_downloads(self) -> None:
        """Requirement 4: No undeclared silent urllib urlretrieve calls exist in app/."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        app_dir = repo_root / "app"

        for py_file in app_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn(
                "urlretrieve",
                content,
                f"Silent download urlretrieve found in {py_file}",
            )


if __name__ == "__main__":
    unittest.main()
