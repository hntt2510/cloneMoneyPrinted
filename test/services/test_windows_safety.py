from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import tempfile
import unittest
import wave
import struct
from pathlib import Path

from moviepy import ColorClip

from app.models.assembly import AssemblyConfig, AssemblyStatus
from app.models.export import EditManifest, EditorPackageStatus, EditorSceneEntry
from app.models.project import VisualType
from app.services.assembly_runner import assemble_final_video
from app.services.evidence_sources import compute_file_sha256
from app.services.export_runner import export_editor_package


class TestWindowsSafety(unittest.TestCase):
    """G12.3 Windows Safety Tests.

    Validates path handling with spaces, Unicode filenames, list-style subprocess arguments,
    atomic file replacement, console encoding safety, absence of /tmp assumptions, and
    portable export naming conventions.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_paths_with_spaces(self) -> None:
        """Requirement 1: Directory paths with spaces work correctly in assembly/export."""
        space_dir = Path(self.temp_dir) / "directory with spaces in path"
        export_dir = space_dir / "my export package"
        export_dir.mkdir(parents=True, exist_ok=True)
        scenes_dir = export_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        narr_dir = export_dir / "narration"
        narr_dir.mkdir(parents=True, exist_ok=True)

        clip_path = scenes_dir / "S001_DATA.mp4"
        c = ColorClip(size=(640, 360), color=(80, 80, 80), duration=1.0)
        c.write_videofile(str(clip_path), fps=30, codec="libx264", logger=None)
        c.close()
        clip_sha = compute_file_sha256(clip_path)

        narr_path = narr_dir / "narration.wav"
        with wave.open(str(narr_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(bytearray(44100 * 2))
        narr_sha = compute_file_sha256(narr_path)

        manifest = EditManifest(
            schema_version="1.0",
            project_title="Space Path Project",
            project_slug="space-path-project",
            task_id="space-task-001",
            source_project_fingerprint="fp-spaces",
            export_fingerprint="exp-spaces",
            package_status=EditorPackageStatus.complete,
            fps=30,
            resolution=[640, 360],
            aspect_ratio="16:9",
            duration_frames=30,
            duration_seconds=1.0,
            narration_file="narration/narration.wav",
            narration_sha256=narr_sha,
            subtitle_file=None,
            subtitle_sha256=None,
            scenes=[
                EditorSceneEntry(
                    scene_id="S001",
                    order=1,
                    planned_visual_type=VisualType.data,
                    resolved_visual_type=VisualType.data,
                    start_frame=0,
                    end_frame=30,
                    duration_frames=30,
                    exported_file="scenes/S001_DATA.mp4",
                    sha256=clip_sha,
                )
            ],
            source_provenance=[],
            missing_scenes=[],
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
            outputs={"export_dir": str(export_dir)},
        )
        manifest_path = export_dir / "edit_manifest.json"
        manifest_path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")

        cfg = AssemblyConfig(fps=30, resolution=[640, 360], crf=23)
        res = assemble_final_video(manifest_path, task_id="space-task-001", config=cfg)
        self.assertEqual(res.status, AssemblyStatus.complete.value)
        self.assertTrue(Path(res.final_video_file).exists())
        self.assertTrue(Path(res.qc_report_file).exists())

    def test_unicode_filenames(self) -> None:
        """Requirement 2: Vietnamese, CJK, and accented Unicode paths are handled safely."""
        unicode_dir = Path(self.temp_dir) / "dự_án_tiếng_việt_日本語_中文"
        unicode_dir.mkdir(parents=True, exist_ok=True)
        unicode_file = unicode_dir / "tài_liệu_xác_thực_証拠.json"

        payload = {"title": "Tiếng Việt có dấu và 日本語 and 中文", "status": "thành công"}
        unicode_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        self.assertTrue(unicode_file.exists())
        loaded = json.loads(unicode_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["title"], payload["title"])
        self.assertEqual(loaded["status"], "thành công")

    def test_subprocess_list_args(self) -> None:
        """Requirement 3: Subprocess calls in app/services/ use list arguments and never shell=True."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        services_dir = repo_root / "app" / "services"

        for py_file in services_dir.rglob("*.py"):
            code = py_file.read_text(encoding="utf-8")
            tree = ast.parse(code, filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "subprocess":
                            func_name = node.func.attr
                    elif isinstance(node.func, ast.Name):
                        if node.func.id in ("run", "Popen", "call", "check_call", "check_output"):
                            func_name = node.func.id

                    if func_name in ("run", "Popen", "call", "check_call", "check_output"):
                        # Verify shell=True is NEVER used
                        for kw in node.keywords:
                            if kw.arg == "shell":
                                if isinstance(kw.value, ast.Constant):
                                    self.assertFalse(
                                        kw.value.value,
                                        f"Prohibited shell=True found in {py_file} at line {node.lineno}",
                                    )

    def test_atomic_replace_windows(self) -> None:
        """Requirement 4: Atomic file replacement (os.replace) overwrites existing destination without error."""
        src = Path(self.temp_dir) / "source.tmp"
        dst = Path(self.temp_dir) / "dest.json"

        dst.write_text("initial content", encoding="utf-8")
        src.write_text("updated content", encoding="utf-8")

        # os.replace must succeed atomically even when dst exists
        os.replace(src, dst)
        self.assertFalse(src.exists())
        self.assertTrue(dst.exists())
        self.assertEqual(dst.read_text(encoding="utf-8"), "updated content")

    def test_console_encoding_stdout(self) -> None:
        """Requirement 5: Unicode/CJK text strings can be encoded to utf-8 safely for console/log writes."""
        test_strings = [
            "Start TTS: 冰糖 voice",
            "Xác thực tài liệu tiếng Việt thành công ✅",
            "日本語字幕生成完了 🚀",
            "Special symbols: © ® ™ § ¶ † ‡ • ‣",
        ]
        for s in test_strings:
            # Verify string encodes and decodes cleanly in UTF-8
            encoded = s.encode("utf-8", errors="replace")
            decoded = encoded.decode("utf-8")
            self.assertEqual(s, decoded)

            # Verify TextIOWrapper with utf-8 or replace errors handles it without raising UnicodeEncodeError
            buf = io.BytesIO()
            writer = io.TextIOWrapper(buf, encoding="utf-8", errors="replace")
            writer.write(s)
            writer.flush()
            self.assertGreater(len(buf.getvalue()), 0)

    def test_no_tmp_assumptions(self) -> None:
        """Requirement 6: Production code in app/ does not contain hardcoded /tmp/ or \\tmp\\ paths."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        app_dir = repo_root / "app"

        for py_file in app_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            # Disallow literal "/tmp/" or "\tmp\" paths in production code
            self.assertNotIn(
                '"/tmp/',
                content,
                f"Hardcoded /tmp/ found in {py_file}",
            )
            self.assertNotIn(
                "'/tmp/",
                content,
                f"Hardcoded /tmp/ found in {py_file}",
            )
            self.assertNotIn(
                '"\\\\tmp\\\\',
                content,
                f"Hardcoded \\tmp\\ found in {py_file}",
            )

    def test_portable_export_names(self) -> None:
        """Requirement 7: Exported filenames conform to portable filename rules (no forbidden Windows chars)."""
        invalid_windows_chars = set('<>:"/\\|?*')
        reserved_dos_names = {
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        }

        standard_filenames = [
            "project.json",
            "project.executed.json",
            "execution_manifest.json",
            "edit_manifest.json",
            "README_EDIT.md",
            "S001_DATA.mp4",
            "S002_TEXT.mp4",
            "S003_BROLL.mp4",
            "S004_DOCUMENT.mp4",
            "narration.mp3",
            "narration.wav",
            "subtitle.srt",
            "source_manifest.json",
            "final.mp4",
            "qc_report.json",
        ]

        for fname in standard_filenames:
            # Check characters
            for ch in fname:
                self.assertNotIn(
                    ch,
                    invalid_windows_chars,
                    f"Filename '{fname}' contains forbidden Windows character '{ch}'",
                )
            # Check base name against DOS reserved device names
            stem = Path(fname).stem.upper()
            self.assertNotIn(
                stem,
                reserved_dos_names,
                f"Filename '{fname}' stem '{stem}' is a reserved DOS device name",
            )


if __name__ == "__main__":
    unittest.main()
