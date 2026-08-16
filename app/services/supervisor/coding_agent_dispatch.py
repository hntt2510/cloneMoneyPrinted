from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from loguru import logger


class CodingBrief(BaseModel):
    """Structured brief passed to the autonomous coding agent."""

    model_config = ConfigDict(extra="forbid")

    repo_path: str
    base_sha: str
    branch: str
    goal_spec: str
    qa_commands: list[str] = Field(default_factory=list)
    stop_condition: str | None = None

    def to_prompt(self) -> str:
        """Render coding brief into an explicit prompt for the agent."""
        qa_lines = "\n".join(f"- {cmd}" for cmd in self.qa_commands) if self.qa_commands else "Standard QA suite"
        return (
            f"# Coding Task Specification\n"
            f"- Repository: `{self.repo_path}`\n"
            f"- Base SHA: `{self.base_sha}`\n"
            f"- Feature Branch: `{self.branch}`\n\n"
            f"## Goal Specification\n{self.goal_spec}\n\n"
            f"## Required QA Commands\n{qa_lines}\n\n"
            f"## Stop Condition\n{self.stop_condition or 'Pass all QA checks, commit to feature branch, and stop.'}\n"
        )


class AgentResult(BaseModel):
    """Result returned by coding agent execution."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    output: str = ""
    error: str | None = None
    exit_code: int = 0


class AgentUnavailableError(Exception):
    """Raised when the Antigravity CLI / agent runner binary is not found."""


def find_agy_binary(custom_path: str | None = None) -> str | None:
    """Find the path to the Antigravity CLI executable."""
    if custom_path and os.path.exists(custom_path):
        return custom_path
    for candidate in ("agy", "agy.exe", "antigravity", "antigravity.exe"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def dispatch_coding_agent(
    brief: CodingBrief,
    agy_binary: str | None = None,
    timeout: int = 1800,
) -> AgentResult:
    """Dispatch coding task to Antigravity CLI non-interactively using safe subprocess list arguments."""
    agy_path = find_agy_binary(agy_binary)
    if not agy_path:
        raise AgentUnavailableError(
            "Antigravity CLI ('agy') was not found in PATH or configured location. "
            "Unattended dispatch requires 'agy' binary or a mocked dispatcher."
        )

    prompt = brief.to_prompt()
    args = [
        agy_path,
        "run",
        "--prompt",
        prompt,
        "--workspace",
        brief.repo_path,
        "--model",
        "flash",
    ]

    logger.info(f"Dispatching coding agent with {agy_path} in {brief.repo_path}")
    try:
        proc = subprocess.run(
            args,
            cwd=brief.repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            shell=False,
        )
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
        output = f"{stdout_text}\n{stderr_text}".strip()

        success = proc.returncode == 0
        return AgentResult(
            success=success,
            output=output,
            error=stderr_text if not success else None,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error(f"Coding agent execution timed out after {timeout}s")
        return AgentResult(
            success=False,
            output=str(exc),
            error=f"Timeout expired after {timeout}s",
            exit_code=124,
        )
    except Exception as exc:
        logger.error(f"Coding agent dispatch error: {exc}")
        return AgentResult(
            success=False,
            output="",
            error=str(exc),
            exit_code=1,
        )
