from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from moviepy.video.io.VideoFileClip import VideoFileClip

from app.models.export import EditManifest, EditorPackageStatus
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
from app.services.export_runner import export_editor_package
from app.services.project_spec import save_project_spec
from app.services.scene_orchestrator import compute_project_input_fingerprint, run_all_project


class TestExportRunnerSmoke(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "smoke-export-task-001"
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir = Path(self.temp_dir) / "exports" / "smoke-package"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_local_smoke_run_all_and_export_package(self) -> None:
        # 1. Setup local project with 2 motion scenes and 1 optional document (falling back to text)
        aspect = VideoAspect.landscape
        target_w, target_h = aspect.to_resolution()

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
        timing_content = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Full retirement age is sixty-seven."},
                {"start": 1.0, "end": 2.0, "text": "Early benefits begin at sixty-two."},
                {"start": 2.0, "end": 3.0, "text": "Medicare coverage eligibility begins at sixty-five."},
            ]
        }
        dummy_timing.write_text(json.dumps(timing_content, indent=2), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Smoke Export Project",
                language="en-US",
                aspect_ratio=aspect,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Retirement Guide",
                script="Full retirement age is sixty-seven. Early benefits begin at sixty-two. Medicare coverage eligibility begins at sixty-five.",
                search_terms=["retirement", "medicare"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )

        project_path = self.task_dir / "project.json"
        save_project_spec(project, project_path)

        # Pre-seed planning artifacts in task_dir
        save_project_spec(project, self.task_dir / "project.planned.json")
        (self.task_dir / "visual_plan.json").write_text(
            json.dumps({"schema_version": "1.0", "project_title": project.project.title, "cues": [c.model_dump(mode="json") for c in cues]}),
            encoding="utf-8",
        )
        (self.task_dir / "timeline.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "project_title": project.project.title,
                "audio_file": str(dummy_audio.resolve()),
                "timing_file": str(dummy_timing.resolve()),
                "duration": 3.0,
                "cues": [c.model_dump(mode="json") for c in timeline_cues],
            }),
            encoding="utf-8",
        )
        now = "2026-08-16T00:00:00Z"
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
        fp = compute_project_input_fingerprint(project)
        (self.task_dir / "orchestrator_state.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "task_id": self.task_id,
                "source_project_fingerprint": fp,
                "source_project_file": str(project_path),
                "created_at": now,
                "updated_at": now,
            }, indent=2),
            encoding="utf-8",
        )

        from unittest.mock import patch
        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)):

            # 2. Run G08 autonomous execution
            orch_res = run_all_project(project_path, task_id=self.task_id)
            self.assertEqual(orch_res["status"], "complete")

            # 3. Export G09 Editor Package
            export_res = export_editor_package(project_path, task_id=self.task_id, output_dir=self.export_dir)

        self.assertEqual(export_res.status, "complete")
        self.assertEqual(export_res.ready_scene_count, 3)
        self.assertEqual(export_res.missing_scene_count, 0)

        # 4. Verify directory layout and exported files
        self.assertTrue((self.export_dir / "project.json").exists())
        self.assertTrue((self.export_dir / "project.executed.json").exists())
        self.assertTrue((self.export_dir / "execution_manifest.json").exists())
        self.assertTrue((self.export_dir / "edit_manifest.json").exists())
        self.assertTrue((self.export_dir / "README_EDIT.md").exists())
        self.assertTrue((self.export_dir / "narration" / "narration.mp3").exists())
        self.assertTrue((self.export_dir / "narration" / "subtitle.srt").exists())
        self.assertTrue((self.export_dir / "sources" / "source_manifest.json").exists())

        # No final.mp4
        self.assertFalse((self.export_dir / "final.mp4").exists())

        # 5. Validate each actual exported scene MP4 clip
        manifest_data = json.loads((self.export_dir / "edit_manifest.json").read_text(encoding="utf-8"))
        edit_manifest = EditManifest.model_validate(manifest_data)
        self.assertEqual(edit_manifest.package_status, EditorPackageStatus.complete)

        for scene in edit_manifest.scenes:
            scene_file = self.export_dir / scene.exported_file
            self.assertTrue(scene_file.exists())
            self.assertGreater(scene_file.stat().st_size, 0)

            clip = VideoFileClip(str(scene_file))
            try:
                self.assertEqual(clip.size, [target_w, target_h])
                self.assertAlmostEqual(clip.fps, 30, delta=1.0)
                self.assertAlmostEqual(clip.duration, 1.0, delta=0.1)
                self.assertIsNone(clip.audio, f"Scene {scene.scene_id} in package must not contain audio")
            finally:
                clip.close()


if __name__ == "__main__":
    unittest.main()
