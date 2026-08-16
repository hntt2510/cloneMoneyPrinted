from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from loguru import logger


class QAResult(BaseModel):
    """Result of running QA verification commands."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    failed_commands: list[str] = Field(default_factory=list)
    passed_commands: list[str] = Field(default_factory=list)
    output: str = ""
    command_outputs: dict[str, str] = Field(default_factory=dict)


class QARunner:
    """Independent supervisor QA verification runner."""

    MANDATORY_COMMANDS: list[str] = [
        "python -m compileall app test",
        "python -m unittest discover -s test",
        "uv lock --check",
        "git diff --check",
    ]

    def __init__(self, python_executable: str | None = None) -> None:
        if python_executable:
            self.python_executable = python_executable
        else:
            # Look for local venv python first, then sys.executable
            venv_win = Path(".venv") / "Scripts" / "python.exe"
            venv_posix = Path(".venv") / "bin" / "python"
            if venv_win.exists():
                self.python_executable = str(venv_win.resolve())
            elif venv_posix.exists():
                self.python_executable = str(venv_posix.resolve())
            else:
                self.python_executable = sys.executable

    def _resolve_cmd_args(self, cmd_str: str) -> list[str]:
        """Convert a shell command string into a safe argument list with python path resolved."""
        # Use shlex to parse arguments safely
        is_windows = sys.platform == "win32"
        parts = shlex.split(cmd_str, posix=not is_windows)
        if not parts:
            return []

        # Replace leading 'python' or 'python3' with target interpreter
        if parts[0].lower() in ("python", "python3", "python.exe"):
            parts[0] = self.python_executable

        return parts

    def run_qa(
        self,
        cwd: str | Path = ".",
        extra_commands: list[str] | None = None,
        timeout_per_command: int = 300,
    ) -> QAResult:
        """Run all mandatory and issue-specific QA commands sequentially."""
        cwd_path = Path(cwd).resolve()
        commands_to_run: list[str] = list(self.MANDATORY_COMMANDS)

        if extra_commands:
            for extra in extra_commands:
                extra_clean = extra.strip()
                if extra_clean and extra_clean not in commands_to_run:
                    commands_to_run.append(extra_clean)

        failed_commands: list[str] = []
        passed_commands: list[str] = []
        combined_logs: list[str] = []
        command_outputs: dict[str, str] = {}

        for cmd_str in commands_to_run:
            args = self._resolve_cmd_args(cmd_str)
            if not args:
                continue

            logger.info(f"Running QA check: {cmd_str} in {cwd_path}")
            try:
                proc = subprocess.run(
                    args,
                    cwd=str(cwd_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout_per_command,
                    shell=False,  # Enforce list-style, shell=False
                )
                output = proc.stdout or ""
                command_outputs[cmd_str] = output
                combined_logs.append(f"=== CMD: {cmd_str} (exit {proc.returncode}) ===\n{output}\n")

                if proc.returncode == 0:
                    passed_commands.append(cmd_str)
                    logger.info(f"QA check passed: {cmd_str}")
                else:
                    failed_commands.append(cmd_str)
                    logger.warning(f"QA check failed ({proc.returncode}): {cmd_str}")
            except subprocess.TimeoutExpired as exc:
                err_msg = f"Command timed out after {timeout_per_command}s: {cmd_str}"
                failed_commands.append(cmd_str)
                command_outputs[cmd_str] = err_msg
                combined_logs.append(f"=== CMD: {cmd_str} (TIMEOUT) ===\n{err_msg}\n")
                logger.error(err_msg)
            except Exception as exc:
                err_msg = f"Execution error for '{cmd_str}': {exc}"
                failed_commands.append(cmd_str)
                command_outputs[cmd_str] = err_msg
                combined_logs.append(f"=== CMD: {cmd_str} (ERROR) ===\n{err_msg}\n")
                logger.error(err_msg)

        passed = len(failed_commands) == 0
        return QAResult(
            passed=passed,
            failed_commands=failed_commands,
            passed_commands=passed_commands,
            output="\n".join(combined_logs),
            command_outputs=command_outputs,
        )
