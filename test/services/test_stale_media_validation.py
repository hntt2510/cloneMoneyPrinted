import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.export import EditManifest, EditorPackageStatus, EditorSceneEntry
from app.models.execution import ExecutionManifest, SceneExecutionRecord
from app.models.project import (
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
    BrollPayload,
)
from app.models.schema import VideoAspect
from app.services.assembly_runner import assemble_final_video
from app.services.broll import acquire_broll_scene, BrollSelectionContext
from app.services.export_runner import export_editor_package, probe_media_frames
from app.services.production_workflow import run_production_workflow
from app.services.project_runner import ProjectRunError
from app.services.project_spec import save_project_spec


class TestStaleMediaValidation(unittest.TestCase):
    """Test suite for physical scene media duration validation, cache invalidation, and defense-in-depth."""

    def _create_test_project(self, root: Path, fps: int = 30) -> Path:
        project_file = root / "project.json"
        t_cues = [
            TimelineCue(id="S001", order=1, start=0.00, end=4.00, narration="Scene 1 speech"),
            TimelineCue(id="S002", order=2, start=4.00, end=8.00, narration="Scene 2 speech"),
        ]
        v_cues = [
            VisualCue(
                id="S001",
                order=1,
                start=0.00,
                end=4.00,
                narration="Scene 1 speech",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="query 1").model_dump(mode="json"),
            ),
            VisualCue(
                id="S002",
                order=2,
                start=4.00,
                end=8.00,
                narration="Scene 2 speech",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="query 2").model_dump(mode="json"),
            ),
        ]
        spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Stale Test", aspect_ratio=VideoAspect.landscape, fps=fps),
            script=ScriptSpec(subject="EVs", script="Scene 1 speech Scene 2 speech"),
            narration=NarrationSpec(mode="file", file="audio.wav"),
            production=ProductionConfig(),
            timeline_cues=t_cues,
            visual_cues=v_cues,
        )
        save_project_spec(spec, project_file)
        (root / "audio.wav").write_bytes(b"dummy audio")
        return project_file

    def test_g09_rejects_stale_scene_media_duration(self):
        """G09 export_editor_package fails if physical MP4 has fewer frames than manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task_dir = root / "task"
            task_dir.mkdir(parents=True, exist_ok=True)
            proj_file = self._create_test_project(task_dir)

            # Create scenes directory with mock MP4s
            broll_dir = task_dir / "broll"
            (broll_dir / "S001").mkdir(parents=True, exist_ok=True)
            (broll_dir / "S002").mkdir(parents=True, exist_ok=True)
            mp1 = broll_dir / "S001" / "rendered.mp4"
            mp2 = broll_dir / "S002" / "rendered.mp4"
            mp1.write_bytes(b"dummy video 1")
            mp2.write_bytes(b"dummy video 2")

            # Create mock executed project with 2 scenes expecting 120 frames each @ 30fps
            executed_spec = ProjectSpec.model_validate_json(proj_file.read_text())
            from app.models.project import AssetJob
            executed_spec.asset_jobs = [
                AssetJob(id="A001", scene_id="S001", kind="broll", status=JobStatus.ready, output=str(mp1)),
                AssetJob(id="A002", scene_id="S002", kind="broll", status=JobStatus.ready, output=str(mp2)),
            ]
            (task_dir / "project.executed.json").write_text(executed_spec.model_dump_json(), encoding="utf-8")
            (task_dir / "project.planned.json").write_text(executed_spec.model_dump_json(), encoding="utf-8")

            # Mock execution_manifest.json with ready scenes
            exec_manifest = ExecutionManifest(
                schema_version="1.0",
                project_title="Stale Test",
                task_id="test-task",
                source_project_file=str(proj_file),
                source_project_fingerprint="abc",
                status="complete",
                created_at="2026-08-17T00:00:00Z",
                updated_at="2026-08-17T00:00:00Z",
                scenes=[
                    SceneExecutionRecord(
                        scene_id="S001",
                        order=1,
                        status="ready",
                        planned_visual_type=VisualType.broll,
                        resolved_visual_type=VisualType.broll,
                        start=0.0,
                        end=4.0,
                        start_frame=0,
                        end_frame=120,
                        duration_frames=120,
                        output_file=str(mp1.resolve()),
                        source_stage="broll",
                    ),
                    SceneExecutionRecord(
                        scene_id="S002",
                        order=2,
                        status="ready",
                        planned_visual_type=VisualType.broll,
                        resolved_visual_type=VisualType.broll,
                        start=4.0,
                        end=8.0,
                        start_frame=120,
                        end_frame=240,
                        duration_frames=120,
                        output_file=str(mp2.resolve()),
                        source_stage="broll",
                    ),
                ],
            )
            (task_dir / "execution_manifest.json").write_text(exec_manifest.model_dump_json(), encoding="utf-8")

            # Mock probe_media_frames: S001 is STALE (114 frames instead of 120), S002 is OK (120 frames)
            def mock_probe(video_file, fps=30):
                if "S001" in str(video_file):
                    return 114  # Stale!
                return 120

            with patch("app.services.export_runner.utils.task_dir", return_value=str(task_dir)), patch(
                "app.services.export_runner.probe_media_frames", side_effect=mock_probe
            ):
                res = export_editor_package(proj_file, task_id="test-task")

            self.assertEqual(res.status, EditorPackageStatus.failed.value)
            self.assertIn("Stale scene asset S001: expected 120 frames, media contains 114 frames", res.error)
            self.assertIn("Resume production to rerender scene assets", res.error)

    def test_g10_defense_in_depth_blocks_assembly_on_stale_media(self):
        """G10 assemble_final_video fails before video concatenation when physical MP4 is stale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            export_dir = root / "export"
            scenes_dir = export_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)

            sc1_file = scenes_dir / "S001_BROLL.mp4"
            sc2_file = scenes_dir / "S002_BROLL.mp4"
            sc1_file.write_bytes(b"dummy 1")
            sc2_file.write_bytes(b"dummy 2")

            edit_manifest = EditManifest(
                schema_version="1.0",
                project_title="Stale Test",
                project_slug="stale-test",
                task_id="test-task",
                source_project_fingerprint="abc",
                export_fingerprint="def",
                package_status=EditorPackageStatus.complete,
                fps=30,
                resolution=[1920, 1080],
                aspect_ratio="16:9",
                duration_frames=240,
                duration_seconds=8.0,
                narration_file="narration/narration.mp3",
                narration_sha256="hash",
                subtitle_file=None,
                subtitle_sha256=None,
                scenes=[
                    EditorSceneEntry(
                        scene_id="S001",
                        order=1,
                        planned_visual_type=VisualType.broll,
                        resolved_visual_type=VisualType.broll,
                        purpose=VisualPurpose.context,
                        start=0.0,
                        end=4.0,
                        start_frame=0,
                        end_frame=120,
                        duration_frames=120,
                        exported_file="scenes/S001_BROLL.mp4",
                        sha256="sha1",
                    ),
                    EditorSceneEntry(
                        scene_id="S002",
                        order=2,
                        planned_visual_type=VisualType.broll,
                        resolved_visual_type=VisualType.broll,
                        purpose=VisualPurpose.context,
                        start=4.0,
                        end=8.0,
                        start_frame=120,
                        end_frame=240,
                        duration_frames=120,
                        exported_file="scenes/S002_BROLL.mp4",
                        sha256="sha2",
                    ),
                ],
                missing_scenes=[],
                source_provenance=[],
                created_at="2026-08-17T00:00:00Z",
                updated_at="2026-08-17T00:00:00Z",
            )
            (export_dir / "edit_manifest.json").write_text(edit_manifest.model_dump_json(), encoding="utf-8")

            # Mock probe_media_frames: S001 has 114 frames instead of 120
            def mock_probe(video_file, fps=30):
                if "S001" in str(video_file):
                    return 114
                return 120

            with patch("app.services.assembly_runner.probe_media_frames", side_effect=mock_probe):
                with self.assertRaises(ProjectRunError) as ctx:
                    assemble_final_video(export_dir)

            self.assertIn("Final assembly blocked: stale scene media detected. S001: expected 120 frames, actual 114 frames", str(ctx.exception))
            self.assertIn("Resume Production is required", str(ctx.exception))

    def test_broll_re_trims_from_source_on_duration_change(self):
        """B-roll cache invalidation re-trims existing source.mp4 when scene duration increases without redownloading."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            task_dir = root / "task"
            scene_dir = task_dir / "broll" / "S001"
            scene_dir.mkdir(parents=True, exist_ok=True)

            source_file = scene_dir / "source.mp4"
            rendered_file = scene_dir / "rendered.mp4"
            meta_file = scene_dir / "metadata.json"

            source_file.write_bytes(b"dummy source")
            rendered_file.write_bytes(b"dummy rendered")

            # Prior asset recorded 81 frames (2.7s)
            prior_asset = SelectedBrollAsset(
                scene_id="S001",
                candidate_id="cand_1",
                provider="pexels",
                provider_asset_id="123",
                query_used="test query",
                download_url="https://example.com/video.mp4",
                source_duration=10.0,
                trim_start=0.0,
                trim_end=2.7,
                scene_duration=2.7,
                width=1920,
                height=1080,
                score=85.0,
                score_breakdown={},
                metadata={"start_frame": 0, "end_frame": 81, "duration_frames": 81},
                source_file=str(source_file),
                rendered_file=str(rendered_file),
            )
            meta_file.write_text(json.dumps(prior_asset.model_dump(mode="json")), encoding="utf-8")

            # New cue requires 107 frames (3.567s)
            cue = VisualCue(
                id="S001",
                order=1,
                start=0.0,
                end=3.5667,
                narration="EV speech",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="test query").model_dump(mode="json"),
            )
            spec = ProjectSpec(
                schema_version="1.0",
                project=ProjectMetadata(title="Test", aspect_ratio=VideoAspect.landscape, fps=30),
                script=ScriptSpec(subject="EVs", script="EV speech"),
                narration=NarrationSpec(mode="file", file="audio.wav"),
                production=ProductionConfig(),
                timeline_cues=[TimelineCue(id="S001", order=1, start=0.0, end=3.0, narration="EV speech")],
                visual_cues=[cue],
            )

            # Mock get_video_duration to return 10.0s for source.mp4 and 2.7s for old rendered.mp4
            def mock_get_dur(path):
                if "source.mp4" in str(path):
                    return 10.0
                return 2.7

            mock_rendered_dur = [2.7]

            def mock_val(rendered_path, scene_duration, **kwargs):
                file_dur = mock_rendered_dur[0]
                if abs(file_dur - scene_duration) > 0.05:
                    raise ValueError(f"duration mismatch: expected {scene_duration}, got {file_dur}")
                return scene_duration

            def mock_render(source_path, destination_path, scene_duration, **kwargs):
                mock_rendered_dur[0] = scene_duration
                return 10.0, 3.217, 6.783

            context = BrollSelectionContext()

            with patch("app.services.broll.get_video_duration", side_effect=mock_get_dur), patch(
                "app.services.broll.validate_rendered_clip", side_effect=mock_val
            ), patch(
                "app.services.broll.render_scene_clip", side_effect=mock_render
            ) as mock_render_clip, patch(
                "app.services.broll.download_candidate"
            ) as mock_dl:
                asset = acquire_broll_scene(cue, spec, task_dir, context)

                # Verify re-trim was called from source.mp4 without re-downloading
                mock_render_clip.assert_called_once()
                mock_dl.assert_not_called()
                self.assertAlmostEqual(asset.scene_duration, 3.5667, places=2)
                self.assertEqual(asset.metadata.get("duration_frames"), 107)

    def test_production_workflow_propagates_real_orchestrator_error(self):
        """production_workflow propagates the underlying orchestrator_res['error'] without masking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            proj_file = self._create_test_project(root)

            # Mock orchestrator failure with specific error message
            with patch("app.services.production_workflow.run_all_project") as mock_orch:
                mock_orch.return_value = {
                    "status": "failed",
                    "ready_scenes": 0,
                    "failed_scenes": 2,
                    "error": "Planning stage failed: Timeline planning failed: 1 validation error for ProjectSpec",
                }
                res = run_production_workflow(proj_file, output_target="final_video")

                self.assertFalse(res.is_success)
                self.assertEqual(res.failed_stage, "execution")
                self.assertIn("Planning stage failed: Timeline planning failed: 1 validation error for ProjectSpec", res.error)


if __name__ == "__main__":
    unittest.main()
