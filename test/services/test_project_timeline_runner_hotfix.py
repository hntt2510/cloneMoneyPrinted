import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.project import (
    NarrationSpec,
    ProjectMetadata,
    ProjectSpec,
    ProductionConfig,
    ScriptSpec,
    TimelineCue,
    VisualCue,
    VisualType,
    VisualPurpose,
    BrollPayload,
    DataPayload,
    DataTemplate,
)
from app.models.schema import VideoAspect
from app.services.project_spec import save_project_spec, load_project_spec
from app.services.project_timeline_runner import run_project_plan
from app.services.timeline import parse_srt_text


class TestProjectTimelineRunnerHotfix(unittest.TestCase):
    """Test project planning stage with speech gaps normalizes visual boundaries and passes ProjectSpec validation."""

    def test_run_project_plan_with_speech_gaps_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_path = root / "project.json"
            task_dir = root / "task"

            spec = ProjectSpec(
                schema_version="1.0",
                project=ProjectMetadata(
                    title="EV Performance",
                    aspect_ratio=VideoAspect.landscape,
                    fps=30,
                ),
                script=ScriptSpec(
                    subject="EVs",
                    script="Electric vehicles deliver peak torque instantly. Creating an immediate sensation of effortless acceleration. Unlike internal combustion engines with mechanical delay. Direct-drive electric motors achieve maximum efficiency.",
                ),
                narration=NarrationSpec(mode="file", file="audio.wav"),
                production=ProductionConfig(),
            )
            project_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
            audio = root / "audio.wav"
            audio.write_bytes(b"dummy audio content")

            srt_content = (
                "1\n00:00:00,100 --> 00:00:03,900\nElectric vehicles deliver peak torque instantly.\n\n"
                "2\n00:00:04,080 --> 00:00:06,800\nCreating an immediate sensation of effortless acceleration.\n\n"
                "3\n00:00:07,660 --> 00:00:11,200\nUnlike internal combustion engines with mechanical delay.\n\n"
                "4\n00:00:11,450 --> 00:00:15,600\nDirect-drive electric motors achieve maximum efficiency.\n"
            )

            llm_response = json.dumps({
                "cues": [
                    {
                        "id": "S001",
                        "order": 1,
                        "visual_type": "data",
                        "purpose": "explain",
                        "payload": {
                            "template": "number",
                            "headline": "Instant Peak Torque",
                            "data": {},
                        },
                    },
                    {
                        "id": "S002",
                        "order": 2,
                        "visual_type": "broll",
                        "purpose": "context",
                        "payload": {
                            "search_query": "electric car acceleration",
                            "fallback_queries": ["electric car acceleration daily life"],
                            "avoid": ["animation"],
                            "source_priority": ["pexels"],
                        },
                    },
                    {
                        "id": "S003",
                        "order": 3,
                        "visual_type": "broll",
                        "purpose": "context",
                        "payload": {
                            "search_query": "combustion engine pistons",
                            "fallback_queries": ["combustion engine pistons daily life"],
                            "avoid": ["animation"],
                            "source_priority": ["pexels"],
                        },
                    },
                    {
                        "id": "S004",
                        "order": 4,
                        "visual_type": "broll",
                        "purpose": "context",
                        "payload": {
                            "search_query": "electric motor rotating",
                            "fallback_queries": ["electric motor rotating daily life"],
                            "avoid": ["animation"],
                            "source_priority": ["pexels"],
                        },
                    },
                ]
            })

            with patch("app.services.project_timeline_runner.utils.task_dir", return_value=str(task_dir)), patch(
                "app.services.project_timeline_runner.tm.generate_script",
                return_value="Electric vehicles deliver peak torque instantly. Creating an immediate sensation of effortless acceleration. Unlike internal combustion engines with mechanical delay. Direct-drive electric motors achieve maximum efficiency.",
            ), patch(
                "app.services.project_timeline_runner.tm.generate_audio",
                return_value=(str(audio), 16.4667, None),
            ), patch(
                "app.services.project_timeline_runner.voice.get_audio_duration", return_value=16.4667
            ), patch(
                "app.services.project_timeline_runner.acquire_timing_file",
                return_value=(
                    str(task_dir / "timing.srt"),
                    parse_srt_text(srt_content),
                    "user_srt",
                ),
            ), patch(
                "app.services.visual_planner.llm.generate_response",
                return_value=llm_response,
            ):
                result = run_project_plan(str(project_path), task_id="test-plan-hotfix")

            self.assertEqual(result["manifest"]["status"], "complete")
            planned_file = Path(result["planned_project_file"])
            self.assertTrue(planned_file.is_file())

            # Load and verify ProjectSpec validation passes
            planned_project = load_project_spec(planned_file)
            self.assertEqual(len(planned_project.visual_cues), 4)
            # S001 starts at 0.0
            self.assertEqual(planned_project.visual_cues[0].start, 0.0)
            # S004 ends at 16.4667
            self.assertAlmostEqual(planned_project.visual_cues[-1].end, 16.4667, places=2)


if __name__ == "__main__":
    unittest.main()
