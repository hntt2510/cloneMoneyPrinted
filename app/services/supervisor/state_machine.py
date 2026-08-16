from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from loguru import logger


class JobState(str, Enum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    PLANNING = "PLANNING"
    CODING = "CODING"
    QA = "QA"
    FIXING = "FIXING"
    MERGING = "MERGING"
    MAIN_QA = "MAIN_QA"
    PUSHING = "PUSHING"
    REPORTING = "REPORTING"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


VALID_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.QUEUED: {JobState.CLAIMED, JobState.CANCELLED, JobState.BLOCKED},
    JobState.CLAIMED: {JobState.PLANNING, JobState.CODING, JobState.CANCELLED, JobState.BLOCKED},
    JobState.PLANNING: {JobState.CODING, JobState.CANCELLED, JobState.BLOCKED},
    JobState.CODING: {JobState.QA, JobState.CANCELLED, JobState.BLOCKED},
    JobState.QA: {JobState.FIXING, JobState.MERGING, JobState.BLOCKED, JobState.CANCELLED},
    JobState.FIXING: {JobState.QA, JobState.BLOCKED, JobState.CANCELLED},
    JobState.MERGING: {JobState.MAIN_QA, JobState.BLOCKED, JobState.CANCELLED},
    JobState.MAIN_QA: {JobState.PUSHING, JobState.REPORTING, JobState.BLOCKED, JobState.CANCELLED},
    JobState.PUSHING: {JobState.REPORTING, JobState.BLOCKED, JobState.CANCELLED},
    JobState.REPORTING: {JobState.DONE, JobState.BLOCKED, JobState.CANCELLED},
    JobState.DONE: set(),
    JobState.BLOCKED: set(),
    JobState.CANCELLED: set(),
}


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""


class JobStateStore:
    """Manages persistent JSON state storage for supervisor agent jobs."""

    def __init__(self, state_dir: str | Path = ".agents/state") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_job_id(issue_number: int | str, base_sha: str, run_id: str) -> str:
        """Create deterministic job key: <issue>_<base_sha[:8]>_<run_id>."""
        sha_prefix = base_sha[:8] if base_sha else "unknown"
        return f"{issue_number}_{sha_prefix}_{run_id}"

    def _get_path(self, job_id: str) -> Path:
        # Sanitize filename
        safe_id = "".join(c for c in job_id if c.isalnum() or c in ("-", "_", "."))
        return self.state_dir / f"{safe_id}.json"

    def load(self, job_id: str) -> dict[str, Any] | None:
        """Load job state dictionary from disk."""
        path = self._get_path(job_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error(f"Failed to load state for {job_id}: {exc}")
            return None

    def save(self, job_id: str, data: dict[str, Any]) -> None:
        """Save job state dictionary atomically to disk."""
        path = self._get_path(job_id)
        temp_path = path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(path)
        except Exception as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.error(f"Failed to save state for {job_id}: {exc}")
            raise

    def initialize_state(
        self,
        job_id: str,
        issue_number: int,
        base_sha: str,
        run_id: str,
        initial_state: JobState = JobState.QUEUED,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create initial state record."""
        now = datetime.now(timezone.utc).isoformat()
        state_data: dict[str, Any] = {
            "job_id": job_id,
            "issue_number": issue_number,
            "base_sha": base_sha,
            "run_id": run_id,
            "current_state": initial_state.value,
            "created_at": now,
            "updated_at": now,
            "history": [
                {
                    "from_state": None,
                    "to_state": initial_state.value,
                    "timestamp": now,
                    "metadata": metadata or {},
                }
            ],
            "metadata": metadata or {},
        }
        self.save(job_id, state_data)
        return state_data

    def transition(
        self,
        job_id: str,
        new_state: JobState,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate and transition job to new state, recording timestamp & history."""
        data = self.load(job_id)
        if not data:
            raise FileNotFoundError(f"No existing state found for job_id '{job_id}'")

        curr_state_str = data.get("current_state", JobState.QUEUED.value)
        try:
            curr_state = JobState(curr_state_str)
        except ValueError:
            curr_state = JobState.QUEUED

        allowed = VALID_TRANSITIONS.get(curr_state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(
                f"Invalid transition from {curr_state.value} to {new_state.value} for job {job_id}"
            )

        now = datetime.now(timezone.utc).isoformat()
        data["current_state"] = new_state.value
        data["updated_at"] = now
        if metadata:
            data.setdefault("metadata", {}).update(metadata)

        history_entry = {
            "from_state": curr_state.value,
            "to_state": new_state.value,
            "timestamp": now,
            "metadata": metadata or {},
        }
        data.setdefault("history", []).append(history_entry)

        self.save(job_id, data)
        logger.info(f"Job {job_id} transitioned: {curr_state.value} -> {new_state.value}")
        return data
