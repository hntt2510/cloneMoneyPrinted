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
from app.services.motion_normalizer import normalize_motion_spec
from app.services.project_runner import ProjectRunError
from app.services.project_spec import save_project_spec
from app.services.project_timeline_runner import run_timeline_plan
from app.services.timeline import (
    SrtCue,
    TimelineError,
    acquire_timing_file,
    build_timeline_cues,
    parse_srt_text,
    validate_script_srt_alignment,
)
from app.services import voice


def _create_dummy_wav(path: Path, duration_seconds: float = 3.0, sample_rate: int = 16000) -> Path:
    """Create a minimal valid PCM WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_frames = int(duration_seconds * sample_rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * num_frames)
    return path


CAR_INSURANCE_SRT = """1
00:00:00,000 --> 00:00:01,500
Your collision deductible is one thousand dollars.

2
00:00:01,500 --> 00:00:03,000
Repair costs six thousand dollars.
"""

COOKING_SRT = """1
00:00:00,000 --> 00:00:01,500
Add two cups of flour and cocoa powder.

2
00:00:01,500 --> 00:00:03,000
Bake the chocolate cake in the oven at 350 degrees.
"""


class TestG15ExternalNarration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_zero_tts_calls_in_external_mode(self):
        """When narration mode is 'file' with external audio + SRT, zero TTS calls must be made."""
        audio_path = _create_dummy_wav(self.root / "audio.wav", duration_seconds=3.0)
        srt_path = self.root / "timing.srt"
        srt_path.write_text(CAR_INSURANCE_SRT, encoding="utf-8")

        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Insurance Explainer", language="en-US", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Auto Insurance", script="Your collision deductible is one thousand dollars. Repair costs six thousand dollars."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(audio_path), timing_file=str(srt_path)),
        )
        spec_path = save_project_spec(spec, self.root / "project.json")

        with patch("app.services.voice.tts") as mock_tts, \
             patch("app.services.task.generate_audio") as mock_gen_audio, \
             patch("app.services.task.generate_script") as mock_gen_script:
            
            result = run_timeline_plan(str(spec_path))
            
            self.assertEqual(mock_tts.call_count, 0)
            self.assertEqual(mock_gen_audio.call_count, 0)
            self.assertEqual(mock_gen_script.call_count, 0)
            self.assertEqual(result["manifest"]["outputs"]["timing_source"], "user_srt")

    def test_user_srt_source_propagated_to_motion(self):
        """Timing source 'user_srt' must propagate cleanly to Planned Project and MotionSceneSpec."""
        audio_path = _create_dummy_wav(self.root / "audio.wav", duration_seconds=3.0)
        srt_path = self.root / "timing.srt"
        srt_path.write_text(CAR_INSURANCE_SRT, encoding="utf-8")

        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Insurance Explainer", language="en-US", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Auto Insurance", script="Your collision deductible is one thousand dollars. Repair costs six thousand dollars."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(audio_path), timing_file=str(srt_path)),
        )
        spec_path = save_project_spec(spec, self.root / "project.json")

        result = run_timeline_plan(str(spec_path))
        planned_proj_path = Path(result["planned_project_file"])
        planned_data = json.loads(planned_proj_path.read_text(encoding="utf-8"))
        
        self.assertEqual(planned_data.get("timing_source"), "user_srt")

        # Test MotionSceneSpec normalization receives user_srt
        planned_spec = ProjectSpec.model_validate(planned_data)
        cue = VisualCue(id="S001", order=1, start=0.0, end=1.5, narration="Your collision deductible is one thousand dollars.", visual_type=VisualType.data, purpose="explain", payload={"template": "number", "headline": "Deductible", "data": {"value": "$1,000"}})
        motion_spec = normalize_motion_spec(cue, planned_spec)

        self.assertIsNotNone(motion_spec.animation_plan)
        self.assertEqual(motion_spec.animation_plan.timing_source, "user_srt")
        self.assertEqual(motion_spec.animation_plan.kinetic_timing_source, "user_srt_cue_exact+intra_cue_estimated")

    def test_gross_mismatch_fails_alignment_validation(self):
        """Gross mismatch between script (car insurance) and SRT (cooking) must raise TimelineError."""
        cues = parse_srt_text(COOKING_SRT)
        script = "Car insurance collision coverage policy deductible liability limits and comprehensive auto claims."

        with self.assertRaises(TimelineError) as ctx:
            validate_script_srt_alignment(cues, script)

        self.assertIn("Uploaded SRT narration does not sufficiently match the configured script", str(ctx.exception))

    def test_minor_mismatch_passes_alignment_validation(self):
        """Minor differences (punctuation, capitalization, contractions) must pass alignment validation."""
        cues = parse_srt_text(CAR_INSURANCE_SRT)
        script = "YOUR COLLISION DEDUCTIBLE IS $1,000! REPAIR COSTS $6,000..."

        confidence = validate_script_srt_alignment(cues, script)
        self.assertGreaterEqual(confidence, 0.20)

    def test_script_blank_derives_script_from_user_srt(self):
        """When script is blank in External Audio + SRT mode, canonical script is derived from SRT cues."""
        audio_path = _create_dummy_wav(self.root / "audio.wav", duration_seconds=3.0)
        srt_path = self.root / "timing.srt"
        srt_path.write_text(CAR_INSURANCE_SRT, encoding="utf-8")

        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Insurance Explainer", language="en-US", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Auto Insurance", script=""),  # blank script
            narration=NarrationSpec(mode=NarrationMode.file, file=str(audio_path), timing_file=str(srt_path)),
        )
        spec_path = save_project_spec(spec, self.root / "project.json")

        with patch("app.services.task.generate_script") as mock_gen_script:
            result = run_timeline_plan(str(spec_path))
            self.assertEqual(mock_gen_script.call_count, 0)
            
            planned_proj = json.loads(Path(result["planned_project_file"]).read_text(encoding="utf-8"))
            derived_script = planned_proj["script"]["script"]
            self.assertIn("collision deductible", derived_script.lower())
            self.assertIn("six thousand dollars", derived_script.lower())

    def test_malformed_user_srt_fails_hard_without_whisper(self):
        """A malformed supplied SRT (overlapping cues, broken timestamps) must fail hard without silent Whisper fallback."""
        bad_srt = self.root / "bad.srt"
        bad_srt.write_text("1\n00:00:02,000 --> 00:00:01,000\nBroken timestamps\n", encoding="utf-8")
        audio_path = _create_dummy_wav(self.root / "audio.wav", duration_seconds=3.0)

        with self.assertRaises(TimelineError):
            acquire_timing_file(
                source_timing_file=str(bad_srt),
                task_directory=self.root,
                audio_file=str(audio_path),
                script="Some script text",
                duration=3.0,
            )

    def test_external_narration_missing_audio_raises_error(self):
        """Missing external audio file raises actionable ProjectRunError."""
        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Test", language="en-US", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Test", script="Hello world"),
            narration=NarrationSpec(mode=NarrationMode.file, file="non_existent.wav"),
        )
        spec_path = save_project_spec(spec, self.root / "project.json")

        with self.assertRaises(Exception):
            run_timeline_plan(str(spec_path))


if __name__ == "__main__":
    unittest.main()
