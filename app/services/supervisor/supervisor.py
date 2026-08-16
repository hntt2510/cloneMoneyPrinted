from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable
import yaml
from pydantic import BaseModel, ConfigDict, Field
from loguru import logger

from app.services.supervisor.github_client import GitHubClient, sanitize_sensitive_text
from app.services.supervisor.job_schema import AgentJob, parse_job_from_issue_body
from app.services.supervisor.state_machine import JobState, JobStateStore, InvalidStateTransitionError
from app.services.supervisor.qa_runner import QARunner, QAResult
from app.services.supervisor.git_enforcer import GitEnforcer, GitEnforcerError
from app.services.supervisor.coding_agent_dispatch import (
    CodingBrief,
    AgentResult,
    dispatch_coding_agent,
    AgentUnavailableError,
)


class SupervisorConfig(BaseModel):
    """Configuration loaded from .agents/orchestrator.yaml."""

    model_config = ConfigDict(extra="forbid")

    allowed_repo: str = "hntt2510/cloneMoneyPrinted"
    allowed_base_branch: str = "main"
    allow_push_main: bool = True
    allow_force_push: bool = False
    max_parallel_jobs: int = 1
    polling_interval_s: int = 30
    required_labels: list[str] = Field(default_factory=lambda: ["agent:queued"])
    stop_labels: list[str] = Field(default_factory=lambda: ["agent:cancelled"])
    qa_commands: list[str] = Field(
        default_factory=lambda: [
            "python -m compileall app test",
            "python -m unittest discover -s test",
            "uv lock --check",
            "git diff --check",
        ]
    )
    working_directory: str = "."
    state_directory: str = ".agents/state"
    log_directory: str = ".agents/logs"
    trusted_github_actors: list[str] = Field(default_factory=lambda: ["hntt2510"])
    max_qa_retries: int = 3


def load_supervisor_config(config_path: str | Path = ".agents/orchestrator.yaml") -> SupervisorConfig:
    """Load and validate orchestrator.yaml configuration."""
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Config file {config_path} not found; using default supervisor config.")
        return SupervisorConfig()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return SupervisorConfig(**data)
    except Exception as exc:
        logger.error(f"Error reading config from {config_path}: {exc}")
        return SupervisorConfig()


class SupervisorLoop:
    """Autonomous GitHub -> Antigravity supervisor process."""

    def __init__(
        self,
        config_path: str | Path = ".agents/orchestrator.yaml",
        github_client: GitHubClient | None = None,
        state_store: JobStateStore | None = None,
        git_enforcer: GitEnforcer | None = None,
        qa_runner: QARunner | None = None,
        agent_dispatcher: Callable[[CodingBrief], AgentResult] | None = None,
    ) -> None:
        self.config = load_supervisor_config(config_path)
        self.cwd = Path(self.config.working_directory).resolve()
        self.github_client = github_client or GitHubClient()
        self.state_store = state_store or JobStateStore(self.config.state_directory)
        self.git_enforcer = git_enforcer or GitEnforcer(self.cwd)
        self.qa_runner = qa_runner or QARunner()
        self.agent_dispatcher = agent_dispatcher or dispatch_coding_agent

        # Security invariant: Disallow force push strictly
        if self.config.allow_force_push:
            raise ValueError("allow_force_push must be False in supervisor configuration")

    def _check_cancellation(self, repo: str, issue_number: int, job_id: str) -> bool:
        """Check if job has been cancelled via GitHub label."""
        for stop_label in self.config.stop_labels:
            if self.github_client.check_cancel(repo, issue_number, cancel_label=stop_label):
                logger.warning(f"Job {job_id} cancelled by label '{stop_label}'")
                try:
                    self.state_store.transition(
                        job_id,
                        JobState.CANCELLED,
                        metadata={"reason": f"Cancelled by label {stop_label}"},
                    )
                    self.github_client.post_status(
                        repo,
                        issue_number,
                        f"🛑 **Supervisor Stopped**: Job cancelled via label `{stop_label}` before next action.",
                    )
                except Exception as exc:
                    logger.error(f"Error recording cancellation for {job_id}: {exc}")
                return True
        return False

    def poll_and_fetch_next_job(self) -> tuple[AgentJob | None, dict[str, Any] | None]:
        """Poll GitHub API for candidate queued issues and validate trust/schema."""
        label = self.config.required_labels[0] if self.config.required_labels else "agent:queued"
        issues = self.github_client.list_queued_jobs(self.config.allowed_repo, label=label)
        if not issues:
            return None, None

        for issue_dict in issues:
            issue_number = issue_dict.get("number")
            author_dict = issue_dict.get("user") or {}
            author = author_dict.get("login", "")

            # Validate trusted author policy
            if self.config.trusted_github_actors and author not in self.config.trusted_github_actors:
                logger.warning(
                    f"Skipping issue #{issue_number} from untrusted author '{author}'"
                )
                continue

            body = issue_dict.get("body", "")
            job = parse_job_from_issue_body(body, issue_number=issue_number, issue_author=author)
            if not job:
                logger.warning(f"Issue #{issue_number} does not contain a valid AgentJob schema.")
                continue

            # Validate repository match
            if job.repo != self.config.allowed_repo:
                logger.warning(
                    f"Issue #{issue_number} specifies repository '{job.repo}', but supervisor is restricted to '{self.config.allowed_repo}'"
                )
                continue

            return job, issue_dict

        return None, None

    def run_once(
        self,
        job: AgentJob | None = None,
        issue_data: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> JobState:
        """Execute a single cycle: claim -> code -> QA -> merge -> main QA -> push -> report."""
        if job is None:
            job, issue_data = self.poll_and_fetch_next_job()
            if job is None:
                return JobState.QUEUED

        issue_number = job.issue_number or (issue_data.get("number") if issue_data else 0)
        active_run_id = run_id or uuid.uuid4().hex[:8]
        job_id = JobStateStore.get_job_id(issue_number, job.base_sha, active_run_id)

        # Idempotency / Active Lease Check
        existing_state = self.state_store.load(job_id)
        if existing_state:
            curr_state_str = existing_state.get("current_state")
            if curr_state_str in (JobState.DONE.value, JobState.BLOCKED.value, JobState.CANCELLED.value):
                logger.info(f"Job {job_id} is already terminal ({curr_state_str}). Skipping.")
                return JobState(curr_state_str)

        # Step 1: Claim Job on GitHub
        claimed = self.github_client.claim_job(
            repo=job.repo,
            issue_number=issue_number,
            run_id=active_run_id,
            claimed_label="agent:claimed",
            queued_label=self.config.required_labels[0] if self.config.required_labels else "agent:queued",
        )
        if not claimed:
            logger.warning(f"Could not claim job #{issue_number}. Already claimed or active lease present.")
            return JobState.QUEUED

        if not existing_state:
            self.state_store.initialize_state(
                job_id=job_id,
                issue_number=issue_number,
                base_sha=job.base_sha,
                run_id=active_run_id,
                initial_state=JobState.CLAIMED,
                metadata={"job": job.model_dump()},
            )
        else:
            self.state_store.transition(job_id, JobState.CLAIMED)

        # Kill Switch Check
        if self._check_cancellation(job.repo, issue_number, job_id):
            return JobState.CANCELLED

        # Step 2: Validate Base SHA and Ancestry
        try:
            self.git_enforcer.assert_clean_worktree()
            current_head = self.git_enforcer.current_sha()
            if job.base_sha and not current_head.startswith(job.base_sha):
                # Verify ancestor
                try:
                    self.git_enforcer.assert_ancestor(job.base_sha, current_head)
                except GitEnforcerError as anc_err:
                    err_msg = f"Base SHA mismatch: '{job.base_sha}' is not an ancestor of HEAD ({current_head})"
                    logger.error(err_msg)
                    self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
                    self.github_client.post_status(
                        job.repo,
                        issue_number,
                        f"❌ **Supervisor Blocked**: {err_msg}",
                    )
                    return JobState.BLOCKED
        except GitEnforcerError as git_err:
            err_msg = f"Git validation error: {git_err}"
            logger.error(err_msg)
            self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
            self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
            return JobState.BLOCKED

        # Create Feature Branch
        try:
            self.git_enforcer.create_feature_branch(job.branch, job.base_sha)
        except GitEnforcerError as branch_err:
            # If branch already exists, switch to it
            try:
                self.git_enforcer.switch_branch(job.branch)
            except Exception:
                err_msg = f"Failed to create/switch branch {job.branch}: {branch_err}"
                self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
                self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
                return JobState.BLOCKED

        # Step 3: Coding Agent Dispatch
        if self._check_cancellation(job.repo, issue_number, job_id):
            return JobState.CANCELLED

        self.state_store.transition(job_id, JobState.CODING)
        brief = CodingBrief(
            repo_path=str(self.cwd),
            base_sha=job.base_sha,
            branch=job.branch,
            goal_spec=job.objective or job.raw_issue_body,
            qa_commands=job.qa_commands or self.config.qa_commands,
            stop_condition=job.stop_after,
        )

        try:
            agent_res = self.agent_dispatcher(brief)
            if not agent_res.success:
                err_msg = f"Coding agent dispatch failed: {agent_res.error or agent_res.output}"
                logger.error(err_msg)
                self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
                self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
                return JobState.BLOCKED
        except AgentUnavailableError as agy_err:
            err_msg = f"Agent runner unavailable: {agy_err}"
            logger.error(err_msg)
            self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
            self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
            return JobState.BLOCKED

        # Step 4: QA & Bounded Fixing Loop
        if self._check_cancellation(job.repo, issue_number, job_id):
            return JobState.CANCELLED

        self.state_store.transition(job_id, JobState.QA)
        qa_result = self.qa_runner.run_qa(self.cwd, extra_commands=job.qa_commands)

        attempt = 0
        while not qa_result.passed and attempt < self.config.max_qa_retries:
            attempt += 1
            logger.warning(f"QA failed on attempt {attempt}/{self.config.max_qa_retries}. Failed: {qa_result.failed_commands}")
            if self._check_cancellation(job.repo, issue_number, job_id):
                return JobState.CANCELLED

            self.state_store.transition(
                job_id,
                JobState.FIXING,
                metadata={"attempt": attempt, "failed_commands": qa_result.failed_commands},
            )

            # Re-dispatch agent with failure context
            fixing_goal = (
                f"{job.objective}\n\n"
                f"### PREVIOUS QA ATTEMPT {attempt} FAILED\n"
                f"Failed checks: {qa_result.failed_commands}\n"
                f"QA Output Snippet:\n{qa_result.output[-1000:]}"
            )
            fix_brief = CodingBrief(
                repo_path=str(self.cwd),
                base_sha=job.base_sha,
                branch=job.branch,
                goal_spec=fixing_goal,
                qa_commands=job.qa_commands or self.config.qa_commands,
            )
            self.agent_dispatcher(fix_brief)

            if self._check_cancellation(job.repo, issue_number, job_id):
                return JobState.CANCELLED

            self.state_store.transition(job_id, JobState.QA)
            qa_result = self.qa_runner.run_qa(self.cwd, extra_commands=job.qa_commands)

        if not qa_result.passed:
            err_msg = f"QA failed after {self.config.max_qa_retries} attempts: {qa_result.failed_commands}"
            logger.error(err_msg)
            self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
            self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
            return JobState.BLOCKED

        # Step 5: Feature Commit Validation
        try:
            self.git_enforcer.assert_clean_worktree()
        except GitEnforcerError as dirty_err:
            err_msg = f"Uncommitted dirty changes remaining after feature QA: {dirty_err}"
            logger.error(err_msg)
            self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
            self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
            return JobState.BLOCKED

        if self._check_cancellation(job.repo, issue_number, job_id):
            return JobState.CANCELLED

        # Step 6: Merging into Target Base Branch (--no-ff)
        self.state_store.transition(job_id, JobState.MERGING)
        try:
            self.git_enforcer.switch_branch(job.merge_to)
            self.git_enforcer.assert_clean_worktree()
            merge_msg = f"merge: {job.goal_id} ({job.branch})"
            self.git_enforcer.merge_no_ff(job.branch, message=merge_msg)
        except GitEnforcerError as merge_err:
            err_msg = f"Merge failed: {merge_err}"
            logger.error(err_msg)
            self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
            self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
            return JobState.BLOCKED

        # Step 7: Main QA Verification
        if self._check_cancellation(job.repo, issue_number, job_id):
            return JobState.CANCELLED

        self.state_store.transition(job_id, JobState.MAIN_QA)
        main_qa_res = self.qa_runner.run_qa(self.cwd, extra_commands=job.qa_commands)
        if not main_qa_res.passed:
            err_msg = f"Merged main QA failed: {main_qa_res.failed_commands}"
            logger.error(err_msg)
            self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
            self.github_client.post_status(job.repo, issue_number, f"❌ **Supervisor Blocked**: {err_msg}")
            return JobState.BLOCKED

        # Step 8: Push to Origin
        if self._check_cancellation(job.repo, issue_number, job_id):
            return JobState.CANCELLED

        if self.config.allow_push_main and job.auto_push_main:
            self.state_store.transition(job_id, JobState.PUSHING)
            try:
                self.git_enforcer.push_origin(job.merge_to)
                self.git_enforcer.verify_push(job.merge_to)
            except GitEnforcerError as push_err:
                err_msg = f"Push to origin failed: {push_err}"
                logger.error(err_msg)
                # Note: push failure preserves state as PUSHING or BLOCKED without marking DONE
                self.state_store.transition(job_id, JobState.BLOCKED, metadata={"error": err_msg})
                self.github_client.post_status(job.repo, issue_number, f"⚠️ **Supervisor Push Failed**: {err_msg}")
                return JobState.BLOCKED

        # Step 9: Reporting & Mark DONE
        if self._check_cancellation(job.repo, issue_number, job_id):
            return JobState.CANCELLED

        self.state_store.transition(job_id, JobState.REPORTING)
        final_sha = self.git_enforcer.current_sha()
        report_msg = (
            f"✅ **Autonomous Supervisor Completed Job**\n"
            f"- Goal: `{job.goal_id}`\n"
            f"- Run ID: `{active_run_id}`\n"
            f"- Feature Branch: `{job.branch}`\n"
            f"- Merged Target: `{job.merge_to}`\n"
            f"- Final SHA: `{final_sha}`\n"
            f"- QA Checks: Passed\n"
        )
        self.github_client.post_status(job.repo, issue_number, report_msg)
        self.github_client.add_label(job.repo, issue_number, "agent:done")
        self.github_client.remove_label(job.repo, issue_number, "agent:claimed")

        self.state_store.transition(job_id, JobState.DONE, metadata={"final_sha": final_sha})
        return JobState.DONE

    def run_loop(self, interval_s: int | None = None, max_cycles: int | None = None) -> None:
        """Continuously poll and execute supervisor jobs."""
        poll_interval = interval_s or self.config.polling_interval_s
        cycles = 0
        logger.info(f"Starting SupervisorLoop (interval={poll_interval}s)...")
        while max_cycles is None or cycles < max_cycles:
            cycles += 1
            try:
                state = self.run_once()
                logger.debug(f"Cycle {cycles} completed with state: {state.value}")
            except Exception as exc:
                logger.error(f"Error in supervisor loop cycle {cycles}: {exc}")
            if max_cycles is None or cycles < max_cycles:
                time.sleep(poll_interval)
