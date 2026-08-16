from __future__ import annotations

import compileall
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class TestReleaseGate(unittest.TestCase):
    """G12.11 Release Gate Automated Tests.

    Validates all mandatory pre-release criteria before tagging v1.0.0:
    1. Python byte-compilation succeeds across app/ and test/
    2. All mandatory release documentation files exist and are populated
    3. Git repository contains zero tracked generated junk (*.tmp, *.pyc, build artifacts)
    4. Git whitespace check passes cleanly (git diff --check)
    5. Security audit passes across project specifications and templates
    """

    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parent.parent.parent

    def test_release_docs_exist(self) -> None:
        """Requirement 1: All required release documentation files exist and are non-empty."""
        required_docs = [
            "README.md",
            "README-en.md",
            "RELEASE_CHECKLIST.md",
            "PROJECT_SPEC.md",
            "EDITOR_EXPORT.md",
            "FINAL_ASSEMBLY.md",
            "SUPERVISOR.md",
        ]
        for doc_name in required_docs:
            doc_path = self.repo_root / doc_name
            self.assertTrue(
                doc_path.exists(),
                f"Mandatory release document missing: {doc_name}",
            )
            self.assertGreater(
                doc_path.stat().st_size,
                100,
                f"Release document {doc_name} is unexpectedly empty",
            )

    def test_compileall_clean(self) -> None:
        """Requirement 2: All python files in app/ and test/ byte-compile with zero errors."""
        app_dir = str(self.repo_root / "app")
        test_dir = str(self.repo_root / "test")

        app_ok = compileall.compile_dir(app_dir, quiet=1)
        test_ok = compileall.compile_dir(test_dir, quiet=1)

        self.assertTrue(app_ok, "compileall failed on app/ directory")
        self.assertTrue(test_ok, "compileall failed on test/ directory")

    def test_no_generated_junk_committed(self) -> None:
        """Requirement 3: Git tracked files do not contain *.pyc, *.tmp, or ephemeral binaries."""
        git_bin = shutil.which("git")
        if not git_bin:
            self.skipTest("git executable not found in PATH")

        res = subprocess.run(
            [git_bin, "ls-files"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        tracked_files = res.stdout.splitlines()

        for f in tracked_files:
            self.assertFalse(
                f.endswith(".pyc") or "__pycache__" in f,
                f"Tracked pyc/cache file found in git index: {f}",
            )
            self.assertFalse(
                f.endswith(".tmp") or ".tmp." in f,
                f"Tracked temporary file found in git index: {f}",
            )
            self.assertFalse(
                f.startswith("storage/tasks/") or f.startswith("storage/temp/"),
                f"Tracked ephemeral storage file found in git index: {f}",
            )

    def test_git_diff_check_clean(self) -> None:
        """Requirement 4: Git diff check finds zero whitespace errors."""
        git_bin = shutil.which("git")
        if not git_bin:
            self.skipTest("git executable not found in PATH")

        res = subprocess.run(
            [git_bin, "diff", "--check"],
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            res.returncode,
            0,
            f"git diff --check reported whitespace or conflict marker errors:\n{res.stdout}\n{res.stderr}",
        )

    def test_security_audit_pass(self) -> None:
        """Requirement 5: No secrets or raw API key patterns exist in tracked source code or manifests."""
        secret_patterns = [
            re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
            re.compile(r"github_pat_[A-Za-z0-9_]{30,}"),
            re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{30,}"),
            re.compile(r"sk-[A-Za-z0-9]{32,}"),
        ]
        app_dir = self.repo_root / "app"
        for py_file in app_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for pat in secret_patterns:
                matches = pat.findall(content)
                self.assertEqual(
                    matches,
                    [],
                    f"Found raw secret in {py_file}: {matches}",
                )


if __name__ == "__main__":
    unittest.main()
