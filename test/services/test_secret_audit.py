from __future__ import annotations

import unittest

from app.services.supervisor.github_client import (
    GitHubClientError,
    sanitize_exception,
    sanitize_sensitive_text,
)


class TestSecretAudit(unittest.TestCase):
    """G12.6 Secret / PII Audit Tests.

    Validates that authorization tokens, bearer tokens, query parameters, API keys,
    passwords, and nested exception chains are never leaked in plaintext in logs,
    error messages, or supervisor status comments.
    """

    def test_github_token_not_in_status_comment(self) -> None:
        """Requirement 1: GitHub tokens are sanitized from status comments/output strings."""
        token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        raw_comment = f"Task completed successfully by supervisor using auth token {token}."
        sanitized = sanitize_sensitive_text(raw_comment, token=token)

        self.assertNotIn(token, sanitized)
        self.assertIn("***REDACTED***", sanitized)

    def test_bearer_token_redacted_in_exception(self) -> None:
        """Requirement 2: Bearer tokens in exception messages are redacted."""
        secret_bearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123"
        raw_msg = f"HTTP 401 Unauthorized: Authorization header was {secret_bearer}"

        err = GitHubClientError(raw_msg)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123", str(err))
        self.assertIn("***REDACTED***", str(err))

    def test_url_query_token_redacted(self) -> None:
        """Requirement 3: URLs containing ?token=... or &secret=... query params are sanitized."""
        url1 = "https://api.example.com/data?token=secretTokenValue12345&format=json"
        url2 = "https://api.example.com/v1/search?q=query&api_key=AIzaSyD_SecretApiKey999"
        url3 = "https://cdn.example.com/file.mp4?sig=Signature123456&secret=MyTopSecretVal"

        sanitized1 = sanitize_sensitive_text(url1)
        sanitized2 = sanitize_sensitive_text(url2)
        sanitized3 = sanitize_sensitive_text(url3)

        self.assertNotIn("secretTokenValue12345", sanitized1)
        self.assertNotIn("AIzaSyD_SecretApiKey999", sanitized2)
        self.assertNotIn("Signature123456", sanitized3)
        self.assertNotIn("MyTopSecretVal", sanitized3)

        self.assertIn("?token=***REDACTED***", sanitized1)
        self.assertIn("&api_key=***REDACTED***", sanitized2)
        self.assertIn("?sig=***REDACTED***", sanitized3)
        self.assertIn("&secret=***REDACTED***", sanitized3)

    def test_api_key_pattern_redacted(self) -> None:
        """Requirement 4: Strings matching api_key=..., apikey=..., secret=..., password=... are redacted."""
        test_cases = [
            ("Connecting with api_key=sk-proj-supersecretkey12345 to endpoint", "sk-proj-supersecretkey12345"),
            ("Payload config: apikey='my_api_key_value_99999'", "my_api_key_value_99999"),
            ("Database credential: password=\"SuperSecretPass123!\"", "SuperSecretPass123!"),
            ("Service secret: secret=TopSecretServiceTokenValue", "TopSecretServiceTokenValue"),
        ]
        for raw, secret_val in test_cases:
            sanitized = sanitize_sensitive_text(raw)
            self.assertNotIn(
                secret_val,
                sanitized,
                f"Secret value '{secret_val}' was not redacted in '{sanitized}'",
            )
            self.assertIn("***REDACTED***", sanitized)

    def test_nested_exception_chain_sanitized(self) -> None:
        """Requirement 5: Sensitive tokens in nested exception causes are sanitized."""
        token = "github_pat_11AABCDEF1234567890abcdefghijklmnopqrstuvwxyz"
        try:
            try:
                raise ValueError(f"Underlying socket error with auth token: {token}")
            except Exception as inner:
                raise RuntimeError(f"Higher-level service failure during request with bearer {token}") from inner
        except Exception as chained_exc:
            sanitized_repr = sanitize_exception(chained_exc, token=token)
            self.assertNotIn(token, sanitized_repr)
            self.assertIn("***REDACTED***", sanitized_repr)
            self.assertIn("Cause:", sanitized_repr)


if __name__ == "__main__":
    unittest.main()
