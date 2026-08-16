from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.supervisor.github_client import GitHubClient, GitHubClientError, sanitize_sensitive_text
from app.services.supervisor.job_schema import AgentJob, parse_job_from_issue_body
from app.services.supervisor.state_machine import JobState, JobStateStore, InvalidStateTransitionError
from app.services.supervisor.qa_runner import QARunner, QAResult
from app.services.supervisor.git_enforcer import GitEnforcer, GitEnforcerError
from app.services.supervisor.coding_agent_dispatch import (
    CodingBrief,
    AgentResult,
    AgentUnavailableError,
    dispatch_coding_agent,
)
from app.services.supervisor.supervisor import SupervisorLoop, SupervisorConfig


class TestSupervisor(unittest.TestCase):
    """Unit test suite covering the 16 mandatory Autonomous Supervisor test cases."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.state_dir = Path(self.temp_dir) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_store = JobStateStore(state_dir=self.state_dir)

        self.mock_gh = MagicMock(spec=GitHubClient)
        self.mock_gh.token = "ghp_secrettoken1234567890abcdef123456"
        self.mock_gh.claim_job.return_value = True
        self.mock_gh.check_cancel.return_value = False
        self.mock_gh.post_status.return_value = {"id": 1}
        self.mock_gh.list_queued_jobs.return_value = []

        self.mock_git = MagicMock(spec=GitEnforcer)
        self.mock_git.current_sha.return_value = "0c391a39406ddcbc163798d3b6360b749f8184dc"
        self.mock_git.current_branch.return_value = "main"
        self.mock_git.assert_clean_worktree.return_value = None
        self.mock_git.assert_ancestor.return_value = None
        self.mock_git.has_new_commits.return_value = True

        self.mock_qa = MagicMock(spec=QARunner)
        self.mock_qa.run_qa.return_value = QAResult(
            passed=True,
            failed_commands=[],
            passed_commands=["python -m compileall app test"],
            output="All checks passed.",
        )

        self.mock_dispatcher = MagicMock(return_value=AgentResult(success=True, output="Done"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_job(
        self,
        base_sha: str = "0c391a39406ddcbc163798d3b6360b749f8184dc",
        repo: str = "hntt2510/cloneMoneyPrinted",
        issue_number: int = 101,
        author: str = "hntt2510",
    ) -> AgentJob:
        return AgentJob(
            agent_job_version="1.0",
            repo=repo,
            goal_id="G11",
            base_sha=base_sha,
            branch="feature/autonomous-github-supervisor",
            merge_to="main",
            merge_mode="no-ff",
            auto_push_main=True,
            objective="Build supervisor",
            issue_number=issue_number,
            issue_author=author,
        )

    def _get_supervisor(self) -> SupervisorLoop:
        sup = SupervisorLoop(
            config_path=".agents/orchestrator.yaml",
            github_client=self.mock_gh,
            state_store=self.state_store,
            git_enforcer=self.mock_git,
            qa_runner=self.mock_qa,
            agent_dispatcher=self.mock_dispatcher,
        )
        sup.config.allowed_repo = "hntt2510/cloneMoneyPrinted"
        sup.config.trusted_github_actors = ["hntt2510"]
        return sup

    # 1. test_queued_job_claim
    def test_queued_job_claim(self) -> None:
        """Verify that a queued job transitions QUEUED -> CLAIMED in state store and on GitHub."""
        sup = self._get_supervisor()
        job = self._create_sample_job()

        state = sup.run_once(job=job, run_id="run101")
        self.assertEqual(state, JobState.DONE)
        self.mock_gh.claim_job.assert_called_once()
        job_id = JobStateStore.get_job_id(job.issue_number, job.base_sha, "run101")
        stored = self.state_store.load(job_id)
        self.assertIsNotNone(stored)
        history_states = [h["to_state"] for h in stored["history"]]
        self.assertIn(JobState.CLAIMED.value, history_states)

    # 2. test_duplicate_claim_rejected
    def test_duplicate_claim_rejected(self) -> None:
        """Verify that a second supervisor cannot claim a job already claimed."""
        sup = self._get_supervisor()
        job = self._create_sample_job()
        self.mock_gh.claim_job.return_value = False

        state = sup.run_once(job=job, run_id="run102")
        self.assertEqual(state, JobState.QUEUED)
        self.mock_dispatcher.assert_not_called()

    # 3. test_untrusted_author_rejected
    def test_untrusted_author_rejected(self) -> None:
        """Verify that issues created by untrusted authors are ignored."""
        sup = self._get_supervisor()
        untrusted_body = (
            "---\n"
            "agent_job_version: '1.0'\n"
            "repo: 'hntt2510/cloneMoneyPrinted'\n"
            "goal_id: 'G11'\n"
            "base_sha: '0c391a39406ddcbc163798d3b6360b749f8184dc'\n"
            "branch: 'feature/bad'\n"
            "---\n"
            "## Objective\nMalicious task"
        )
        self.mock_gh.list_queued_jobs.return_value = [
            {"number": 99, "user": {"login": "attacker"}, "body": untrusted_body}
        ]
        job, data = sup.poll_and_fetch_next_job()
        self.assertIsNone(job)
        self.assertIsNone(data)

    # 4. test_base_sha_mismatch
    def test_base_sha_mismatch(self) -> None:
        """Verify that base SHA mismatch causes job to transition to BLOCKED."""
        sup = self._get_supervisor()
        job = self._create_sample_job(base_sha="1111111122222222333333334444444455555555")
        self.mock_git.current_sha.return_value = "0c391a39406ddcbc163798d3b6360b749f8184dc"
        self.mock_git.assert_ancestor.side_effect = GitEnforcerError("Not an ancestor")

        state = sup.run_once(job=job, run_id="run104")
        self.assertEqual(state, JobState.BLOCKED)
        self.mock_gh.post_status.assert_called()
        self.assertIn("Blocked", self.mock_gh.post_status.call_args_list[-1][0][2])

    # 5. test_coding_success
    def test_coding_success(self) -> None:
        """Verify successful coding and QA leads to DONE state."""
        sup = self._get_supervisor()
        job = self._create_sample_job()

        state = sup.run_once(job=job, run_id="run105")
        self.assertEqual(state, JobState.DONE)
        self.mock_dispatcher.assert_called_once()
        self.mock_git.merge_no_ff.assert_called_once()
        self.mock_git.push_origin.assert_called_once_with("main")

    # 6. test_qa_failure_fix_loop
    def test_qa_failure_fix_loop(self) -> None:
        """Verify QA failure triggers FIXING and recovers on next QA pass."""
        sup = self._get_supervisor()
        job = self._create_sample_job()

        # First QA fails, second QA passes
        fail_res = QAResult(
            passed=False,
            failed_commands=["python -m unittest discover -s test"],
            output="AssertionError: 1 != 2",
        )
        pass_res = QAResult(
            passed=True,
            failed_commands=[],
            passed_commands=["python -m unittest discover -s test"],
            output="All tests passed",
        )
        # Sequence: Feature QA 1 (fail), Feature QA 2 (pass), Main QA (pass)
        self.mock_qa.run_qa.side_effect = [fail_res, pass_res, pass_res]

        state = sup.run_once(job=job, run_id="run106")
        self.assertEqual(state, JobState.DONE)
        # Agent dispatched twice (initial + 1 fix)
        self.assertEqual(self.mock_dispatcher.call_count, 2)
        job_id = JobStateStore.get_job_id(job.issue_number, job.base_sha, "run106")
        stored = self.state_store.load(job_id)
        history_states = [h["to_state"] for h in stored["history"]]
        self.assertIn(JobState.FIXING.value, history_states)

    # 7. test_bounded_qa_failure_blocked
    def test_bounded_qa_failure_blocked(self) -> None:
        """Verify that repeated QA failures beyond max retries result in BLOCKED state."""
        sup = self._get_supervisor()
        job = self._create_sample_job()

        fail_res = QAResult(
            passed=False,
            failed_commands=["python -m unittest discover -s test"],
            output="Persistent failure",
        )
        self.mock_qa.run_qa.return_value = fail_res

        state = sup.run_once(job=job, run_id="run107")
        self.assertEqual(state, JobState.BLOCKED)
        self.mock_git.merge_no_ff.assert_not_called()
        self.mock_git.push_origin.assert_not_called()

    # 8. test_feature_commit_validation
    def test_feature_commit_validation(self) -> None:
        """Verify that dirty uncommitted changes block merge."""
        sup = self._get_supervisor()
        job = self._create_sample_job()
        # Clean at start, dirty after feature QA
        self.mock_git.assert_clean_worktree.side_effect = [None, GitEnforcerError("Dirty worktree")]

        state = sup.run_once(job=job, run_id="run108")
        self.assertEqual(state, JobState.BLOCKED)
        self.mock_git.merge_no_ff.assert_not_called()

    # 9. test_merge_blocked_while_qa_red
    def test_merge_blocked_while_qa_red(self) -> None:
        """Verify merge is never executed when QA is red."""
        sup = self._get_supervisor()
        job = self._create_sample_job()
        self.mock_qa.run_qa.return_value = QAResult(passed=False, failed_commands=["compileall"])

        state = sup.run_once(job=job, run_id="run109")
        self.assertEqual(state, JobState.BLOCKED)
        self.mock_git.merge_no_ff.assert_not_called()

    # 10. test_merged_main_qa
    def test_merged_main_qa(self) -> None:
        """Verify that QA runs again after merge into main branch."""
        sup = self._get_supervisor()
        job = self._create_sample_job()

        # Feature QA passes, Main QA fails
        feature_qa = QAResult(passed=True, passed_commands=["all"])
        main_qa_fail = QAResult(passed=False, failed_commands=["git diff --check"])
        self.mock_qa.run_qa.side_effect = [feature_qa, main_qa_fail]

        state = sup.run_once(job=job, run_id="run110")
        self.assertEqual(state, JobState.BLOCKED)
        self.mock_git.merge_no_ff.assert_called_once()
        self.mock_git.push_origin.assert_not_called()

    # 11. test_push_success
    def test_push_success(self) -> None:
        """Verify successful push verifies local SHA == remote SHA."""
        sup = self._get_supervisor()
        job = self._create_sample_job()

        state = sup.run_once(job=job, run_id="run111")
        self.assertEqual(state, JobState.DONE)
        self.mock_git.push_origin.assert_called_once_with("main")
        self.mock_git.verify_push.assert_called_once_with("main")

    # 12. test_push_failure_preserved
    def test_push_failure_preserved(self) -> None:
        """Verify that push failure does not mark job as DONE and preserves state."""
        sup = self._get_supervisor()
        job = self._create_sample_job()
        self.mock_git.push_origin.side_effect = GitEnforcerError("Remote rejected push")

        state = sup.run_once(job=job, run_id="run112")
        self.assertEqual(state, JobState.BLOCKED)
        job_id = JobStateStore.get_job_id(job.issue_number, job.base_sha, "run112")
        stored = self.state_store.load(job_id)
        self.assertNotEqual(stored["current_state"], JobState.DONE.value)

    # 13. test_restart_resume_idempotency
    def test_restart_resume_idempotency(self) -> None:
        """Verify reloading state from disk prevents redundant execution for terminal job."""
        sup = self._get_supervisor()
        job = self._create_sample_job()
        job_id = JobStateStore.get_job_id(job.issue_number, job.base_sha, "run113")

        # Initialize as DONE in state store
        self.state_store.initialize_state(job_id, job.issue_number, job.base_sha, "run113", initial_state=JobState.QUEUED)
        self.state_store.transition(job_id, JobState.CLAIMED)
        self.state_store.transition(job_id, JobState.CODING)
        self.state_store.transition(job_id, JobState.QA)
        self.state_store.transition(job_id, JobState.MERGING)
        self.state_store.transition(job_id, JobState.MAIN_QA)
        self.state_store.transition(job_id, JobState.PUSHING)
        self.state_store.transition(job_id, JobState.REPORTING)
        self.state_store.transition(job_id, JobState.DONE)

        state = sup.run_once(job=job, run_id="run113")
        self.assertEqual(state, JobState.DONE)
        self.mock_dispatcher.assert_not_called()
        self.mock_git.merge_no_ff.assert_not_called()

    # 14. test_cancellation_kill_switch
    def test_cancellation_kill_switch(self) -> None:
        """Verify agent:cancelled label causes immediate cancellation before git writes."""
        sup = self._get_supervisor()
        job = self._create_sample_job()
        self.mock_gh.check_cancel.return_value = True

        state = sup.run_once(job=job, run_id="run114")
        self.assertEqual(state, JobState.CANCELLED)
        self.mock_git.create_feature_branch.assert_not_called()
        self.mock_git.merge_no_ff.assert_not_called()
        self.mock_git.push_origin.assert_not_called()

    # 15. test_status_sanitization
    def test_status_sanitization(self) -> None:
        """Verify sensitive tokens are redacted from status messages and client output."""
        token = "ghp_secretTokenVal1234567890abcdef"
        raw_msg = f"Failed to authenticate with token {token} and Bearer {token}"
        sanitized = sanitize_sensitive_text(raw_msg, token=token)
        self.assertNotIn(token, sanitized)
        self.assertIn("***REDACTED***", sanitized)

        client = GitHubClient(token=token)
        err = GitHubClientError(f"HTTP 401: Invalid token {token}", status_code=401, token=token)
        self.assertNotIn(token, str(err))

    # 16. test_no_force_push
    def test_no_force_push(self) -> None:
        """Verify GitEnforcer strictly rejects any force push flags."""
        git = GitEnforcer(cwd=self.temp_dir)
        with self.assertRaises(GitEnforcerError) as ctx:
            git._run_git(["push", "--force", "origin", "main"])
        self.assertIn("strictly prohibited", str(ctx.exception))

        with self.assertRaises(GitEnforcerError) as ctx2:
            git._run_git(["push", "-f", "origin", "main"])
        self.assertIn("strictly prohibited", str(ctx2.exception))


if __name__ == "__main__":
    unittest.main()
