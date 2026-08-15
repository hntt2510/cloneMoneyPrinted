from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from moviepy.video.io.VideoFileClip import VideoFileClip

from app.models.project import (
    DataPayload,
    DataTemplate,
    DocumentPayload,
    JobStatus,
    NarrationMode,
    ProjectManifest,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    ScriptSpec,
    TextPayload,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.project_spec import save_project_spec
from app.services.scene_orchestrator import run_all_project


class TestSceneOrchestratorSmoke(unittest.TestCase):
    """End-to-end local smoke render integration tests for G08 Scene Orchestrator.

    Executes actual Remotion rendering (local, 0 network requests) and validates
    final scene outputs and manifests.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "smoke-g08-task-001"
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_mock_local_project(self, aspect: VideoAspect = VideoAspect.landscape) -> tuple[ProjectSpec, Path]:
        width, height = aspect.to_resolution()

        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=1.0,
                narration="Full retirement age is sixty-seven.",
                payload={"template": "number", "headline": "Retirement Age", "data": {"primary_value": "67", "label": "Retirement Age"}},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.text,
                purpose=VisualPurpose.emphasis,
                start=1.0,
                end=2.0,
                narration="Early benefits begin at sixty-two.",
                payload={"headline": "Early Benefits: Age 62", "subheadline": None},
            ),
            VisualCue(
                id="S003",
                order=3,
                visual_type=VisualType.document,
                purpose=VisualPurpose.evidence,
                start=2.0,
                end=3.0,
                narration="Medicare coverage eligibility begins at sixty-five.",
                payload={
                    "search_query": "Medicare eligibility age 65",
                    "source_hint": "Medicare rules",
                    "evidence_required": False,
                    "highlight_target": "Medicare: Age 65",
                    "source_ids": ["NON_EXISTENT_SRC"],
                },
            ),
        ]

        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in sorted(cues, key=lambda x: x.order)
        ]

        dummy_audio = self.task_dir / "narration.mp3"
        dummy_audio.write_bytes(b"\x00" * 1024)

        dummy_timing = self.task_dir / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": []}), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Social Security Smoke",
                language="en-US",
                aspect_ratio=aspect,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Social Security Overview",
                script="Full retirement age is sixty-seven. Early benefits begin at sixty-two. Medicare coverage eligibility begins at sixty-five.",
                search_terms=["retirement", "medicare"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )

        project_path = self.task_dir / "project.json"
        save_project_spec(project, project_path)

        # Pre-seed planning artifacts to avoid external LLM/TTS
        save_project_spec(project, self.task_dir / "project.planned.json")
        (self.task_dir / "visual_plan.json").write_text(
            json.dumps({"project_title": project.project.title, "cues": [c.model_dump(mode="json") for c in cues]}),
            encoding="utf-8",
        )
        (self.task_dir / "timeline.json").write_text(
            json.dumps({"project_title": project.project.title, "cues": [c.model_dump(mode="json") for c in timeline_cues]}),
            encoding="utf-8",
        )
        now = "2026-08-15T00:00:00Z"
        p_manifest = ProjectManifest(
            schema_version=project.schema_version,
            project_title=project.project.title,
            project_file=str(project_path),
            task_id=self.task_id,
            status=ProjectStatus.processing,
            fps=30,
            aspect_ratio=aspect,
            created_at=now,
            updated_at=now,
        )
        (self.task_dir / "project_manifest.json").write_text(
            json.dumps(p_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        return project, project_path

    def test_local_smoke_run_all_and_validate_media(self) -> None:
        project, project_path = self._setup_mock_local_project(aspect=VideoAspect.landscape)

        # Run orchestrator
        from unittest.mock import patch
        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)):

            res = run_all_project(project_path, task_id=self.task_id)

        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["ready_scenes"], 3)
        self.assertEqual(res["failed_scenes"], 0)

        # Validate manifests exist and parse
        exec_manifest_path = Path(res["execution_manifest"])
        self.assertTrue(exec_manifest_path.exists())
        exec_data = json.loads(exec_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(exec_data["status"], "complete")
        self.assertEqual(len(exec_data["scenes"]), 3)

        # Inspect and validate each actual rendered MP4 file
        target_w, target_h = (1920, 1080)
        fps = 30

        for scene in exec_data["scenes"]:
            self.assertEqual(scene["status"], "ready")
            output_file = Path(scene["output_file"])
            self.assertTrue(output_file.exists(), f"Output file does not exist: {output_file}")
            self.assertGreater(output_file.stat().st_size, 0)

            clip = VideoFileClip(str(output_file))
            try:
                self.assertEqual(clip.size, [target_w, target_h])
                self.assertAlmostEqual(clip.fps, fps, delta=1.0)
                self.assertAlmostEqual(clip.duration, 1.0, delta=0.1)
                self.assertIsNone(clip.audio, f"Scene {scene['scene_id']} output must not contain audio")
            finally:
                clip.close()

        # Check S003 fallback record
        s003 = next(s for s in exec_data["scenes"] if s["scene_id"] == "S003")
        self.assertEqual(s003["planned_visual_type"], "document")
        self.assertEqual(s003["resolved_visual_type"], "text")
        self.assertEqual(s003["fallback_from"], "document")


if __name__ == "__main__":
    unittest.main()
