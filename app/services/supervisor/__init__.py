"""Autonomous GitHub -> Antigravity Supervisor Module."""

from app.services.supervisor.github_client import GitHubClient, GitHubClientError, sanitize_sensitive_text
from app.services.supervisor.job_schema import AgentJob, parse_job_from_issue_body
from app.services.supervisor.state_machine import (
    JobState,
    JobStateStore,
    InvalidStateTransitionError,
)
from app.services.supervisor.qa_runner import QARunner, QAResult
from app.services.supervisor.git_enforcer import GitEnforcer, GitEnforcerError
from app.services.supervisor.coding_agent_dispatch import (
    CodingBrief,
    AgentResult,
    AgentUnavailableError,
    dispatch_coding_agent,
)
from app.services.supervisor.supervisor import SupervisorLoop, SupervisorConfig, load_supervisor_config

__all__ = [
    "GitHubClient",
    "GitHubClientError",
    "sanitize_sensitive_text",
    "AgentJob",
    "parse_job_from_issue_body",
    "JobState",
    "JobStateStore",
    "InvalidStateTransitionError",
    "QARunner",
    "QAResult",
    "GitEnforcer",
    "GitEnforcerError",
    "CodingBrief",
    "AgentResult",
    "AgentUnavailableError",
    "dispatch_coding_agent",
    "SupervisorLoop",
    "SupervisorConfig",
    "load_supervisor_config",
]
