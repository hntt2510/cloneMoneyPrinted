from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.models.project import (
    AssetJob,
    JobStatus,
    NarrationMode,
    NarrationSpec,
    ProductionConfig,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    ScriptSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.motion_runner import run_motion_render
from app.utils import utils


def _make_mixed_project(task_dir: Path) -> ProjectSpec:
    audio_file = task_dir / "audio.mp3"
    audio_file.write_bytes(b"\x00" * 100)

    spec = ProjectSpec(
        schema_version="1.0",
        project=ProjectMetadata(
            title="Mixed Motion Test Project",
            aspect_ratio=VideoAspect.landscape,
            fps=30,
        ),
        script=ScriptSpec(
            subject="Mixed Motion",
            script="Hook. Core. Resolution.",
        ),
        narration=NarrationSpec(mode=NarrationMode.file, file=str(audio_file)),
        production=ProductionConfig(),
        timeline_cues=[
            TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Broll scene"),
            TimelineCue(id="S002", order=2, start=1.0, end=2.0, narration="Data scene"),
            TimelineCue(id="S003", order=3, start=2.0, end=3.0, narration="Text scene"),
        ],
        visual_cues=[
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                start=0.0,
                end=1.0,
                narration="Broll scene",
                payload={"search_query": "stock footage"},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=1.0,
                end=2.0,
                narration="Data scene",
                payload={
                    "template": "number",
                    "headline": "TOTAL NET WORTH",
                    "data": {"value": "$250,000", "label": "GROWTH"},
                },
            ),
            VisualCue(
                id="S003",
                order=3,
                visual_type=VisualType.text,
                purpose=VisualPurpose.emphasis,
                start=2.0,
                end=3.0,
                narration="Text scene",
                payload={"headline": "CHAPTER 2", "subheadline": "THE STRATEGY"},
            ),
        ],
        asset_jobs=[
            AssetJob(
                id="A001",
                scene_id="S001",
                kind="broll",
                status=JobStatus.ready,
                output="broll/S001.mp4",
                metadata={"status_history": ["planned", "ready"]},
            )
        ],
        render_jobs=[],
    )
    return spec


class TestMotionRunner(unittest.TestCase):
    def setUp(self):
        self.task_id = utils.get_uuid()
        self.task_dir = Path(utils.task_dir(self.task_id)).resolve()
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.task_dir, ignore_errors=True)

    def test_run_motion_render_mixed_project(self):
        project = _make_mixed_project(self.task_dir)
        project_file = self.task_dir / "project.planned.json"
        project_file.write_text(project.model_dump_json(indent=2), encoding="utf-8")

        result = run_motion_render(project_file, task_id=self.task_id)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["motion_count"], 2)

        motion_project_file = self.task_dir / "project.motion.json"
        self.assertTrue(motion_project_file.exists())
        motion_project = ProjectSpec.model_validate_json(motion_project_file.read_text(encoding="utf-8"))

        self.assertEqual(len(motion_project.asset_jobs), 1)
        self.assertEqual(motion_project.asset_jobs[0].id, "A001")

        self.assertEqual(len(motion_project.render_jobs), 2)
        render_scene_ids = [j.scene_id for j in motion_project.render_jobs]
        self.assertEqual(render_scene_ids, ["S002", "S003"])

        for job in motion_project.render_jobs:
            self.assertEqual(job.status, JobStatus.ready)
            self.assertIn("planned", job.metadata["status_history"])
            self.assertIn("processing", job.metadata["status_history"])
            self.assertIn("ready", job.metadata["status_history"])

        manifest_file = self.task_dir / "motion" / "motion_manifest.json"
        self.assertTrue(manifest_file.exists())

    def test_run_motion_render_zero_motion_cues(self):
        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Zero Motion", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="T", script="H. C. R."),
            narration=NarrationSpec(mode=NarrationMode.tts, voice_name="alloy"),
            timeline_cues=[TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Broll")],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    start=0.0,
                    end=1.0,
                    narration="Broll",
                    payload={"search_query": "sky landscape"},
                )
            ],
        )
        project_file = self.task_dir / "project.planned.json"
        project_file.write_text(spec.model_dump_json(indent=2), encoding="utf-8")

        result = run_motion_render(project_file, task_id=self.task_id)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["motion_count"], 0)

    def test_run_motion_render_grouped_cues(self):
        audio_file = self.task_dir / "audio.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Grouped Motion Test Project",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Grouped Motion",
                script="Hook. Core. Resolution.",
            ),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(audio_file)),
            production=ProductionConfig(),
            timeline_cues=[
                TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Scene 1"),
                TimelineCue(id="S002", order=2, start=1.0, end=2.0, narration="Scene 2"),
            ],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=0.0,
                    end=1.0,
                    narration="Scene 1",
                    visual_group_id="grp_runner",
                    payload={
                        "template": "number",
                        "headline": "POINT 1",
                        "data": {"value": "100"},
                    },
                ),
                VisualCue(
                    id="S002",
                    order=2,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=1.0,
                    end=2.0,
                    narration="Scene 2",
                    visual_group_id="grp_runner",
                    payload={
                        "template": "number",
                        "headline": "POINT 2",
                        "data": {"value": "200"},
                    },
                ),
            ],
        )
        project_file = self.task_dir / "project.planned.json"
        project_file.write_text(spec.model_dump_json(indent=2), encoding="utf-8")

        result = run_motion_render(project_file, task_id=self.task_id)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["motion_count"], 2)

        motion_project_file = self.task_dir / "project.motion.json"
        motion_project = ProjectSpec.model_validate_json(motion_project_file.read_text(encoding="utf-8"))
        for job in motion_project.render_jobs:
            self.assertEqual(job.status, JobStatus.ready)
            self.assertIn("planned", job.metadata["status_history"])
            self.assertIn("queued", job.metadata["status_history"])
            self.assertIn("processing", job.metadata["status_history"])
            self.assertIn("ready", job.metadata["status_history"])

    def test_run_motion_render_preserves_prior_manifest_failure(self):
        from datetime import datetime, timezone
        from app.models.project import ProjectManifest

        # Create a prior failed project_manifest.json
        manifest_file = self.task_dir / "project_manifest.json"
        now = datetime.now(timezone.utc)
        p_man = ProjectManifest(
            schema_version="1.0",
            project_title="Failed Project",
            project_file=str(self.task_dir / "project.json"),
            task_id=self.task_id,
            status=ProjectStatus.failed,
            fps=30,
            aspect_ratio=VideoAspect.landscape,
            created_at=now,
            updated_at=now,
            error="Broll extraction failed previously",
            outputs={"broll_failed": True},
        )
        manifest_file.write_text(p_man.model_dump_json(indent=2), encoding="utf-8")

        project = _make_mixed_project(self.task_dir)
        project_file = self.task_dir / "project.planned.json"
        project_file.write_text(project.model_dump_json(indent=2), encoding="utf-8")

        result = run_motion_render(project_file, task_id=self.task_id)
        self.assertEqual(result["status"], "complete")

        # Verify project_manifest.json status remains failed and prior error is preserved
        updated_man = ProjectManifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_man.status, ProjectStatus.failed)
        self.assertIn("Broll extraction failed previously", updated_man.error)


if __name__ == "__main__":
    unittest.main()
