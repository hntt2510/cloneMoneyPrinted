import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.project import NarrationMode, ProjectSpec
from app.services.external_narration_preflight import ExternalNarrationPreflightResult, TimingQuality
from app.services.project_builder import build_project_spec_from_ui
from webui.production import render_production_workspace, resolve_task_project_path, save_uploaded_file


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

    @patch("webui.production.run_production_workflow")
    @patch("webui.production.st")
    def test_ui_start_gate_blocks_temporally_invalid_external_narration(self, mock_st, mock_run_workflow):
        """When External Audio + SRT is selected and preflight is invalid, start is blocked (zero workflow runs)."""
        mock_st.session_state = {
            "external_narration_preflight": ExternalNarrationPreflightResult(
                audio_duration_seconds=183.3,
                srt_end_seconds=220.5,
                duration_delta_seconds=37.2,
                timing_quality=TimingQuality.INVALID,
                errors=["External narration timing mismatch: Audio duration: 183.30s, SRT final timestamp: 220.54s"],
                is_valid=False,
            ),
            "narration_audio_path": "/path/to/narration.wav",
            "narration_srt_path": "/path/to/narration.srt",
        }

        # Radio returns External Audio + SRT
        def radio_side_effect(label, options, *args, **kwargs):
            if "Configuration" in label:
                return "Mode A: Form Builder (Interactive)"
            if "Target Production" in label:
                return "Final Video (G08 → G09 → G10 Assembly)"
            if "Narration Source" in label:
                return "External Audio + SRT"
            return options[0]

        mock_st.radio.side_effect = radio_side_effect
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.button.return_value = True  # Click Start Production
        mock_st.selectbox.return_value = "16:9"
        mock_st.number_input.return_value = 30
        mock_st.text_input.return_value = "Test Title"
        mock_st.text_area.return_value = "Test Subject"
        mock_st.checkbox.return_value = True
        mock_st.file_uploader.return_value = None

        render_production_workspace()

        # Workflow runner must NOT be called
        self.assertEqual(mock_run_workflow.call_count, 0)
        # Error must be shown
        error_calls = [c[0][0] for c in mock_st.error.call_args_list]
        self.assertTrue(any("Cannot start production" in str(e) for e in error_calls))

    @patch("webui.production.run_production_workflow")
    @patch("webui.production.st")
    def test_ui_start_gate_blocks_coarse_srt(self, mock_st, mock_run_workflow):
        """When External Audio + SRT has coarse single-cue timing, start is blocked."""
        mock_st.session_state = {
            "external_narration_preflight": ExternalNarrationPreflightResult(
                audio_duration_seconds=180.0,
                srt_end_seconds=180.0,
                duration_delta_seconds=0.0,
                cue_count=1,
                timing_quality=TimingQuality.COARSE,
                errors=["SRT timing is too coarse for synchronized production: 1 cue covers 180.0 seconds."],
                is_valid=False,
            ),
            "narration_audio_path": "/path/to/narration.wav",
            "narration_srt_path": "/path/to/coarse.srt",
        }

        def radio_side_effect(label, options, *args, **kwargs):
            if "Configuration" in label:
                return "Mode A: Form Builder (Interactive)"
            if "Target Production" in label:
                return "Final Video (G08 → G09 → G10 Assembly)"
            if "Narration Source" in label:
                return "External Audio + SRT"
            return options[0]

        mock_st.radio.side_effect = radio_side_effect
        mock_st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
        mock_st.button.return_value = True
        mock_st.selectbox.return_value = "16:9"
        mock_st.number_input.return_value = 30
        mock_st.text_input.return_value = "Test Title"
        mock_st.text_area.return_value = "Test Subject"
        mock_st.checkbox.return_value = True
        mock_st.file_uploader.return_value = None

        render_production_workspace()

        self.assertEqual(mock_run_workflow.call_count, 0)
        error_calls = [c[0][0] for c in mock_st.error.call_args_list]
        self.assertTrue(any("Cannot start production" in str(e) for e in error_calls))


if __name__ == "__main__":
    unittest.main()
