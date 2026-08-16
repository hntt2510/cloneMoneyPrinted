from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.supervisor.github_client import GitHubClient
from app.services.supervisor.job_schema import AgentJob, parse_job_from_issue_body
from app.services.supervisor.state_machine import JobState, JobStateStore
from app.services.supervisor.qa_runner import QARunner, QAResult
from app.services.supervisor.git_enforcer import GitEnforcer
from app.services.supervisor.coding_agent_dispatch import CodingBrief, AgentResult
from app.services.supervisor.supervisor import SupervisorLoop


class TestSupervisorSmoke(unittest.TestCase):
    """Disposable local git fixture smoke tests for end-to-end supervisor lifecycle."""

    def setUp(self) -> None:
        self.temp_root = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_root) / "fixture_repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.remote_dir = Path(self.temp_root) / "fixture_remote.git"

        # Initialize bare remote repository
        subprocess.run(
            ["git", "init", "--bare", str(self.remote_dir)],
            cwd=str(self.temp_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            shell=False,
        )

        # Initialize real disposable git repository
        self._run_git(["init"])
        self._run_git(["checkout", "-b", "main"])
        self._run_git(["config", "user.name", "Supervisor Smoke Tester"])
        self._run_git(["config", "user.email", "smoke@example.com"])
        self._run_git(["config", "commit.gpgsign", "false"])

        # Add origin remote
        self._run_git(["remote", "add", "origin", str(self.remote_dir)])

        # Initial commit
        readme = self.repo_dir / "README.md"
        readme.write_text("# Disposable Test Repo\n", encoding="utf-8")
        self._run_git(["add", "README.md"])
        self._run_git(["commit", "-m", "chore: initial commit"])
        self._run_git(["push", "-u", "origin", "main"])

        res = self._run_git(["rev-parse", "HEAD"])
        self.base_sha = res.stdout.strip()

        # State directory
        self.state_dir = self.repo_dir / ".agents" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_store = JobStateStore(state_dir=self.state_dir)

        # Mock GitHub client
        self.mock_gh = MagicMock(spec=GitHubClient)
        self.mock_gh.token = "mock_smoke_token"
        self.mock_gh.claim_job.return_value = True
        self.mock_gh.check_cancel.return_value = False
        self.mock_gh.post_status.return_value = {"id": 1}

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git"] + args,
            cwd=str(self.repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
            shell=False,
        )

    def test_full_lifecycle_with_push_smoke(self) -> None:
        """Smoke test verifying full progression with remote push:
        QUEUED -> CLAIMED -> CODING -> QA -> MERGING -> MAIN_QA -> PUSHING -> REPORTING -> DONE
        """
        issue_body = (
            "---\n"
            "agent_job_version: '1.0'\n"
            "repo: 'hntt2510/cloneMoneyPrinted'\n"
            "goal_id: 'G11-SMOKE-PUSH'\n"
            f"base_sha: '{self.base_sha}'\n"
            "branch: 'feature/smoke-push-branch'\n"
            "merge_to: 'main'\n"
            "merge_mode: 'no-ff'\n"
            "auto_push_main: true\n"
            "---\n"
            "## Objective\n"
            "Smoke test verifying autonomous supervisor cycle with push."
        )

        job = parse_job_from_issue_body(issue_body, issue_number=42, issue_author="hntt2510")
        self.assertIsNotNone(job)
        assert job is not None

        def fixture_agent_dispatcher(brief: CodingBrief) -> AgentResult:
            feature_file = self.repo_dir / "smoke_push_feature.txt"
            feature_file.write_text("Automated feature artifact with push.\n", encoding="utf-8")
            self._run_git(["add", "smoke_push_feature.txt"])
            self._run_git(["commit", "-m", "feat: automated feature change with push"])
            return AgentResult(success=True, output="Feature committed.")

        git_enforcer = GitEnforcer(cwd=self.repo_dir)
        qa_runner = MagicMock(spec=QARunner)
        qa_runner.run_qa.return_value = QAResult(
            passed=True,
            passed_commands=["smoke_qa_check"],
            output="QA passed successfully.",
        )

        supervisor = SupervisorLoop(
            config_path=".agents/orchestrator.yaml",
            github_client=self.mock_gh,
            state_store=self.state_store,
            git_enforcer=git_enforcer,
            qa_runner=qa_runner,
            agent_dispatcher=fixture_agent_dispatcher,
        )
        supervisor.cwd = self.repo_dir
        supervisor.config.allowed_repo = "hntt2510/cloneMoneyPrinted"
        supervisor.config.trusted_github_actors = ["hntt2510"]
        supervisor.config.allow_push_main = True

        final_state = supervisor.run_once(job=job, run_id="smoke_push_run_1")
        self.assertEqual(final_state, JobState.DONE)

        # Verify git merge succeeded on main
        git_enforcer.switch_branch("main")
        merged_file = self.repo_dir / "smoke_push_feature.txt"
        self.assertTrue(merged_file.exists())

        # Verify state history
        job_id = JobStateStore.get_job_id(job.issue_number, job.base_sha, "smoke_push_run_1")
        state_data = self.state_store.load(job_id)
        self.assertIsNotNone(state_data)
        assert state_data is not None

        history = [entry["to_state"] for entry in state_data["history"]]
        expected_progression = [
            JobState.CLAIMED.value,
            JobState.CODING.value,
            JobState.QA.value,
            JobState.MERGING.value,
            JobState.MAIN_QA.value,
            JobState.PUSHING.value,
            JobState.REPORTING.value,
            JobState.DONE.value,
        ]
        for exp in expected_progression:
            self.assertIn(exp, history)

        # Verify remote received push
        remote_sha = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=str(self.remote_dir),
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout.strip()
        local_sha = git_enforcer.current_sha()
        self.assertEqual(local_sha, remote_sha)


if __name__ == "__main__":
    unittest.main()
