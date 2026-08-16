from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path or sys.path[0] != str(ROOT_DIR):
    sys.path.insert(0, str(ROOT_DIR))

from app.models.evidence import EvidenceSource, EvidenceSourceKind, EvidenceSourceRegistry, EvidenceSourceTrust
from app.services.evidence_runner import discover_source_registry
from app.services.project_spec import load_project_spec
from webui.production import (
    check_providers_readiness,
    create_editor_package_zip,
    format_fallback_badge,
    get_recent_tasks,
    sanitize_manifest_for_display,
    save_uploaded_file,
)


class DummyUploadedFile:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getbuffer(self) -> bytes:
        return self._content

    def read(self) -> bytes:
        return self._content


class TestProductionHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_save_uploaded_file_path_traversal_forward_slash(self):
        malicious_file = DummyUploadedFile("../../outside.pdf", b"document content")
        saved_path = save_uploaded_file(malicious_file, self.target_dir)

        self.assertTrue(saved_path.exists())
        self.assertEqual(saved_path.name, "outside.pdf")
        self.assertEqual(saved_path.parent, self.target_dir.resolve())

    def test_save_uploaded_file_path_traversal_back_slash(self):
        malicious_file = DummyUploadedFile("..\\..\\secret.json", b'{"safe": true}')
        saved_path = save_uploaded_file(malicious_file, self.target_dir)

        self.assertTrue(saved_path.exists())
        self.assertEqual(saved_path.name, "secret.json")
        self.assertEqual(saved_path.parent, self.target_dir.resolve())

    def test_save_uploaded_file_extension_whitelist(self):
        bad_file = DummyUploadedFile("script.exe", b"binary")
        with self.assertRaises(ValueError):
            save_uploaded_file(bad_file, self.target_dir, allowed_extensions={".pdf", ".json"})

        good_file = DummyUploadedFile("doc.PDF", b"pdf content")
        saved = save_uploaded_file(good_file, self.target_dir, allowed_extensions={".pdf", ".json"})
        self.assertTrue(saved.exists())

    def test_utf8_bom_support_load_project_spec(self):
        bom_proj_file = self.target_dir / "project.bom.json"
        valid_spec_data = {
            "schema_version": "1.0",
            "project": {"title": "BOM Test Project"},
            "script": {"subject": "BOM Handling"},
            "narration": {"mode": "tts"},
        }
        # Write with UTF-8 BOM
        bom_proj_file.write_text(json.dumps(valid_spec_data), encoding="utf-8-sig")

        loaded = load_project_spec(bom_proj_file)
        self.assertEqual(loaded.project.title, "BOM Test Project")

    def test_utf8_bom_support_discover_source_registry(self):
        bom_sources_file = self.target_dir / "sources.json"
        registry = EvidenceSourceRegistry(
            sources=[
                EvidenceSource(
                    id="SRC_001",
                    kind=EvidenceSourceKind.pdf,
                    title="Source with BOM",
                    trust=EvidenceSourceTrust.official,
                    local_file="doc.pdf",
                )
            ]
        )
        bom_sources_file.write_text(json.dumps(registry.model_dump(mode="json")), encoding="utf-8-sig")

        loaded_reg, loaded_path = discover_source_registry(self.target_dir)
        self.assertIsNotNone(loaded_path)
        self.assertEqual(len(loaded_reg.sources), 1)
        self.assertEqual(loaded_reg.sources[0].id, "SRC_001")

    def test_create_editor_package_zip_safety(self):
        export_dir = self.target_dir / "exports" / "test-pkg"
        (export_dir / "scenes").mkdir(parents=True, exist_ok=True)
        (export_dir / "narration").mkdir(parents=True, exist_ok=True)

        (export_dir / "scenes" / "scene_001.mp4").write_bytes(b"scene1")
        (export_dir / "narration" / "narration.mp3").write_bytes(b"audio")
        (export_dir / "edit_manifest.json").write_text('{"schema_version": "1.0"}', encoding="utf-8")

        zip_out = create_editor_package_zip(export_dir)
        self.assertTrue(zip_out.exists())

        with zipfile.ZipFile(zip_out, "r") as zf:
            names = zf.namelist()
            self.assertIn("edit_manifest.json", names)
            self.assertIn("scenes/scene_001.mp4", names)
            self.assertIn("narration/narration.mp3", names)
            for name in names:
                self.assertFalse(name.startswith(".."))
                self.assertFalse(name.startswith("/"))
                self.assertFalse(name.startswith("\\"))

    def test_get_recent_tasks_discovery_and_safety(self):
        tasks_base = self.target_dir / "tasks"
        tasks_base.mkdir(parents=True, exist_ok=True)

        # Valid task
        task_1_id = "11111111-2222-3333-4444-555555555555"
        task_1_dir = tasks_base / task_1_id
        task_1_dir.mkdir()
        manifest_data = {
            "project_title": "Recent Project A",
            "status": "complete",
            "scenes": [
                {"scene_id": "S1", "status": "ready"},
                {"scene_id": "S2", "status": "failed"},
            ],
            "created_at": "2026-08-16T12:00:00Z",
        }
        (task_1_dir / "execution_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        # Corrupted task dir
        task_corrupted = tasks_base / "corrupted-dir"
        task_corrupted.mkdir()
        (task_corrupted / "execution_manifest.json").write_text("NOT_JSON", encoding="utf-8")

        with patch("app.utils.utils.task_dir", return_value=str(tasks_base)):
            tasks = get_recent_tasks(limit=10)
            self.assertTrue(len(tasks) >= 1)
            first = next((t for t in tasks if t["task_id"] == task_1_id), None)
            self.assertIsNotNone(first)
            self.assertEqual(first["title"], "Recent Project A")
            self.assertEqual(first["status"], "complete")
            self.assertEqual(first["total_scenes"], 2)
            self.assertEqual(first["ready_scenes"], 1)
            self.assertEqual(first["failed_scenes"], 1)

    def test_format_fallback_badge(self):
        fb_scene = {
            "scene_id": "S1",
            "fallback_from": "document",
            "resolved_visual_type": "text",
        }
        self.assertEqual(format_fallback_badge(fb_scene), "DOCUMENT → TEXT FALLBACK")

        normal_scene = {"scene_id": "S2", "visual_type": "broll"}
        self.assertIsNone(format_fallback_badge(normal_scene))

    def test_sanitize_manifest_for_display(self):
        raw_manifest = {
            "project_title": "Secret Project",
            "api_key": "sk-1234567890abcdef",
            "auth_token": "bearer xyz",
            "scenes": [
                {
                    "url": "https://api.pexels.com/v1/videos/123?api_key=secretkey123&page=1",
                    "nested": {"client_secret": "sensitive"},
                }
            ],
        }

        sanitized = sanitize_manifest_for_display(raw_manifest)
        self.assertEqual(sanitized["project_title"], "Secret Project")
        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["auth_token"], "[REDACTED]")
        self.assertEqual(sanitized["scenes"][0]["nested"]["client_secret"], "[REDACTED]")
        self.assertIn("api_key=[REDACTED]", sanitized["scenes"][0]["url"])

    def test_check_providers_readiness(self):
        readiness = check_providers_readiness()
        self.assertIn("llm", readiness)
        self.assertIn("tts", readiness)
        self.assertIn("pexels", readiness)
        self.assertIn("pixabay", readiness)
        self.assertIn("coverr", readiness)
        self.assertIn("ffmpeg", readiness)
        self.assertIn("remotion", readiness)
        for key, val in readiness.items():
            self.assertIn("ready", val)
            self.assertIn("label", val)


if __name__ == "__main__":
    unittest.main()
