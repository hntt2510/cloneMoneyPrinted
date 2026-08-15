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


if __name__ == "__main__":
    unittest.main()
