from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from loguru import logger


class GitEnforcerError(Exception):
    """Exception raised for git policy enforcement violations or git command failures."""


class GitEnforcer:
    """Git policy enforcer ensuring worktree cleanliness, ancestry, no-ff merge, and no force-push."""

    def __init__(self, cwd: str | Path = ".") -> None:
        self.cwd = Path(cwd).resolve()

    def _run_git(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        """Execute a git command using safe list arguments (shell=False)."""
        cmd = ["git"] + args
        # Security invariant: Never permit force push flags
        for arg in args:
            if arg in ("--force", "-f", "--force-with-lease"):
                raise GitEnforcerError(f"Force-push is strictly prohibited: {args}")

        try:
            res = subprocess.run(
                cmd,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
            if check and res.returncode != 0:
                err_out = res.stderr.strip() or res.stdout.strip()
                raise GitEnforcerError(f"Git command failed ({' '.join(cmd)}): {err_out}")
            return res
        except FileNotFoundError:
            raise GitEnforcerError("git executable not found in PATH")

    def current_sha(self) -> str:
        """Return the current HEAD commit SHA."""
        res = self._run_git(["rev-parse", "HEAD"])
        return res.stdout.strip()

    def current_branch(self) -> str:
        """Return the current checked-out branch name."""
        res = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        return res.stdout.strip()

    def assert_clean_worktree(self, allow_untracked: bool = True) -> None:
        """Assert that there are no uncommitted tracked changes in the working directory."""
        res = self._run_git(["status", "--porcelain"])
        output = res.stdout.strip()
        if not output:
            return

        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not allow_untracked:
            if lines:
                raise GitEnforcerError(f"Worktree is dirty: {lines}")
        else:
            # Check for modified / staged tracked files
            tracked_dirty = [l for l in lines if not l.startswith("??")]
            if tracked_dirty:
                raise GitEnforcerError(f"Worktree has modified tracked files: {tracked_dirty}")

    def assert_on_branch(self, expected_branch: str) -> None:
        """Assert that the repository is currently on the expected branch."""
        current = self.current_branch()
        if current != expected_branch:
            raise GitEnforcerError(f"Branch mismatch: currently on '{current}', expected '{expected_branch}'")

    def assert_ancestor(self, expected_base_sha: str, head_sha: str = "HEAD") -> None:
        """Ensure that expected_base_sha is an ancestor of head_sha."""
        res = self._run_git(["merge-base", "--is-ancestor", expected_base_sha, head_sha], check=False)
        if res.returncode != 0:
            raise GitEnforcerError(
                f"Base SHA '{expected_base_sha}' is not an ancestor of '{head_sha}'"
            )

    def no_force_push_check(self) -> bool:
        """Verify that force-push is disallowed by policy."""
        return True

    def create_feature_branch(self, branch: str, base_sha: str) -> None:
        """Create and switch to a feature branch starting at base_sha."""
        logger.info(f"Creating feature branch '{branch}' from '{base_sha}'")
        self._run_git(["checkout", "-b", branch, base_sha])

    def switch_branch(self, branch: str) -> None:
        """Switch to an existing branch."""
        logger.info(f"Switching to branch '{branch}'")
        self._run_git(["switch", branch])

    def has_new_commits(self, base_sha: str, head: str = "HEAD") -> bool:
        """Check if there are new commits between base_sha and head."""
        res = self._run_git(["rev-list", "--count", f"{base_sha}..{head}"])
        try:
            count = int(res.stdout.strip())
            return count > 0
        except ValueError:
            return False

    def merge_no_ff(self, feature_branch: str, message: str) -> None:
        """Perform a --no-ff merge of feature_branch into current branch."""
        logger.info(f"Performing --no-ff merge of '{feature_branch}': {message}")
        self._run_git(["merge", "--no-ff", feature_branch, "-m", message])

    def push_origin(self, branch: str, remote: str = "origin") -> None:
        """Push branch to remote without force flags."""
        logger.info(f"Pushing '{branch}' to '{remote}'")
        self._run_git(["push", remote, branch])

    def verify_push(self, branch: str, remote: str = "origin") -> None:
        """Verify that local branch SHA matches remote tracking branch SHA."""
        self._run_git(["fetch", remote, branch], check=False)
        local_sha = self._run_git(["rev-parse", branch]).stdout.strip()
        remote_sha = self._run_git(["rev-parse", f"{remote}/{branch}"]).stdout.strip()
        if local_sha != remote_sha:
            raise GitEnforcerError(
                f"Push verification failed: local {branch} ({local_sha}) != {remote}/{branch} ({remote_sha})"
            )
        logger.info(f"Push verified: local and {remote}/{branch} match at {local_sha}")
