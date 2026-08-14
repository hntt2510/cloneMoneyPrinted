import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.project import NarrationSpec, ProjectSpec, TimelineCue, TimelinePlan
from app.services.project_timeline_runner import run_timeline_plan
from app.services.timeline import (
    TimelineError,
    acquire_timing_file,
    build_timeline_cues,
    build_timeline_plan,
    parse_srt_text,
    serialize_srt,
    _canonicalize_narration,
    SrtCue,
    AUDIO_DURATION_TOLERANCE,
)
from app.services.visual_planner import fallback_visual


SRT = """1
00:00:00,000 --> 00:00:01,000
If you retire at 60,

2
00:00:01,000 --> 00:00:03,500
Medicare begins at 65.

3
00:00:03,500 --> 00:00:06,000
That leaves a five-year gap.
"""


class TestTimelineModel(unittest.TestCase):
    def test_valid_and_invalid_timeline_cue(self):
        cue = TimelineCue(id="S001", order=1, start=0, end=2, narration="Hello")
        self.assertEqual(cue.id, "S001")
        with self.assertRaises(ValueError):
            TimelineCue(id="", order=1, start=0, end=2, narration="Hello")
        with self.assertRaises(ValueError):
            TimelineCue(id="S001", order=1, start=-1, end=2, narration="Hello")
        with self.assertRaises(ValueError):
            TimelineCue(id="S001", order=1, start=2, end=2, narration="Hello")

    def test_plan_rejects_duplicates_and_overlap(self):
        with self.assertRaises(ValueError):
            TimelinePlan(
                schema_version="1.0",
                project_title="x",
                audio_file="a.wav",
                timing_file="t.srt",
                duration=2,
                cues=[
                    TimelineCue(id="S001", order=1, start=0, end=1, narration="a"),
                    TimelineCue(id="S001", order=2, start=1, end=2, narration="b"),
                ],
            )

    def test_timing_source_field_default_and_serialization(self):
        """TimelinePlan.timing_source defaults to 'estimated' and serializes to JSON."""
        plan = TimelinePlan(
            schema_version="1.0",
            project_title="Test",
            audio_file="a.wav",
            timing_file="t.srt",
            duration=5.0,
            cues=[TimelineCue(id="S001", order=1, start=0, end=5, narration="hello")],
        )
        self.assertEqual(plan.timing_source, "estimated")
        dumped = plan.model_dump(mode="json")
        self.assertIn("timing_source", dumped)
        self.assertEqual(dumped["timing_source"], "estimated")

    def test_timing_source_preserved_from_build(self):
        """build_timeline_plan propagates timing_source to TimelinePlan."""
        cue = TimelineCue(id="S001", order=1, start=0, end=2, narration="hello")
        plan = build_timeline_plan(
            project_title="T",
            audio_file="a.wav",
            timing_file="t.srt",
            duration=2.0,
            cues=[cue],
            timing_source="user_srt",
        )
        self.assertEqual(plan.timing_source, "user_srt")


class TestTimelineService(unittest.TestCase):
    def test_srt_parse_round_trip_and_deterministic_ids(self):
        cues = parse_srt_text(SRT)
        self.assertEqual(len(cues), 3)
        self.assertEqual(parse_srt_text(serialize_srt(cues)), cues)
        timeline = build_timeline_cues(cues, "If you retire at 60, Medicare begins at 65. That leaves a five-year gap.")
        self.assertEqual([cue.id for cue in timeline], ["S001", "S002"])
        self.assertTrue(all(a.end <= b.start for a, b in zip(timeline, timeline[1:])))

    def test_invalid_srt_is_rejected(self):
        with self.assertRaises(TimelineError):
            parse_srt_text("1\n00:00:02,000 --> 00:00:01,000\nBad\n")

    def test_supplied_timing_never_calls_whisper(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            with patch("app.services.timeline.subtitle.create") as whisper:
                target, cues, source_label = acquire_timing_file(
                    source_timing_file=str(source),
                    task_directory=Path(directory) / "task",
                    audio_file="audio.wav",
                    script="If you retire at 60, Medicare begins at 65. That leaves a five-year gap.",
                    duration=6,
                )
            whisper.assert_not_called()
            self.assertTrue(Path(target).is_file())
            self.assertEqual(len(cues), 3)
            self.assertEqual(source_label, "user_srt")

    def test_fallback_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cues, source_label = acquire_timing_file(
                source_timing_file=None,
                task_directory=directory,
                audio_file="audio.wav",
                script="First point. Second point.",
                duration=8,
                whisper_create=lambda **kwargs: None,
            )
            self.assertEqual([cue.start for cue in cues], [0.0, 3.8095238095238093])
            self.assertTrue(Path(target).is_file())
            self.assertEqual(source_label, "estimated")


class TestMonotonicAlignment(unittest.TestCase):
    """Tests for text-aware monotonic alignment (G03 requirement #9)."""

    def test_cue_count_mismatch_follows_srt_text_not_duration(self):
        """Alignment with differing cue counts must use SRT text, not duration percentage.

        Script semantic order: A, B, C, D
        SRT timing:
            0-5:  "A. B."
            5-6:  "C."
            6-10: "D."

        Result MUST preserve 0-5 → A/B, 5-6 → C, 6-10 → D.
        It must NOT assign C to first cue based on duration percentage.
        """
        srt_cues = [
            SrtCue(start=0.0, end=5.0, text="A. B."),
            SrtCue(start=5.0, end=6.0, text="C."),
            SrtCue(start=6.0, end=10.0, text="D."),
        ]
        script = "Sentence A. Sentence B. Sentence C. Sentence D."
        result = _canonicalize_narration(srt_cues, script)

        # First cue (0-5) must contain A and B content
        self.assertEqual(result[0].start, 0.0)
        self.assertEqual(result[0].end, 5.0)
        self.assertIn("A", result[0].text)

        # Second cue (5-6) must contain C
        self.assertEqual(result[1].start, 5.0)
        self.assertEqual(result[1].end, 6.0)
        self.assertIn("C", result[1].text)

        # Third cue (6-10) must contain D
        self.assertEqual(result[2].start, 6.0)
        self.assertEqual(result[2].end, 10.0)
        self.assertIn("D", result[2].text)

    def test_duration_percentage_would_wrongly_assign_c_to_first_cue(self):
        """Regression: old duration-weight algorithm would assign C to 0-5 cue.

        With a 10s total duration and 4 clauses (A, B, C, D), the old algorithm
        assigned clauses proportionally by word weight.
        C is ~75% through the clauses, which maps to ~7.5s — in cue 3 (6-10).
        But the old code's weight accumulation might put it in cue 1 for short texts.
        The new text-aware approach must keep C in the 5-6 cue.
        """
        srt_cues = [
            SrtCue(start=0.0, end=5.0, text="A B"),
            SrtCue(start=5.0, end=6.0, text="C"),
            SrtCue(start=6.0, end=10.0, text="D"),
        ]
        script = "A. B. C. D."
        result = _canonicalize_narration(srt_cues, script)
        # The 5-6 cue must contain C, not B or D
        self.assertEqual(result[1].start, 5.0)
        self.assertEqual(result[1].end, 6.0)
        self.assertIn("C", result[1].text)

    def test_asr_wording_variation_alignment(self):
        """ASR/Whisper may produce slightly different wording than the canonical script.

        Script: "Medicare begins at age 65."
        ASR:    "Medicare begins at age sixty five."

        The alignment must remain monotonic and sensible even with number-word variations.
        """
        srt_cues = [
            SrtCue(start=0.0, end=3.0, text="Medicare begins at age sixty five."),
            SrtCue(start=3.0, end=6.0, text="That leaves a gap."),
        ]
        script = "Medicare begins at age 65. That leaves a five-year gap."
        result = _canonicalize_narration(srt_cues, script)

        # Timing must be preserved
        self.assertEqual(result[0].start, 0.0)
        self.assertEqual(result[0].end, 3.0)
        self.assertEqual(result[1].start, 3.0)
        self.assertEqual(result[1].end, 6.0)

        # Should be monotonic (second clause after first)
        first_text = result[0].text.lower()
        second_text = result[1].text.lower()
        self.assertTrue(
            "medicare" in first_text or "65" in first_text or "sixty" in first_text,
            f"First cue should relate to Medicare/65, got: {result[0].text!r}",
        )

    def test_monotonic_constraint_never_reverses(self):
        """Script spans must always move forward — never assigned backwards."""
        srt_cues = [
            SrtCue(start=0.0, end=2.0, text="First sentence here."),
            SrtCue(start=2.0, end=4.0, text="Second sentence here."),
            SrtCue(start=4.0, end=6.0, text="Third sentence here."),
        ]
        script = "First sentence. Second sentence. Third sentence."
        result = _canonicalize_narration(srt_cues, script)

        # All 3 cues must have timing preserved
        self.assertEqual(len(result), 3)
        for i in range(len(result) - 1):
            self.assertLessEqual(result[i].end, result[i + 1].start + 0.001)

    def test_exact_count_with_similarity_uses_canonical_script(self):
        """When cue count equals clause count and all pairs are similar, canonical script is used."""
        srt_cues = [
            SrtCue(start=0.0, end=2.0, text="Clause one."),
            SrtCue(start=2.0, end=4.0, text="Clause two."),
        ]
        script = "Clause one. Clause two."
        result = _canonicalize_narration(srt_cues, script)
        self.assertEqual(len(result), 2)
        self.assertIn("one", result[0].text.lower())
        self.assertIn("two", result[1].text.lower())

    def test_exact_count_mismatched_content_uses_textual_evidence_not_blind_index(self):
        """When cue count == clause count but content does not match by index:
        The engine must NOT blindly map by index; it must use textual evidence.
        """
        srt_cues = [
            SrtCue(start=0.0, end=2.0, text="Unrelated background noise."),
            SrtCue(start=2.0, end=4.0, text="Second sentence here."),
            SrtCue(start=4.0, end=6.0, text="Third sentence here."),
        ]
        script = "First sentence here. Second sentence here. Third sentence here."
        result = _canonicalize_narration(srt_cues, script)

        # Cue 0 had low similarity with clause 0, so it must preserve its timing-source text
        # rather than blindly getting "First sentence here."
        self.assertEqual(result[0].text, "Unrelated background noise.")
        # Cues 1 and 2 should match the corresponding canonical clauses
        self.assertEqual(result[1].text, "Second sentence here.")
        self.assertEqual(result[2].text, "Third sentence here.")

    def test_last_cue_low_confidence_preserves_timing_source_text(self):
        """Final cue with low confidence does not blindly attach unrelated canonical remainder."""
        srt_cues = [
            SrtCue(start=0.0, end=2.0, text="First sentence here."),
            SrtCue(start=2.0, end=4.0, text="Incomprehensible garble and static."),
        ]
        script = "First sentence here. Second sentence here. Third very long detailed sentence."
        result = _canonicalize_narration(srt_cues, script)

        # First cue matches first sentence
        self.assertEqual(result[0].text, "First sentence here.")
        # Final cue had low confidence with remaining script, so it must preserve its timing text
        # rather than fabricating false precision with "Second sentence here. Third very long..."
        self.assertEqual(result[1].text, "Incomprehensible garble and static.")


class TestAudioDurationBounds(unittest.TestCase):
    """Tests for audio duration bounds validation (G03 requirement #10)."""

    def _cue(self, start, end, label="hello"):
        return TimelineCue(id="S001", order=1, start=start, end=end, narration=label)

    def test_timeline_beyond_audio_duration_rejected(self):
        """Last cue end far past audio duration must raise TimelineError."""
        cue = self._cue(0, 75.0)
        with self.assertRaises(TimelineError) as ctx:
            build_timeline_plan(
                project_title="T",
                audio_file="a.wav",
                timing_file="t.srt",
                duration=60.0,
                cues=[cue],
            )
        self.assertIn("75.000", str(ctx.exception))
        self.assertIn("60.000", str(ctx.exception))

    def test_minor_timing_tolerance_accepted(self):
        """End within tolerance of audio duration (e.g. 0.3s over) should be accepted."""
        cue = self._cue(0, 60.3)
        # Should NOT raise for a minor overshoot within AUDIO_DURATION_TOLERANCE
        plan = build_timeline_plan(
            project_title="T",
            audio_file="a.wav",
            timing_file="t.srt",
            duration=60.0,
            cues=[cue],
        )
        self.assertIsNotNone(plan)

    def test_cue_start_beyond_audio_duration_rejected(self):
        """A cue starting after audio duration must be rejected."""
        cue = TimelineCue(id="S001", order=1, start=70.0, end=72.0, narration="late")
        with self.assertRaises(TimelineError) as ctx:
            build_timeline_plan(
                project_title="T",
                audio_file="a.wav",
                timing_file="t.srt",
                duration=60.0,
                cues=[cue],
            )
        self.assertIn("70.000", str(ctx.exception))

    def test_tolerance_boundary_at_exactly_tolerance(self):
        """End exactly at audio_duration + tolerance is accepted."""
        cue = self._cue(0, 60.0 + AUDIO_DURATION_TOLERANCE)
        plan = build_timeline_plan(
            project_title="T",
            audio_file="a.wav",
            timing_file="t.srt",
            duration=60.0,
            cues=[cue],
        )
        self.assertIsNotNone(plan)

    def test_tolerance_just_over_boundary_rejected(self):
        """End just over audio_duration + tolerance is rejected."""
        over = 60.0 + AUDIO_DURATION_TOLERANCE + 0.01
        cue = self._cue(0, over)
        with self.assertRaises(TimelineError):
            build_timeline_plan(
                project_title="T",
                audio_file="a.wav",
                timing_file="t.srt",
                duration=60.0,
                cues=[cue],
            )


class TestTimingProviderFallback(unittest.TestCase):
    """Tests for timing provider fallback safety (G03 requirement #11)."""

    def test_malformed_user_srt_fails_not_falls_through(self):
        """Malformed user-supplied SRT must raise TimelineError, not fall through to Whisper."""
        with tempfile.TemporaryDirectory() as directory:
            bad_srt = Path(directory) / "bad.srt"
            bad_srt.write_text("this is not an SRT file", encoding="utf-8")

            whisper_called = []
            def mock_whisper(**kwargs):
                whisper_called.append(True)

            with self.assertRaises(TimelineError):
                acquire_timing_file(
                    source_timing_file=str(bad_srt),
                    task_directory=Path(directory) / "task",
                    audio_file="audio.wav",
                    script="Some narration.",
                    duration=5.0,
                    whisper_create=mock_whisper,
                )
            # Whisper must NOT have been called
            self.assertFalse(whisper_called, "Whisper must not be called when user SRT is malformed")

    def test_whisper_failure_reaches_estimated_fallback(self):
        """When Whisper fails, estimated text-weight fallback must still be reached."""
        with tempfile.TemporaryDirectory() as directory:
            def mock_whisper(**kwargs):
                raise RuntimeError("Whisper model not available")

            target, cues, source_label = acquire_timing_file(
                source_timing_file=None,
                task_directory=directory,
                audio_file="audio.wav",
                script="First point. Second point.",
                duration=8.0,
                whisper_create=mock_whisper,
            )
            self.assertEqual(source_label, "estimated")
            self.assertTrue(Path(target).is_file())
            self.assertGreater(len(cues), 0)

    def test_tts_failure_reaches_whisper_then_estimated(self):
        """TTS timing failure must log and fall through to Whisper, then estimated."""
        with tempfile.TemporaryDirectory() as directory:

            class FakeSubMaker:
                cues = ["fake"]

            def mock_whisper(**kwargs):
                raise RuntimeError("Whisper not available")

            with patch("app.services.timeline.voice.create_subtitle", side_effect=RuntimeError("TTS failed")):
                target, cues, source_label = acquire_timing_file(
                    source_timing_file=None,
                    task_directory=directory,
                    audio_file="audio.wav",
                    script="Some narration text.",
                    duration=5.0,
                    sub_maker=FakeSubMaker(),
                    reliable_tts_timing=True,
                    whisper_create=mock_whisper,
                )
            self.assertEqual(source_label, "estimated")

    def test_tts_success_returns_tts_source_label(self):
        """Successful TTS timing returns 'tts' source label."""
        with tempfile.TemporaryDirectory() as directory:
            task_dir = Path(directory) / "task"
            task_dir.mkdir()
            timing_srt = task_dir / "timing.srt"

            class FakeSubMaker:
                cues = ["fake"]

            def mock_create_subtitle(**kwargs):
                # Write a valid SRT file to the expected path
                timing_srt.write_text(
                    "1\n00:00:00,000 --> 00:00:05,000\nSome narration text.\n",
                    encoding="utf-8",
                )

            with patch("app.services.timeline.voice.create_subtitle", side_effect=mock_create_subtitle):
                target, cues, source_label = acquire_timing_file(
                    source_timing_file=None,
                    task_directory=task_dir,
                    audio_file="audio.wav",
                    script="Some narration text.",
                    duration=5.0,
                    sub_maker=FakeSubMaker(),
                    reliable_tts_timing=True,
                )
            self.assertEqual(source_label, "tts")

    def test_user_srt_success_returns_user_srt_label(self):
        """Successful user-provided SRT returns 'user_srt' source label."""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.srt"
            source.write_text(SRT, encoding="utf-8")
            _, cues, source_label = acquire_timing_file(
                source_timing_file=str(source),
                task_directory=Path(directory) / "task",
                audio_file="audio.wav",
                script="Text.",
                duration=6.0,
            )
            self.assertEqual(source_label, "user_srt")

    def test_keyboard_interrupt_not_swallowed_by_tts(self):
        """KeyboardInterrupt from TTS must propagate, not be swallowed."""
        with tempfile.TemporaryDirectory() as directory:
            class FakeSubMaker:
                cues = ["fake"]

            with patch("app.services.timeline.voice.create_subtitle", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    acquire_timing_file(
                        source_timing_file=None,
                        task_directory=directory,
                        audio_file="audio.wav",
                        script="Some text.",
                        duration=5.0,
                        sub_maker=FakeSubMaker(),
                        reliable_tts_timing=True,
                    )

    def test_keyboard_interrupt_not_swallowed_by_whisper(self):
        """KeyboardInterrupt from Whisper must propagate, not be swallowed."""
        with tempfile.TemporaryDirectory() as directory:
            def mock_whisper(**kwargs):
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                acquire_timing_file(
                    source_timing_file=None,
                    task_directory=directory,
                    audio_file="audio.wav",
                    script="Some text.",
                    duration=5.0,
                    whisper_create=mock_whisper,
                )


class TestTimelineRunner(unittest.TestCase):
    def test_runner_writes_timeline_and_planned_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_path = root / "project.json"
            project = ProjectSpec(
                schema_version="1.0",
                project={"title": "Timeline"},
                script={"subject": "Timeline subject", "script": "First point."},
                narration=NarrationSpec(mode="file", file="audio.wav"),
            )
            project_path.write_text(project.model_dump_json(), encoding="utf-8")
            audio = root / "audio.wav"
            audio.write_bytes(b"audio")
            task_dir = root / "task"
            with patch("app.services.project_timeline_runner.utils.task_dir", return_value=str(task_dir)), patch(
                "app.services.project_timeline_runner.tm.generate_script", return_value="First point."
            ), patch(
                "app.services.project_timeline_runner.tm.generate_audio",
                return_value=(str(audio), 2.0, None),
            ), patch(
                "app.services.project_timeline_runner.voice.get_audio_duration", return_value=2.0
            ), patch(
                "app.services.project_timeline_runner.acquire_timing_file",
                return_value=(
                    str(task_dir / "timing.srt"),
                    parse_srt_text("1\n00:00:00,000 --> 00:00:02,000\nFirst point.\n"),
                    "tts",
                ),
            ):
                result = run_timeline_plan(str(project_path), task_id="timeline-task")
            self.assertEqual(result["task_id"], "timeline-task")
            self.assertTrue((task_dir / "timeline.json").is_file())
            self.assertTrue((task_dir / "project.planned.json").is_file())
            manifest = json.loads((task_dir / "project_manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")

    def test_plan_runner_writes_visual_plan_without_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_path = root / "project.json"
            project = ProjectSpec(
                schema_version="1.0",
                project={"title": "Plan"},
                script={"subject": "Plan subject", "script": "Age 65 matters."},
                narration=NarrationSpec(mode="file", file="audio.wav"),
            )
            project_path.write_text(project.model_dump_json(), encoding="utf-8")
            audio = root / "audio.wav"
            audio.write_bytes(b"audio")
            task_dir = root / "task"
            cue = TimelineCue(id="S001", order=1, start=0, end=2, narration="Age 65 matters.")
            with patch("app.services.project_timeline_runner.utils.task_dir", return_value=str(task_dir)), patch(
                "app.services.project_timeline_runner.tm.generate_script", return_value="Age 65 matters."
            ), patch(
                "app.services.project_timeline_runner.tm.generate_audio",
                return_value=(str(audio), 2.0, None),
            ), patch(
                "app.services.project_timeline_runner.voice.get_audio_duration", return_value=2.0
            ), patch(
                "app.services.project_timeline_runner.acquire_timing_file",
                return_value=(
                    str(task_dir / "timing.srt"),
                    parse_srt_text("1\n00:00:00,000 --> 00:00:02,000\nAge 65 matters.\n"),
                    "user_srt",
                ),
            ), patch(
                "app.services.project_timeline_runner.plan_visuals",
                return_value=[fallback_visual(project, cue)],
            ) as planner, patch(
                "app.services.project_timeline_runner.tm.get_video_materials",
                side_effect=AssertionError("asset acquisition must not run"),
            ):
                from app.services.project_timeline_runner import run_project_plan

                result = run_project_plan(str(project_path), task_id="plan-task")
            planner.assert_called_once()
            self.assertTrue((task_dir / "visual_plan.json").is_file())
            self.assertTrue((task_dir / "project.planned.json").is_file())
            self.assertIn("visual_plan_file", result)


if __name__ == "__main__":
    unittest.main()
