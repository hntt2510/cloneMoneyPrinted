import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.project import NarrationMode, ProjectSpec
from app.services.project_builder import build_project_spec_from_ui
from webui.production import resolve_task_project_path, save_uploaded_file


class DummyUploadedFile:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getbuffer(self) -> bytes:
        return self._content

    def read(self) -> bytes:
        return self._content


class TestG15ExternalNarrationUI(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_build_spec_with_external_audio_and_srt(self):
        """build_project_spec_from_ui attaches both custom_audio_file and custom_timing_file."""
        spec = build_project_spec_from_ui(
            title="External Test",
            subject="External Voice Production",
            script="",
            narration_mode="file",
            custom_audio_file="/path/to/narration.wav",
            custom_timing_file="/path/to/narration.srt",
        )
        self.assertEqual(spec.narration.mode, NarrationMode.file)
        self.assertEqual(spec.narration.file, "/path/to/narration.wav")
        self.assertEqual(spec.narration.timing_file, "/path/to/narration.srt")

    def test_save_uploaded_srt_and_wav_files_safely(self):
        """Uploaded WAV and SRT files are safely saved inside target directory with traversal protection."""
        audio_file = DummyUploadedFile("../../narration.wav", b"RIFF dummy audio data")
        srt_file = DummyUploadedFile("..\\timing.srt", b"1\n00:00:00,000 --> 00:00:02,000\nHello\n")

        saved_audio = save_uploaded_file(audio_file, self.target_dir, allowed_extensions={".wav", ".mp3"})
        saved_srt = save_uploaded_file(srt_file, self.target_dir, allowed_extensions={".srt"})

        self.assertTrue(saved_audio.exists())
        self.assertEqual(saved_audio.name, "narration.wav")
        self.assertEqual(saved_audio.parent, self.target_dir.resolve())

        self.assertTrue(saved_srt.exists())
        self.assertEqual(saved_srt.name, "timing.srt")
        self.assertEqual(saved_srt.parent, self.target_dir.resolve())

    def test_mode_c_restore_persists_external_narration(self):
        """Mode C task loader correctly resolves and preserves external narration settings."""
        task_id = "test-task-12345678"
        task_dir = self.target_dir / task_id
        task_dir.mkdir(parents=True)

        spec = build_project_spec_from_ui(
            title="Restored Project",
            subject="Restored Subject",
            script="Hello world",
            narration_mode="file",
            custom_audio_file="audio.wav",
            custom_timing_file="timing.srt",
        )
        (task_dir / "project.json").write_text(
            json.dumps(spec.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        with patch("webui.production._get_allowed_storage_roots", return_value=[self.target_dir.resolve()]), \
             patch("app.utils.utils.task_dir", return_value=str(task_dir)):
            
            resolved_p, err = resolve_task_project_path(task_id)
            self.assertIsNone(err)
            self.assertIsNotNone(resolved_p)
            
            from app.services.project_spec import load_project_spec
            loaded_spec = load_project_spec(resolved_p)
            self.assertEqual(loaded_spec.narration.mode, NarrationMode.file)
            self.assertEqual(loaded_spec.narration.file, "audio.wav")
            self.assertEqual(loaded_spec.narration.timing_file, "timing.srt")


if __name__ == "__main__":
    unittest.main()
