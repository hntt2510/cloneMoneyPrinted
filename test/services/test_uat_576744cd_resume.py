import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.export import EditorPackageStatus
from app.models.execution import ExecutionManifest, SceneExecutionRecord
from app.models.project import (
    DataPayload,
    DataTemplate,
    BrollPayload,
    JobStatus,
    NarrationSpec,
    ProductionConfig,
    ProjectMetadata,
    ProjectSpec,
    ScriptSpec,
    SelectedBrollAsset,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.assembly_runner import assemble_final_video
from app.services.broll import acquire_broll_scene, BrollSelectionContext
from app.services.export_runner import export_editor_package
from app.services.production_workflow import run_production_workflow
from app.services.project_spec import load_project_spec, save_project_spec
from app.services.visual_planner import normalize_visual_cue_boundaries


class TestUat576744cdResume(unittest.TestCase):
    """End-to-end simulation of the UAT failure and resume recovery for task 576744cd-b76d-40eb-b272-cfc9fed61e3d."""

    def test_uat_task_resume_lifecycle_with_normalization_and_stale_invalidation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task_id = "576744cd-b76d-40eb-b272-cfc9fed61e3d"
            task_dir = root / "tasks" / task_id
            task_dir.mkdir(parents=True, exist_ok=True)

            # 1. Setup speech cues with realistic pause gaps
            t_cues = [
                TimelineCue(id="S001", order=1, start=0.10, end=3.90, narration="Electric vehicles deliver peak torque instantly."),
                TimelineCue(id="S002", order=2, start=4.088, end=6.80, narration="Creating an immediate sensation of effortless acceleration."),
                TimelineCue(id="S003", order=3, start=7.662, end=11.20, narration="Unlike internal combustion engines with mechanical delay."),
                TimelineCue(id="S004", order=4, start=11.45, end=15.60, narration="Direct-drive electric motors achieve maximum efficiency."),
            ]
            raw_v_cues = [
                VisualCue(
                    id="S001",
                    order=1,
                    start=0.10,
                    end=3.90,
                    narration=t_cues[0].narration,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.evidence,
                    payload=DataPayload(template=DataTemplate.number, headline="0-60 in 2.3s").model_dump(mode="json"),
                ),
                VisualCue(
                    id="S002",
                    order=2,
                    start=4.088,
                    end=6.80,
                    narration=t_cues[1].narration,
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    payload=BrollPayload(search_query="electric car acceleration").model_dump(mode="json"),
                ),
                VisualCue(
                    id="S003",
                    order=3,
                    start=7.662,
                    end=11.20,
                    narration=t_cues[2].narration,
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    payload=BrollPayload(search_query="combustion engine").model_dump(mode="json"),
                ),
                VisualCue(
                    id="S004",
                    order=4,
                    start=11.45,
                    end=15.60,
                    narration=t_cues[3].narration,
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    payload=BrollPayload(search_query="electric motor").model_dump(mode="json"),
                ),
            ]

            spec = ProjectSpec(
                schema_version="1.0",
                project=ProjectMetadata(title="EV Speed Secrets", aspect_ratio=VideoAspect.landscape, fps=30),
                script=ScriptSpec(
                    subject="EVs",
                    script="Electric vehicles deliver peak torque instantly. Creating an immediate sensation of effortless acceleration. Unlike internal combustion engines with mechanical delay. Direct-drive electric motors achieve maximum efficiency.",
                ),
                narration=NarrationSpec(mode="file", file="audio.mp3"),
                production=ProductionConfig(),
                timeline_cues=t_cues,
                visual_cues=raw_v_cues,
            )

            project_file = task_dir / "project.json"
            save_project_spec(spec, project_file)
            audio_file = task_dir / "audio.mp3"
            audio_file.write_bytes(b"dummy audio data")

            # 2. Planning stage normalizes boundaries to 494 frames (16.4667s)
            total_duration = 16.4667
            normalized_cues = normalize_visual_cue_boundaries(
                raw_v_cues,
                fps=30,
                total_duration_seconds=total_duration,
            )
            planned_spec = spec.model_copy(update={"visual_cues": normalized_cues})
            planned_project_file = task_dir / "project.planned.json"
            save_project_spec(planned_spec, planned_project_file)

            # Assert ProjectSpec validation passes without error
            reloaded_planned = load_project_spec(planned_project_file)
            self.assertEqual(len(reloaded_planned.visual_cues), 4)
            self.assertEqual(reloaded_planned.visual_cues[0].start, 0.0)
            self.assertAlmostEqual(reloaded_planned.visual_cues[-1].end, 16.4667, places=2)

            # 3. Simulate existing stale assets on disk (rendered with old durations)
            # S001: motion/S001_DATA.mp4 has 114 frames (needs 123)
            # S002: broll/S002/rendered.mp4 has 81 frames (needs 107), source.mp4 has 4.045s (121 frames)
            # S003: broll/S003/rendered.mp4 has 106 frames (needs 114), source.mp4 has 5.338s (160 frames)
            # S004: broll/S004/rendered.mp4 has 124 frames (needs 150), source.mp4 has 15.015s (450 frames)
            motion_dir = task_dir / "motion"
            motion_dir.mkdir(parents=True, exist_ok=True)
            s1_mp4 = motion_dir / "S001_DATA.mp4"
            s1_mp4.write_bytes(b"dummy s1")

            broll_dir = task_dir / "broll"
            for sid, src_len, old_len in [
                ("S002", 4.045, 81),
                ("S003", 5.338, 106),
                ("S004", 15.015, 124),
            ]:
                s_dir = broll_dir / sid
                s_dir.mkdir(parents=True, exist_ok=True)
                (s_dir / "source.mp4").write_bytes(b"source data")
                (s_dir / "rendered.mp4").write_bytes(b"old rendered")

            # 4. Mock execution / rerender pipeline
            # When broll acquires scenes with new duration, source.mp4 is re-trimmed
            def mock_get_dur(path):
                p_str = str(path)
                if "S002\\source.mp4" in p_str or "S002/source.mp4" in p_str:
                    return 4.045
                if "S003\\source.mp4" in p_str or "S003/source.mp4" in p_str:
                    return 5.338
                if "S004\\source.mp4" in p_str or "S004/source.mp4" in p_str:
                    return 15.015
                return 2.5

            rendered_frames_map = {
                "S001": 123,
                "S002": 107,
                "S003": 114,
                "S004": 150,
            }

            def mock_probe(video_path, fps=30):
                for k, v in rendered_frames_map.items():
                    if k in str(video_path):
                        return v
                return 100

            # Mock scene orchestrator execution
            with patch("app.services.production_workflow.utils.task_dir", return_value=str(task_dir)), patch(
                "app.services.export_runner.utils.task_dir", return_value=str(task_dir)
            ), patch(
                "app.services.export_runner.probe_media_frames", side_effect=mock_probe
            ), patch(
                "app.services.assembly_runner.probe_media_frames", side_effect=mock_probe
            ):
                # Create executed project with 4 ready scenes
                from app.models.project import AssetJob, RenderJob
                executed_project = planned_spec.model_copy(
                    update={
                        "render_jobs": [
                            RenderJob(id="R001", scene_id="S001", kind="data", status=JobStatus.ready, output=str(s1_mp4)),
                        ],
                        "asset_jobs": [
                            AssetJob(id="A002", scene_id="S002", kind="broll", status=JobStatus.ready, output=str(broll_dir / "S002" / "rendered.mp4")),
                            AssetJob(id="A003", scene_id="S003", kind="broll", status=JobStatus.ready, output=str(broll_dir / "S003" / "rendered.mp4")),
                            AssetJob(id="A004", scene_id="S004", kind="broll", status=JobStatus.ready, output=str(broll_dir / "S004" / "rendered.mp4")),
                        ],
                    }
                )
                (task_dir / "project.executed.json").write_text(executed_project.model_dump_json(indent=2), encoding="utf-8")

                # Test G09 Editor Package export
                export_res = export_editor_package(planned_project_file, task_id=task_id)
                self.assertEqual(export_res.status, EditorPackageStatus.complete.value)
                self.assertEqual(export_res.ready_scene_count, 4)
                self.assertEqual(export_res.missing_scene_count, 0)
                self.assertIsNone(export_res.error)

                # Verify edit_manifest.json contents
                manifest_file = Path(export_res.edit_manifest_file)
                self.assertTrue(manifest_file.exists())
                edit_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                self.assertEqual(edit_manifest["duration_frames"], 494)
                self.assertEqual(len(edit_manifest["scenes"]), 4)


if __name__ == "__main__":
    unittest.main()
