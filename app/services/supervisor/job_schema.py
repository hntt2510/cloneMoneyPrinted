from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
import yaml


class AgentJob(BaseModel):
    """Pydantic v2 specification model for autonomous agent jobs."""

    model_config = ConfigDict(extra="forbid")

    agent_job_version: str = "1.0"
    repo: str
    goal_id: str
    base_sha: str
    branch: str
    merge_to: str = "main"
    merge_mode: Literal["no-ff"] = "no-ff"
    auto_push_main: bool = True
    stop_after: str | None = None

    # Context extracted from markdown sections
    objective: str = ""
    scope: str = ""
    non_goals: str = ""
    acceptance_criteria: str = ""
    qa_commands: list[str] = Field(default_factory=list)
    runtime_smoke: str = ""
    final_report_format: str = ""
    raw_issue_body: str = ""
    issue_number: int | None = None
    issue_author: str | None = None


def extract_sections(markdown_text: str) -> dict[str, str]:
    """Extract ## sections from markdown text into a dictionary of normalized keys."""
    sections: dict[str, str] = {}
    pattern = r"(?m)^##\s+([^\n]+)\n(.*?)(?=(?:^##\s+)|$)"
    matches = re.finditer(pattern, markdown_text, re.DOTALL)
    for match in matches:
        title = match.group(1).strip()
        content = match.group(2).strip()
        norm_key = re.sub(r"[^a-zA-Z0-9_]+", "_", title.lower()).strip("_")
        sections[norm_key] = content
    return sections


def parse_command_list(section_content: str) -> list[str]:
    """Parse list of commands from markdown bullet points or code blocks."""
    commands: list[str] = []
    # Check if enclosed in code blocks
    code_blocks = re.findall(r"```(?:bash|sh|cmd|powershell)?\s*\n(.*?)\n```", section_content, re.DOTALL)
    if code_blocks:
        for block in code_blocks:
            for line in block.strip().splitlines():
                clean_line = line.strip()
                if clean_line and not clean_line.startswith("#"):
                    commands.append(clean_line)
        if commands:
            return commands

    # Otherwise parse list items
    for line in section_content.splitlines():
        clean_line = line.strip()
        if clean_line.startswith(("- ", "* ", "+ ")):
            cmd = clean_line[2:].strip().strip("`")
            if cmd:
                commands.append(cmd)
        elif clean_line and not clean_line.startswith("#"):
            commands.append(clean_line.strip("`"))
    return commands


def parse_job_from_issue_body(
    body: str,
    issue_number: int | None = None,
    issue_author: str | None = None,
) -> AgentJob | None:
    """Parse YAML frontmatter and markdown sections from GitHub Issue body."""
    if not body or not isinstance(body, str):
        return None

    # Match YAML frontmatter between --- delimiters
    fm_match = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", body, re.DOTALL)
    if not fm_match:
        return None

    fm_raw = fm_match.group(1)
    md_content = fm_match.group(2)

    try:
        data: dict[str, Any] = yaml.safe_load(fm_raw) or {}
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    # Parse markdown sections
    sections = extract_sections(md_content)

    qa_cmds = data.get("qa_commands")
    if qa_cmds is None:
        if "qa_commands" in sections:
            qa_cmds = parse_command_list(sections["qa_commands"])
        else:
            qa_cmds = []

    try:
        job = AgentJob(
            agent_job_version=str(data.get("agent_job_version", "1.0")),
            repo=str(data.get("repo", "")),
            goal_id=str(data.get("goal_id", "")),
            base_sha=str(data.get("base_sha", "")),
            branch=str(data.get("branch", "")),
            merge_to=str(data.get("merge_to", "main")),
            merge_mode=data.get("merge_mode", "no-ff"),
            auto_push_main=bool(data.get("auto_push_main", True)),
            stop_after=data.get("stop_after"),
            objective=sections.get("objective", ""),
            scope=sections.get("scope", ""),
            non_goals=sections.get("non_goals", ""),
            acceptance_criteria=sections.get("acceptance_criteria", ""),
            qa_commands=qa_cmds,
            runtime_smoke=sections.get("runtime_smoke", ""),
            final_report_format=sections.get("final_report_format", ""),
            raw_issue_body=body,
            issue_number=issue_number,
            issue_author=issue_author,
        )
        return job
    except Exception:
        return None
