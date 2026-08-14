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
    parse_srt_text,
    serialize_srt,
)


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
                target, cues = acquire_timing_file(
                    source_timing_file=str(source),
                    task_directory=Path(directory) / "task",
                    audio_file="audio.wav",
                    script="If you retire at 60, Medicare begins at 65. That leaves a five-year gap.",
                    duration=6,
                )
            whisper.assert_not_called()
            self.assertTrue(Path(target).is_file())
            self.assertEqual(len(cues), 3)

    def test_fallback_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            target, cues = acquire_timing_file(
                source_timing_file=None,
                task_directory=directory,
                audio_file="audio.wav",
                script="First point. Second point.",
                duration=8,
                whisper_create=lambda **kwargs: None,
            )
            self.assertEqual([cue.start for cue in cues], [0.0, 3.8095238095238093])
            self.assertTrue(Path(target).is_file())


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
                ),
            ):
                result = run_timeline_plan(str(project_path), task_id="timeline-task")
            self.assertEqual(result["task_id"], "timeline-task")
            self.assertTrue((task_dir / "timeline.json").is_file())
            self.assertTrue((task_dir / "project.planned.json").is_file())
            manifest = json.loads((task_dir / "project_manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")


if __name__ == "__main__":
    unittest.main()
