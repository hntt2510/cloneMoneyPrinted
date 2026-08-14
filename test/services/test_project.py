import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli
from app.models.project import (
    AssetJob,
    JobStatus,
    NarrationMode,
    NarrationSpec,
    ProjectSpec,
    ProductionConfig,
    ScriptSpec,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.project_runner import ProjectRunError, run_project
from app.services.project_spec import (
    ProjectSpecError,
    load_project_spec,
    preflight_project,
    project_to_video_params,
    save_project_spec,
)


def _project(**overrides) -> ProjectSpec:
    value = {
        "schema_version": "1.0",
        "project": {"title": "Example"},
        "script": {"subject": "A subject", "search_terms": [" foo ", ""]},
        "narration": {"mode": "tts"},
    }
    value.update(overrides)
    return ProjectSpec.model_validate(value)


class TestProjectModels(unittest.TestCase):
    def test_defaults_and_normalization(self):
        project = _project()
        self.assertEqual(project.project.aspect_ratio.value, "16:9")
        self.assertEqual(project.project.fps, 30)
        self.assertEqual(project.script.search_terms, ["foo"])
        self.assertEqual(project.production.video_source.value, "pexels")
        self.assertTrue(project.production.match_materials_to_script)

    def test_strict_and_version_validation(self):
        with self.assertRaises(ValueError):
            _project(script={"subject": "ok", "video_sorce": "pexels"})
        with self.assertRaises(ValueError):
            ProjectSpec.model_validate(
                {
                    "schema_version": "1.0",
                    "project": {"title": "Example"},
                    "script": {"subject": "ok"},
                }
            )
        with self.assertRaises(ProjectSpecError):
            load_project_spec(self._write_json({"schema_version": "2.0"}))

    def test_constraints(self):
        with self.assertRaises(ValueError):
            _project(project={"title": "", "fps": 30})
        with self.assertRaises(ValueError):
            _project(project={"title": "x", "fps": 0})
        with self.assertRaises(ValueError):
            _project(project={"title": "x", "fps": 121})
        with self.assertRaises(ValueError):
            NarrationSpec(mode=NarrationMode.file)
        with self.assertRaises(ValueError):
            ProductionConfig(video_source="local")
        with self.assertRaises(ValueError):
            VisualCue(
                id="cue",
                order=1,
                start=10,
                end=5,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload={"search_query": "office meeting"},
            )

    def test_future_jobs_are_typed_and_have_isolated_defaults(self):
        first = AssetJob(id="a", scene_id="s", kind="stock")
        second = AssetJob(id="b", scene_id="s", kind="stock")
        first.metadata["key"] = "value"
        self.assertEqual(second.metadata, {})
        self.assertEqual(first.status, JobStatus.planned)

    def test_json_round_trip_uses_values(self):
        project = _project()
        restored = ProjectSpec.model_validate_json(project.model_dump_json())
        self.assertEqual(restored, project)
        self.assertEqual(json.loads(project.model_dump_json())["project"]["aspect_ratio"], "16:9")

    def _write_json(self, value):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(value, handle)
        handle.close()
        self.addCleanup(lambda: os.unlink(handle.name) if os.path.exists(handle.name) else None)
        return handle.name


class TestProjectSpecService(unittest.TestCase):
    def test_example_loads_and_adapter_resolves_project_relative_paths(self):
        project = load_project_spec("examples/project.example.json")
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "project.json"
            audio = Path(directory) / "audio" / "narration.wav"
            clip = Path(directory) / "clips" / "a.mp4"
            audio.parent.mkdir()
            clip.parent.mkdir()
            audio.write_bytes(b"audio")
            clip.write_bytes(b"video")
            project = project.model_copy(
                update={
                    "narration": NarrationSpec(mode="file", file="audio/narration.wav"),
                    "production": ProductionConfig(
                        video_source="local", local_materials=["clips/a.mp4"]
                    ),
                }
            )
            save_project_spec(project, project_path)
            loaded = load_project_spec(project_path)
            preflight_project(loaded, directory)
            params = project_to_video_params(loaded, directory)
            self.assertEqual(params.custom_audio_file, str(audio.resolve()))
            self.assertEqual(params.video_materials[0].url, str(clip.resolve()))
            self.assertEqual(params.video_subject, loaded.script.subject)

    def test_preflight_rejects_missing_files(self):
        project = _project(
            narration={"mode": "file", "file": "missing.wav"},
        )
        with self.assertRaises(ProjectSpecError):
            preflight_project(project, tempfile.gettempdir())


class TestProjectRunner(unittest.TestCase):
    def test_runner_persists_normalized_project_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "project.json"
            save_project_spec(_project(), project_path)
            task_root = Path(directory) / "tasks"
            with patch("app.services.project_runner.utils.task_dir", return_value=str(task_root / "task-1")), patch(
                "app.services.project_runner.tm.start", return_value={"script": "ok"}
            ) as start:
                result = run_project(str(project_path), task_id="task-1", stop_at="script")

            task_dir = task_root / "task-1"
            normalized = json.loads((task_dir / "project.normalized.json").read_text())
            manifest = json.loads((task_dir / "project_manifest.json").read_text())
            self.assertEqual(normalized["schema_version"], "1.0")
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(result["task_id"], "task-1")
            self.assertEqual(start.call_args.kwargs["stop_at"], "script")

    def test_runner_persists_failure_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            project_path = Path(directory) / "project.json"
            save_project_spec(_project(), project_path)
            task_dir = Path(directory) / "tasks" / "task-2"
            with patch("app.services.project_runner.utils.task_dir", return_value=str(task_dir)), patch(
                "app.services.project_runner.tm.start", return_value=None
            ):
                with self.assertRaises(ProjectRunError):
                    run_project(str(project_path), task_id="task-2")
            manifest = json.loads((task_dir / "project_manifest.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIn("no result", manifest["error"])


class TestProjectCli(unittest.TestCase):
    def test_project_mode_dispatches_runner(self):
        expected = {"task_id": "task", "result": {}, "manifest": {}}
        with patch("cli.run_project", return_value=expected) as runner:
            code = cli.run_cli(
                ["--project", "examples/project.example.json", "--task-id", "task"]
            )
        self.assertEqual(code, 0)
        runner.assert_called_once_with(
            "examples/project.example.json", task_id="task", stop_at="video"
        )

    def test_validate_only_does_not_run_pipeline(self):
        with patch("cli.tm.start") as start:
            code = cli.run_cli(["--project", "examples/project.example.json", "--validate-only"])
        self.assertEqual(code, 0)
        start.assert_not_called()

    def test_plan_only_dispatches_plan_runner(self):
        expected = {"task_id": "plan-task", "timeline_file": "timeline.json"}
        with patch("cli.run_project_plan", return_value=expected) as runner:
            code = cli.run_cli(
                ["--project", "examples/project.example.json", "--plan-only", "--task-id", "plan-task"]
            )
        self.assertEqual(code, 0)
        runner.assert_called_once_with("examples/project.example.json", task_id="plan-task")

    def test_plan_only_rejects_stop_at_and_validate_only(self):
        with self.assertRaises(SystemExit):
            cli.parse_args(
                ["--project", "examples/project.example.json", "--plan-only", "--stop-at", "audio"]
            )
        with self.assertRaises(SystemExit):
            cli.parse_args(
                ["--project", "examples/project.example.json", "--plan-only", "--validate-only"]
            )

    def test_project_rejects_manual_flags(self):
        with self.assertRaises(SystemExit):
            cli.parse_args(
                ["--project", "examples/project.example.json", "--video-source", "pixabay"]
            )

    def test_manual_mode_still_requires_subject(self):
        with self.assertRaises(SystemExit):
            cli.parse_args([])


if __name__ == "__main__":
    unittest.main()
