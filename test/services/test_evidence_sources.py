from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services.evidence_sources import (
    SSRFValidationError,
    compute_file_sha256,
    detect_file_mime,
    download_evidence_file,
    extract_webpage_content,
    is_safe_remote_url,
    sanitize_secret_url,
)


class TestEvidenceSources(unittest.TestCase):
    def test_ssrf_blocks_private_and_loopback_urls(self):
        blocked_urls = [
            "http://127.0.0.1/doc.pdf",
            "http://localhost:8000/report",
            "http://10.0.1.5/evidence.pdf",
            "http://192.168.1.100/data.json",
            "http://172.16.0.5/page.html",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/secret.pdf",
            "file:///C:/Windows/system32/cmd.exe",
            "ftp://files.example.com/test.pdf",
            "javascript:alert(1)",
            "data:text/plain;base64,SGVsbG8=",
        ]
        for url in blocked_urls:
            is_safe, reason = is_safe_remote_url(url)
            self.assertFalse(is_safe, f"Expected '{url}' to be rejected, but passed. Reason: {reason}")

    def test_ssrf_allows_public_https_urls(self):
        with patch("socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]  # public IP
            is_safe, reason = is_safe_remote_url("https://www.example.com/report.pdf")
            self.assertTrue(is_safe, f"Expected public HTTPS URL to be safe, failed: {reason}")

    def test_sanitize_secret_url(self):
        raw_url = "https://example.com/download.pdf?token=secret123&api_key=mykey456&page=12&sig=ab9876&section=intro"
        sanitized = sanitize_secret_url(raw_url)
        self.assertNotIn("secret123", sanitized)
        self.assertNotIn("mykey456", sanitized)
        self.assertNotIn("ab9876", sanitized)
        self.assertIn("page=12", sanitized)
        self.assertIn("section=intro", sanitized)

    def test_detect_file_mime(self):
        pdf_hdr = b"%PDF-1.5 \n%..."
        self.assertEqual(detect_file_mime("test.pdf", header_bytes=pdf_hdr), "application/pdf")

        png_hdr = b"\x89PNG\r\n\x1a\n\x00\x00"
        self.assertEqual(detect_file_mime("test.png", header_bytes=png_hdr), "image/png")

        html_hdr = b"<!DOCTYPE html><html><head><title>Test</title></head><body>Hello</body></html>"
        self.assertEqual(detect_file_mime("test.html", header_bytes=html_hdr), "text/html")

    def test_extract_webpage_content(self):
        sample_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Retirement Security Guidelines | SSA</title>
            <meta name="publisher" content="Social Security Administration">
            <meta name="description" content="Official retirement age information">
            <style>body { font-size: 14px; }</style>
            <script>console.log("tracker");</script>
        </head>
        <body>
            <header><nav><a href="/">Home</a></nav></header>
            <main>
                <h1>Retirement Age Rules</h1>
                <p>Full retirement age is 67 for individuals born in 1960 or later.</p>
                <p>Early retirement benefits can be claimed starting at age 62 with a permanent reduction.</p>
            </main>
            <footer>Copyright 2026</footer>
        </body>
        </html>
        """
        extracted = extract_webpage_content(sample_html, source_url="https://www.ssa.gov/retirement")
        self.assertEqual(extracted["title"], "Retirement Security Guidelines | SSA")
        self.assertEqual(extracted["publisher"], "Social Security Administration")
        self.assertIn("Full retirement age is 67", extracted["text"])
        self.assertIn("Early retirement benefits can be claimed starting at age 62", extracted["text"])
        self.assertNotIn("tracker", extracted["text"])
        self.assertNotIn("font-size", extracted["text"])


    def test_content_length_oversized_rejected_before_streaming(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "large.pdf"
            with patch("app.services.evidence_sources.is_safe_remote_url", return_value=(True, None)):
                with patch("requests.Session.get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 200
                    mock_resp.headers = {"Content-Length": "200000000"}  # 200 MB > 100 MB limit
                    mock_get.return_value.__enter__.return_value = mock_resp

                    with self.assertRaises(ValueError) as ctx:
                        download_evidence_file("https://example.com/large.pdf", dest_path=dest, max_bytes=104857600)
                    self.assertIn("exceeds maximum limit", str(ctx.exception))
                    mock_resp.iter_content.assert_not_called()

    def test_validate_source_kind_mime(self):
        from app.models.evidence import EvidenceSourceKind
        from app.services.evidence_sources import validate_source_kind_mime

        # PDF valid
        valid, mime = validate_source_kind_mime(EvidenceSourceKind.pdf, "application/pdf")
        self.assertTrue(valid)

        # PDF with image mime -> rejected
        valid, reason = validate_source_kind_mime(EvidenceSourceKind.pdf, "image/jpeg")
        self.assertFalse(valid)
        self.assertIn("does not match detected MIME type", reason)

        # Webpage with PDF mime -> rejected
        valid, reason = validate_source_kind_mime(EvidenceSourceKind.webpage, "application/pdf")
        self.assertFalse(valid)

        # Image with HTML mime -> rejected
        valid, reason = validate_source_kind_mime(EvidenceSourceKind.image, "text/html")
        self.assertFalse(valid)

    def test_ssrf_safe_session_blocks_redirect_to_localhost_and_private(self):
        from app.services.evidence_sources import SSRFSafeSession, SSRFValidationError

        session = SSRFSafeSession()
        req = MagicMock()

        # Redirect to 127.0.0.1
        req.url = "http://127.0.0.1/secret"
        with self.assertRaises(SSRFValidationError):
            session.rebuild_auth(req, MagicMock())

        # Redirect to 10.0.0.1
        req.url = "http://10.0.0.1/internal/admin"
        with self.assertRaises(SSRFValidationError):
            session.rebuild_auth(req, MagicMock())


if __name__ == "__main__":
    unittest.main()
