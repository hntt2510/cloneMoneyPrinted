from __future__ import annotations

import re
from typing import Any
import httpx
from loguru import logger


def sanitize_sensitive_text(text: str, token: str | None = None) -> str:
    """Sanitize secrets and tokens from text before logging or reporting."""
    if not text:
        return ""
    sanitized = text
    if token and len(token) > 3:
        sanitized = sanitized.replace(token, "***REDACTED***")
    # Redact common token patterns (GitHub PAT, Bearer tokens, etc.)
    sanitized = re.sub(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", r"\1***REDACTED***", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(token\s+)[A-Za-z0-9_\-\.]+", r"\1***REDACTED***", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"(ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{30,})", r"***REDACTED***", sanitized)
    sanitized = re.sub(r"([A-Za-z0-9_\-]{35,})", r"***REDACTED***", sanitized)
    return sanitized


class GitHubClientError(Exception):
    """Exception raised for GitHub API client errors."""

    def __init__(self, message: str, status_code: int | None = None, token: str | None = None) -> None:
        sanitized_message = sanitize_sensitive_text(message, token)
        super().__init__(sanitized_message)
        self.status_code = status_code


class GitHubClient:
    """Synchronous GitHub REST API client using httpx with credential sanitization."""

    def __init__(
        self,
        token: str | None = None,
        client: httpx.Client | None = None,
        base_url: str = "https://api.github.com",
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._external_client = client
        self._client = client or httpx.Client(timeout=30.0)

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Autonomous-Supervisor/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def close(self) -> None:
        """Close the underlying HTTP client if supervisor owns it."""
        if not self._external_client:
            self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def list_queued_jobs(
        self,
        repo: str,
        label: str = "agent:queued",
        state: str = "open",
    ) -> list[dict[str, Any]]:
        """List open issues labeled with the required queued label."""
        url = f"{self.base_url}/repos/{repo}/issues"
        params = {"labels": label, "state": state, "per_page": 50}
        try:
            resp = self._client.get(url, headers=self._get_headers(), params=params)
            if resp.status_code != 200:
                logger.warning(
                    sanitize_sensitive_text(
                        f"Failed to list queued jobs for {repo}: HTTP {resp.status_code} - {resp.text}",
                        self.token,
                    )
                )
                return []
            data = resp.json()
            # Filter out pull requests as GitHub returns PRs in issues endpoint
            issues = [item for item in data if "pull_request" not in item]
            return issues
        except Exception as exc:
            logger.error(
                sanitize_sensitive_text(f"Error listing queued jobs for {repo}: {exc}", self.token)
            )
            return []

    def get_issue(self, repo: str, issue_number: int) -> dict[str, Any]:
        """Fetch a specific issue by number."""
        url = f"{self.base_url}/repos/{repo}/issues/{issue_number}"
        try:
            resp = self._client.get(url, headers=self._get_headers())
            if resp.status_code != 200:
                raise GitHubClientError(
                    f"Failed to get issue #{issue_number}: HTTP {resp.status_code} - {resp.text}",
                    status_code=resp.status_code,
                    token=self.token,
                )
            return resp.json()
        except GitHubClientError:
            raise
        except Exception as exc:
            raise GitHubClientError(f"Error getting issue #{issue_number}: {exc}", token=self.token) from exc

    def add_label(self, repo: str, issue_number: int, label: str) -> None:
        """Add a label to an issue."""
        url = f"{self.base_url}/repos/{repo}/issues/{issue_number}/labels"
        payload = {"labels": [label]}
        try:
            resp = self._client.post(url, headers=self._get_headers(), json=payload)
            if resp.status_code not in (200, 201):
                logger.warning(
                    sanitize_sensitive_text(
                        f"Failed to add label {label} to #{issue_number}: HTTP {resp.status_code}",
                        self.token,
                    )
                )
        except Exception as exc:
            logger.error(
                sanitize_sensitive_text(
                    f"Error adding label {label} to #{issue_number}: {exc}", self.token
                )
            )

    def remove_label(self, repo: str, issue_number: int, label: str) -> None:
        """Remove a label from an issue."""
        url = f"{self.base_url}/repos/{repo}/issues/{issue_number}/labels/{label}"
        try:
            resp = self._client.delete(url, headers=self._get_headers())
            if resp.status_code not in (200, 204, 404):
                logger.warning(
                    sanitize_sensitive_text(
                        f"Failed to remove label {label} from #{issue_number}: HTTP {resp.status_code}",
                        self.token,
                    )
                )
        except Exception as exc:
            logger.error(
                sanitize_sensitive_text(
                    f"Error removing label {label} from #{issue_number}: {exc}", self.token
                )
            )

    def claim_job(
        self,
        repo: str,
        issue_number: int,
        run_id: str,
        claimed_label: str = "agent:claimed",
        queued_label: str = "agent:queued",
    ) -> bool:
        """Claim an issue atomically by verifying state and updating labels."""
        try:
            issue = self.get_issue(repo, issue_number)
            labels = [lbl.get("name", "") if isinstance(lbl, dict) else str(lbl) for lbl in issue.get("labels", [])]
            if claimed_label in labels:
                logger.info(f"Issue #{issue_number} is already claimed.")
                return False

            self.add_label(repo, issue_number, claimed_label)
            self.remove_label(repo, issue_number, queued_label)
            claim_msg = f"🤖 **Autonomous Supervisor Claimed Job**\n- Run ID: `{run_id}`\n- Status: `CLAIMED`"
            self.post_status(repo, issue_number, claim_msg)
            return True
        except Exception as exc:
            logger.error(
                sanitize_sensitive_text(
                    f"Failed to claim job #{issue_number}: {exc}", self.token
                )
            )
            return False

    def check_cancel(self, repo: str, issue_number: int, cancel_label: str = "agent:cancelled") -> bool:
        """Check if an issue has been marked with the cancellation label."""
        try:
            issue = self.get_issue(repo, issue_number)
            labels = [lbl.get("name", "") if isinstance(lbl, dict) else str(lbl) for lbl in issue.get("labels", [])]
            return cancel_label in labels
        except Exception as exc:
            logger.warning(
                sanitize_sensitive_text(
                    f"Could not check cancel status for #{issue_number}: {exc}", self.token
                )
            )
            return False

    def post_status(self, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        """Post a status comment to an issue with sanitized content."""
        sanitized_body = sanitize_sensitive_text(body, self.token)
        url = f"{self.base_url}/repos/{repo}/issues/{issue_number}/comments"
        payload = {"body": sanitized_body}
        try:
            resp = self._client.post(url, headers=self._get_headers(), json=payload)
            if resp.status_code not in (200, 201):
                logger.warning(
                    sanitize_sensitive_text(
                        f"Failed to post status comment to #{issue_number}: HTTP {resp.status_code}",
                        self.token,
                    )
                )
                return {}
            return resp.json()
        except Exception as exc:
            logger.error(
                sanitize_sensitive_text(
                    f"Error posting status comment to #{issue_number}: {exc}", self.token
                )
            )
            return {}
