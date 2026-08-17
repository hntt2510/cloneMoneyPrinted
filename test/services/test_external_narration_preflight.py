import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.project import (
    NarrationMode,
    NarrationSpec,
    ProjectMetadata,
    ProjectSpec,
    ScriptSpec,
    VisualCue,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.external_narration_preflight import (
    TimingQuality,
    preflight_external_narration,
)
from app.services.project_runner import ProjectRunError
from app.services.project_spec import ProjectSpecError, preflight_project, save_project_spec
from app.services.project_timeline_runner import run_timeline_plan


def _create_wav(path: Path, duration_seconds: float, sample_rate: int = 16000) -> Path:
    """Create a minimal valid PCM WAV file of precise duration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_frames = int(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * num_frames)
    return path


class TestExternalNarrationPreflight(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_real_uat_failure_regression(self):
        """Real UAT failure: Audio = 183.3s, 1 cue SRT = 220.538s. Must fail preflight and block planning."""
        audio_path = _create_wav(self.root / "narration.wav", duration_seconds=183.3)
        srt_path = self.root / "narration.srt"
        srt_path.write_text(
            "1\n00:00:00,000 --> 00:03:40,538\n"
            "This is the entire three minute car insurance narration in a single giant subtitle cue.\n",
            encoding="utf-8",
        )

        result = preflight_external_narration(
            audio_path=audio_path,
            srt_path=srt_path,
            script="This is the entire three minute car insurance narration in a single giant subtitle cue.",
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.timing_quality, TimingQuality.INVALID)
        self.assertAlmostEqual(result.audio_duration_seconds, 183.3, places=1)
        self.assertAlmostEqual(result.srt_end_seconds, 220.538, places=2)
        self.assertAlmostEqual(result.duration_delta_seconds, 37.238, places=2)
        
        # Verify specific actionable error message
        combined_errors = "\n".join(result.errors)
        self.assertIn("External narration timing mismatch", combined_errors)
        self.assertIn("Audio duration: 183.30s", combined_errors)
        self.assertIn("SRT final timestamp: 220.54s", combined_errors)
        self.assertIn("Difference: +37.24s", combined_errors)

        # Verify preflight_project blocks this upstream
        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="UAT Fail", language="en-US", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Auto Insurance", script="Car insurance"),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(audio_path), timing_file=str(srt_path)),
        )
        with self.assertRaises(ProjectSpecError) as spec_ctx:
            preflight_project(spec, self.root)
        self.assertIn("External narration preflight failed", str(spec_ctx.exception))

        # Verify run_timeline_plan also defends upstream
        spec_path = save_project_spec(spec, self.root / "project.json")
        with self.assertRaises((ProjectRunError, ProjectSpecError)) as run_ctx:
            run_timeline_plan(str(spec_path))
        self.assertIn("External narration preflight failed", str(run_ctx.exception))

    def test_valid_multi_cue_fixture(self):
        """Valid fixture: 12.0s audio, 4 distributed cues within tolerance, matching script."""
        audio_path = _create_wav(self.root / "narration.wav", duration_seconds=12.0)
        srt_path = self.root / "narration.srt"
        srt_text = (
            "1\n00:00:00,000 --> 00:00:03,000\nYour deductible is one thousand dollars.\n\n"
            "2\n00:00:03,000 --> 00:00:06,000\nRepair costs total six thousand dollars.\n\n"
            "3\n00:00:06,000 --> 00:00:09,000\nInsurance covers the remaining five thousand.\n\n"
            "4\n00:00:09,000 --> 00:00:12,000\nReview your collision policy today.\n"
        )
        srt_path.write_text(srt_text, encoding="utf-8")

        result = preflight_external_narration(
            audio_path=audio_path,
            srt_path=srt_path,
            script="Your deductible is one thousand dollars. Repair costs total six thousand dollars. Insurance covers the remaining five thousand. Review your collision policy today.",
        )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.timing_quality, TimingQuality.GOOD)
        self.assertEqual(result.cue_count, 4)
        self.assertEqual(result.duration_delta_seconds, 0.0)
        self.assertEqual(len(result.errors), 0)
        self.assertIsNotNone(result.text_alignment_confidence)
        self.assertGreaterEqual(result.text_alignment_confidence, 0.20)

    def test_coarse_srt_regression(self):
        """Coarse SRT: 180s audio with only 1 cue spanning 180s. Duration matches, but granularity is COARSE -> invalid for kinetic sync."""
        audio_path = _create_wav(self.root / "audio_long.wav", duration_seconds=180.0)
        srt_path = self.root / "coarse.srt"
        srt_path.write_text(
            "1\n00:00:00,000 --> 00:03:00,000\n"
            "A long three minute narration placed into a single cue.\n",
            encoding="utf-8",
        )

        result = preflight_external_narration(
            audio_path=audio_path,
            srt_path=srt_path,
            script="A long three minute narration placed into a single cue.",
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.timing_quality, TimingQuality.COARSE)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("SRT timing is too coarse for synchronized production: 1 cue covers 180.0 seconds", result.errors[0])
        self.assertIn("Please provide a subtitle SRT with sentence/phrase-level timestamps", result.errors[0])

    def test_large_srt_underrun(self):
        """Large underrun: Audio = 183.0s, SRT ends at 140.0s (43s uncovered). Must fail with underrun error."""
        audio_path = _create_wav(self.root / "audio_underrun.wav", duration_seconds=183.0)
        srt_path = self.root / "underrun.srt"
        srt_text = (
            "1\n00:00:00,000 --> 00:01:10,000\nFirst part of narration.\n\n"
            "2\n00:01:10,000 --> 00:02:20,000\nSecond part of narration ending early.\n"
        )
        srt_path.write_text(srt_text, encoding="utf-8")

        result = preflight_external_narration(
            audio_path=audio_path,
            srt_path=srt_path,
        )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.timing_quality, TimingQuality.INVALID)
        combined_errors = "\n".join(result.errors)
        self.assertIn("External narration timing underrun", combined_errors)
        self.assertIn("43.00s of audio is uncovered by subtitles", combined_errors)

    def test_boundary_tolerance_cases(self):
        """Test delta tolerance boundaries (-0.2s PASS, +0.2s PASS, +1.0s FAIL)."""
        audio_path = _create_wav(self.root / "audio_10s.wav", duration_seconds=10.0)

        # 1. Ends 0.2s early (9.8s) -> PASS
        srt_early = self.root / "early.srt"
        srt_early.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\nCue 1\n\n"
            "2\n00:00:05,000 --> 00:00:09,800\nCue 2\n",
            encoding="utf-8",
        )
        res_early = preflight_external_narration(audio_path, srt_early, tolerance_seconds=0.5)
        self.assertTrue(res_early.is_valid)

        # 2. Ends 0.2s late (10.2s) -> PASS
        srt_late_ok = self.root / "late_ok.srt"
        srt_late_ok.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\nCue 1\n\n"
            "2\n00:00:05,000 --> 00:00:10,200\nCue 2\n",
            encoding="utf-8",
        )
        res_late_ok = preflight_external_narration(audio_path, srt_late_ok, tolerance_seconds=0.5)
        self.assertTrue(res_late_ok.is_valid)

        # 3. Ends 1.0s late (11.0s) -> FAIL
        srt_late_fail = self.root / "late_fail.srt"
        srt_late_fail.write_text(
            "1\n00:00:00,000 --> 00:00:05,000\nCue 1\n\n"
            "2\n00:00:05,000 --> 00:00:11,000\nCue 2\n",
            encoding="utf-8",
        )
        res_late_fail = preflight_external_narration(audio_path, srt_late_fail, tolerance_seconds=0.5)
        self.assertFalse(res_late_fail.is_valid)

    def test_cue_bounds_and_overlaps(self):
        """Invalid time intervals, overlaps, and cue starts beyond audio duration fail preflight."""
        audio_path = _create_wav(self.root / "audio_5s.wav", duration_seconds=5.0)

        # Overlapping cues
        srt_overlap = self.root / "overlap.srt"
        srt_overlap.write_text(
            "1\n00:00:00,000 --> 00:00:03,000\nCue 1\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nCue 2\n",
            encoding="utf-8",
        )
        self.assertFalse(preflight_external_narration(audio_path, srt_overlap).is_valid)

        # Cue start beyond audio
        srt_beyond = self.root / "beyond.srt"
        srt_beyond.write_text(
            "1\n00:00:06,000 --> 00:00:08,000\nCue starts at 6s for 5s audio\n",
            encoding="utf-8",
        )
        self.assertFalse(preflight_external_narration(audio_path, srt_beyond).is_valid)

    def test_utf8_bom_and_crlf_handling(self):
        """UTF-8 BOM and Windows CRLF formatting pass smoothly."""
        audio_path = _create_wav(self.root / "audio_6s.wav", duration_seconds=6.0)
        srt_bom = self.root / "bom.srt"
        srt_content = (
            "\ufeff1\r\n00:00:00,000 --> 00:00:03,000\r\nHello with BOM\r\n\r\n"
            "2\r\n00:00:03,000 --> 00:00:06,000\r\nWorld with CRLF\r\n"
        )
        srt_bom.write_bytes(srt_content.encode("utf-8-sig"))

        result = preflight_external_narration(audio_path, srt_bom)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.cue_count, 2)

    def test_text_pass_temporal_fail_separation(self):
        """When text alignment is 100% PASS but temporal duration is mismatch, overall result is FAIL."""
        script_text = "Car insurance deductible is one thousand dollars. Repair costs six thousand dollars."
        audio_path = _create_wav(self.root / "audio_5s.wav", duration_seconds=5.0)
        srt_path = self.root / "mismatch.srt"
        # Exact text, but timestamps are 15s instead of 5s
        srt_path.write_text(
            "1\n00:00:00,000 --> 00:00:07,500\nCar insurance deductible is one thousand dollars.\n\n"
            "2\n00:00:07,500 --> 00:00:15,000\nRepair costs six thousand dollars.\n",
            encoding="utf-8",
        )

        result = preflight_external_narration(
            audio_path=audio_path,
            srt_path=srt_path,
            script=script_text,
        )

        self.assertFalse(result.is_valid)
        self.assertIn("External narration timing mismatch", "\n".join(result.errors))


if __name__ == "__main__":
    unittest.main()
