import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.models.project import (
    AssetJob,
    BrollPayload,
    JobStatus,
    NarrationSpec,
    ProjectManifest,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    SelectedBrollAsset,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.broll import BrollAcquisitionError
from app.services.broll_runner import run_broll_acquisition


class TestBrollRunner(unittest.TestCase):
    def _create_test_planned_project(self, task_dir: Path, has_broll: bool = True) -> Path:
        task_dir.mkdir(parents=True, exist_ok=True)
        visual_cues = []
        timeline_cues = []

        if has_broll:
            timeline_cues.append(
                TimelineCue(id="S001", order=1, start=0.0, end=4.0, narration="First scene narration.")
            )
            visual_cues.append(
                VisualCue(
                    id="S001",
                    order=1,
                    start=0.0,
                    end=4.0,
                    narration="First scene narration.",
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    payload=BrollPayload(search_query="business meeting").model_dump(mode="json"),
                )
            )
        else:
            timeline_cues.append(
                TimelineCue(id="S001", order=1, start=0.0, end=4.0, narration="15% increase in costs.")
            )
            visual_cues.append(
                VisualCue(
                    id="S001",
                    order=1,
                    start=0.0,
                    end=4.0,
                    narration="15% increase in costs.",
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    payload={"template": "number", "headline": "15% INCREASE", "data": {"pct": "15%"}},
                )
            )

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Broll Runner Test", aspect_ratio=VideoAspect.landscape, fps=30),
            script={"subject": "Testing", "script": "Narration text."},
            narration=NarrationSpec(mode="tts"),
            timeline_cues=timeline_cues,
            visual_cues=visual_cues,
        )

        planned_file = task_dir / "project.planned.json"
        planned_file.write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")

        visual_plan_file = task_dir / "visual_plan.json"
        visual_plan_file.write_text(
            json.dumps({"schema_version": "1.0", "project_title": "Broll Runner Test", "cues": [c.model_dump(mode="json") for c in visual_cues]}),
            encoding="utf-8",
        )

        now = datetime.now(timezone.utc)
        project_manifest = ProjectManifest(
            schema_version="1.0",
            project_title="Broll Runner Test",
            project_file=str((task_dir / "project.json").resolve()),
            task_id="test-task",
            status=ProjectStatus.complete,
            fps=30,
            aspect_ratio=VideoAspect.landscape,
            created_at=now,
            updated_at=now,
            outputs={"timeline_file": "timeline.json", "visual_plan_file": "visual_plan.json"},
        )
        (task_dir / "project_manifest.json").write_text(
            json.dumps(project_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        project_path = task_dir / "project.json"
        project_path.write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")
        return project_path

    def test_runner_acquires_broll_and_writes_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            project_path = self._create_test_planned_project(task_dir, has_broll=True)

            mock_asset = SelectedBrollAsset(
                scene_id="S001",
                provider="pexels",
                provider_asset_id="123",
                query_used="business meeting",
                candidate_id="pexels-123",
                download_url="https://dl.example/123.mp4",
                source_file=str((task_dir / "broll" / "S001" / "source.mp4").resolve()),
                rendered_file=str((task_dir / "broll" / "S001" / "rendered.mp4").resolve()),
                source_duration=10.0,
                trim_start=3.0,
                trim_end=7.0,
                scene_duration=4.0,
                width=1920,
                height=1080,
                score=85.0,
            )

            with patch("app.services.broll_runner.acquire_broll_scene", return_value=mock_asset), \
                 patch("app.services.broll_runner.utils.task_dir", return_value=str(task_dir)):
                result = run_broll_acquisition(project_path, task_id="test-task")

            self.assertEqual(result["task_id"], "test-task")
            self.assertEqual(result["ready_count"], 1)
            self.assertEqual(result["failed_count"], 0)
            self.assertEqual(result["status"], "complete")

            self.assertTrue((task_dir / "broll_manifest.json").exists())
            self.assertTrue((task_dir / "project.assets.json").exists())

            # Verify manifest outputs updated
            p_manifest = json.loads((task_dir / "project_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("broll_manifest_file", p_manifest["outputs"])
            self.assertIn("assets_project_file", p_manifest["outputs"])

            # Verify AssetJob in project.assets.json is ready
            p_assets = json.loads((task_dir / "project.assets.json").read_text(encoding="utf-8"))
            self.assertEqual(len(p_assets["asset_jobs"]), 1)
            self.assertEqual(p_assets["asset_jobs"][0]["status"], "ready")
            self.assertEqual(p_assets["asset_jobs"][0]["provider"], "pexels")

    def test_no_broll_project_succeeds_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            project_path = self._create_test_planned_project(task_dir, has_broll=False)

            with patch("app.services.broll_runner.acquire_broll_scene") as mock_acquire, \
                 patch("app.services.broll_runner.utils.task_dir", return_value=str(task_dir)):
                result = run_broll_acquisition(project_path, task_id="test-task")

            mock_acquire.assert_not_called()
            self.assertEqual(result["ready_count"], 0)
            self.assertEqual(result["failed_count"], 0)
            self.assertEqual(result["status"], "complete")

            broll_manifest = json.loads((task_dir / "broll_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(broll_manifest["assets"], [])
            self.assertEqual(broll_manifest["status"], "complete")

    def test_partial_failure_preserves_successful_assets_and_records_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            # Create project with 2 BROLL cues: S001 and S002
            timeline_cues = [
                TimelineCue(id="S001", order=1, start=0.0, end=3.0, narration="Scene 1"),
                TimelineCue(id="S002", order=2, start=3.0, end=6.0, narration="Scene 2"),
            ]
            visual_cues = [
                VisualCue(
                    id="S001",
                    order=1,
                    start=0.0,
                    end=3.0,
                    narration="Scene 1",
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    payload=BrollPayload(search_query="query 1").model_dump(mode="json"),
                ),
                VisualCue(
                    id="S002",
                    order=2,
                    start=3.0,
                    end=6.0,
                    narration="Scene 2",
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    payload=BrollPayload(search_query="query 2").model_dump(mode="json"),
                ),
            ]
            project = ProjectSpec(
                schema_version="1.0",
                project=ProjectMetadata(title="Partial Failure Test", aspect_ratio=VideoAspect.landscape, fps=30),
                script={"subject": "Testing", "script": "Narration text."},
                narration=NarrationSpec(mode="tts"),
                timeline_cues=timeline_cues,
                visual_cues=visual_cues,
            )
            (task_dir / "project.planned.json").write_text(json.dumps(project.model_dump(mode="json")), encoding="utf-8")
            (task_dir / "visual_plan.json").write_text(json.dumps({"schema_version": "1.0", "project_title": "Test", "cues": [c.model_dump(mode="json") for c in visual_cues]}), encoding="utf-8")
            project_path = task_dir / "project.json"
            project_path.write_text(json.dumps(project.model_dump(mode="json")), encoding="utf-8")

            mock_asset_s001 = SelectedBrollAsset(
                scene_id="S001",
                provider="pexels",
                provider_asset_id="111",
                query_used="query 1",
                candidate_id="pexels-111",
                download_url="https://dl.example/111.mp4",
                source_file=str((task_dir / "broll" / "S001" / "source.mp4").resolve()),
                rendered_file=str((task_dir / "broll" / "S001" / "rendered.mp4").resolve()),
                source_duration=6.0,
                trim_start=1.0,
                trim_end=4.0,
                scene_duration=3.0,
                width=1920,
                height=1080,
                score=80.0,
            )

            def mock_acquire(cue, **kwargs):
                if cue.id == "S001":
                    return mock_asset_s001
                raise BrollAcquisitionError("All candidates failed for scene S002")

            with patch("app.services.broll_runner.acquire_broll_scene", side_effect=mock_acquire), \
                 patch("app.services.broll_runner.utils.task_dir", return_value=str(task_dir)):
                result = run_broll_acquisition(project_path, task_id="partial-task")

            self.assertEqual(result["ready_count"], 1)
            self.assertEqual(result["failed_count"], 1)
            self.assertEqual(result["status"], "failed")

            # Check broll_manifest.json contains 1 ready asset and 1 failed scene
            manifest = json.loads((task_dir / "broll_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["assets"]), 1)
            self.assertEqual(manifest["assets"][0]["scene_id"], "S001")
            self.assertEqual(len(manifest["failed_scenes"]), 1)
            self.assertEqual(manifest["failed_scenes"][0]["scene_id"], "S002")

            # Check project.assets.json has S001 ready and S002 failed
            assets_data = json.loads((task_dir / "project.assets.json").read_text(encoding="utf-8"))
            jobs = {j["scene_id"]: j for j in assets_data["asset_jobs"]}
            self.assertEqual(jobs["S001"]["status"], "ready")
            self.assertEqual(jobs["S002"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
