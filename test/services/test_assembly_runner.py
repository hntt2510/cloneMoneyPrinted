from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.assembly import (
    AssemblyConfig,
    AssemblyManifest,
    AssemblyResult,
    AssemblyStatus,
    AudioMixConfig,
    FinalQCReport,
    SubtitleBurnConfig,
)
from app.models.export import (
    EditManifest,
    EditorPackageStatus,
    EditorSceneEntry,
)
from app.models.project import VisualType
from app.services.assembly_runner import (
    assemble_final_video,
    compute_assembly_fingerprint,
    validate_and_inspect_final_video,
)
from app.services.evidence_sources import compute_file_sha256
from app.services.project_runner import ProjectRunError


class TestAssemblyRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "test-assembly-task-001"
        self.export_dir = Path(self.temp_dir) / "exports" / "test-project"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.scenes_dir = self.export_dir / "scenes"
        self.scenes_dir.mkdir(parents=True, exist_ok=True)
        self.narration_dir = self.export_dir / "narration"
        self.narration_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_mock_edit_manifest(
        self,
        scene_count: int = 3,
        include_narration: bool = True,
        missing_scenes: bool = False,
    ) -> EditManifest:
        scenes: list[EditorSceneEntry] = []
        for i in range(1, scene_count + 1):
            sc_id = f"S{i:03d}"
            sc_rel = f"scenes/{sc_id}_DATA.mp4"
            sc_file = self.export_dir / sc_rel
            # Create a small dummy file
            sc_file.write_bytes(b"dummy video data for " + sc_id.encode())
            sha = compute_file_sha256(sc_file)

            scenes.append(
                EditorSceneEntry(
                    scene_id=sc_id,
                    order=i,
                    planned_visual_type=VisualType.data,
                    resolved_visual_type=VisualType.data,
                    start_frame=(i - 1) * 60,
                    end_frame=i * 60,
                    duration_frames=60,
                    exported_file=sc_rel if not (missing_scenes and i == scene_count) else None,
                    sha256=sha if not (missing_scenes and i == scene_count) else None,
                )
            )

        narr_rel = None
        narr_sha = None
        if include_narration:
            narr_rel = "narration/narration.mp3"
            narr_file = self.export_dir / narr_rel
            narr_file.write_bytes(b"dummy narration audio stream")
            narr_sha = compute_file_sha256(narr_file)

        manifest = EditManifest(
            schema_version="1.0",
            project_title="Assembly Test Project",
            project_slug="test-project",
            task_id=self.task_id,
            source_project_fingerprint="src-fp-12345",
            export_fingerprint="exp-fp-67890",
            package_status=EditorPackageStatus.complete if not missing_scenes else EditorPackageStatus.partial,
            fps=30,
            resolution=[1920, 1080],
            aspect_ratio="16:9",
            duration_frames=scene_count * 60,
            duration_seconds=(scene_count * 60) / 30.0,
            narration_file=narr_rel,
            narration_sha256=narr_sha,
            subtitle_file=None,
            subtitle_sha256=None,
            scenes=scenes,
            source_provenance=[],
            missing_scenes=[f"S{scene_count:03d}"] if missing_scenes else [],
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
            outputs={"export_dir": str(self.export_dir)},
        )

        manifest_file = self.export_dir / "edit_manifest.json"
        manifest_file.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")
        return manifest

    def test_assembly_fingerprint_deterministic_and_sensitive_to_config(self) -> None:
        cfg1 = AssemblyConfig(fps=30, resolution=[1920, 1080], crf=18)
        cfg2 = AssemblyConfig(fps=30, resolution=[1920, 1080], crf=23)  # different CRF
        cfg3 = AssemblyConfig(fps=60, resolution=[1920, 1080], crf=18)  # different FPS

        fp1a = compute_assembly_fingerprint("exp-1", ["sha1", "sha2"], "narr-sha", None, cfg1)
        fp1b = compute_assembly_fingerprint("exp-1", ["sha1", "sha2"], "narr-sha", None, cfg1)
        fp2 = compute_assembly_fingerprint("exp-1", ["sha1", "sha2"], "narr-sha", None, cfg2)
        fp3 = compute_assembly_fingerprint("exp-1", ["sha1", "sha2"], "narr-sha", None, cfg3)

        self.assertEqual(fp1a, fp1b)
        self.assertNotEqual(fp1a, fp2)
        self.assertNotEqual(fp1a, fp3)

    def test_missing_scene_fails_assembly(self) -> None:
        self._create_mock_edit_manifest(scene_count=3, missing_scenes=True)
        manifest_path = self.export_dir / "edit_manifest.json"

        with self.assertRaises(ProjectRunError) as cm:
            assemble_final_video(manifest_path, task_id=self.task_id)

        self.assertIn("missing required scenes", str(cm.exception).lower())

    @patch("app.services.assembly_runner.validate_and_inspect_final_video")
    @patch("app.services.assembly_runner.concatenate_videoclips")
    @patch("app.services.assembly_runner.VideoFileClip")
    @patch("app.services.assembly_runner.AudioFileClip")
    def test_deterministic_3_scene_assembly_flow(
        self,
        mock_audio_clip_cls: MagicMock,
        mock_video_clip_cls: MagicMock,
        mock_concat: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        self._create_mock_edit_manifest(scene_count=3, include_narration=True)
        manifest_path = self.export_dir / "edit_manifest.json"

        # Mock video clips
        mock_scene_clip = MagicMock()
        mock_scene_clip.w = 1920
        mock_scene_clip.h = 1080
        mock_scene_clip.duration = 2.0
        mock_video_clip_cls.return_value = mock_scene_clip

        # Mock concatenated video
        mock_concat_clip = MagicMock()
        mock_concat_clip.duration = 6.0
        mock_concat_clip.w = 1920
        mock_concat_clip.h = 1080

        def fake_write_videofile(filename, **kwargs):
            Path(filename).write_bytes(b"mocked final mp4 stream")

        mock_final_clip = MagicMock()
        mock_final_clip.write_videofile = fake_write_videofile
        mock_concat_clip.with_audio.return_value = mock_final_clip
        mock_concat.return_value = mock_concat_clip

        # Mock QC check
        mock_qc = FinalQCReport(
            is_valid=True,
            final_video_file=str(self.export_dir / "final" / "final.mp4"),
            file_size_bytes=24,
            sha256="final-video-sha",
            duration_seconds=6.0,
            fps=30.0,
            resolution=[1920, 1080],
            has_video_stream=True,
            has_audio_stream=True,
            checks_passed=["video_stream_decoded", "resolution_matches", "fps_matches", "audio_stream_present"],
            errors=[],
        )
        mock_validate.return_value = mock_qc

        result = assemble_final_video(manifest_path, task_id=self.task_id)

        self.assertEqual(result.status, AssemblyStatus.complete.value)
        final_dir = self.export_dir / "final"
        final_mp4 = final_dir / "final.mp4"
        asm_manifest_file = final_dir / "assembly_manifest.json"
        qc_report_file = final_dir / "qc_report.json"

        self.assertTrue(final_mp4.exists())
        self.assertTrue(asm_manifest_file.exists())
        self.assertTrue(qc_report_file.exists())

        # Verify assembly manifest structure
        asm_data = json.loads(asm_manifest_file.read_text(encoding="utf-8"))
        self.assertEqual(asm_data["status"], "complete")
        self.assertEqual(len(asm_data["scenes"]), 3)
        self.assertEqual(asm_data["fps"], 30)
        self.assertEqual(asm_data["resolution"], [1920, 1080])

        # Verify clean scene assets are untouched
        for i in range(1, 4):
            sc_file = self.scenes_dir / f"S{i:03d}_DATA.mp4"
            self.assertTrue(sc_file.exists())

    @patch("app.services.assembly_runner.validate_and_inspect_final_video")
    def test_fingerprint_reuse_skips_rerender(self, mock_validate: MagicMock) -> None:
        self._create_mock_edit_manifest(scene_count=2, include_narration=False)
        manifest_path = self.export_dir / "edit_manifest.json"
        cfg = AssemblyConfig(fps=30, resolution=[1920, 1080])

        final_dir = self.export_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        final_mp4 = final_dir / "final.mp4"
        final_mp4.write_bytes(b"existing final mp4 video content")
        final_sha = compute_file_sha256(final_mp4)

        edit_manifest = EditManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
        scene_shas = [s.sha256 or "" for s in edit_manifest.scenes]
        expected_fp = compute_assembly_fingerprint(
            edit_manifest.export_fingerprint,
            scene_shas,
            None,
            None,
            cfg,
        )

        qc_report = FinalQCReport(
            is_valid=True,
            final_video_file=str(final_mp4),
            file_size_bytes=len(b"existing final mp4 video content"),
            sha256=final_sha,
            duration_seconds=4.0,
            fps=30.0,
            resolution=[1920, 1080],
            has_video_stream=True,
            has_audio_stream=False,
            checks_passed=["all_ok"],
            errors=[],
        )
        (final_dir / "qc_report.json").write_text(json.dumps(qc_report.model_dump(mode="json")), encoding="utf-8")

        asm_manifest = AssemblyManifest(
            schema_version="1.0",
            project_title="Assembly Test Project",
            project_slug="test-project",
            task_id=self.task_id,
            source_project_fingerprint="src-fp-12345",
            edit_manifest_sha256=compute_file_sha256(manifest_path),
            assembly_fingerprint=expected_fp,
            status=AssemblyStatus.complete,
            final_video_file=str(final_mp4),
            final_video_sha256=final_sha,
            duration_seconds=4.0,
            duration_frames=120,
            fps=30,
            resolution=[1920, 1080],
            scenes=[],
            audio_mix=cfg.audio_mix,
            subtitles=cfg.subtitles,
            qc_report=qc_report,
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
            outputs={},
        )
        (final_dir / "assembly_manifest.json").write_text(
            json.dumps(asm_manifest.model_dump(mode="json")), encoding="utf-8"
        )

        # Calling assemble_final_video should return complete without calling video encoders or validate
        res = assemble_final_video(manifest_path, task_id=self.task_id, config=cfg)
        self.assertEqual(res.status, "complete")
        self.assertEqual(res.final_video_file, str(final_mp4.resolve()))
        mock_validate.assert_not_called()

    def test_assembly_rejects_timeline_gaps_before_rendering(self) -> None:
        """Edit manifest with timeline gaps (e.g., 425 scene frames vs 468 duration frames) is rejected pre-render."""
        # Create 4 scenes with gaps matching UAT: 3..117, 123..204, 230..336, 344..468 (total scene frames = 425)
        raw_scene_spans = [(3, 117), (123, 204), (230, 336), (344, 468)]
        scenes: list[EditorSceneEntry] = []
        for i, (s_frame, e_frame) in enumerate(raw_scene_spans, 1):
            sc_id = f"S{i:03d}"
            sc_rel = f"scenes/{sc_id}_DATA.mp4"
            sc_file = self.export_dir / sc_rel
            sc_file.write_bytes(b"dummy video data for " + sc_id.encode())
            sha = compute_file_sha256(sc_file)

            scenes.append(
                EditorSceneEntry(
                    scene_id=sc_id,
                    order=i,
                    planned_visual_type=VisualType.data,
                    resolved_visual_type=VisualType.data,
                    start_frame=s_frame,
                    end_frame=e_frame,
                    duration_frames=e_frame - s_frame,
                    exported_file=sc_rel,
                    sha256=sha,
                )
            )

        manifest = EditManifest(
            schema_version="1.0",
            project_title="Gap Test Project",
            project_slug="test-project",
            task_id=self.task_id,
            source_project_fingerprint="src-fp-12345",
            export_fingerprint="exp-fp-67890",
            package_status=EditorPackageStatus.complete,
            fps=30,
            resolution=[1920, 1080],
            aspect_ratio="16:9",
            duration_frames=468,
            duration_seconds=468 / 30.0,
            narration_file=None,
            scenes=scenes,
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
        )
        manifest_path = self.export_dir / "edit_manifest.json"
        manifest_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")

        with self.assertRaises(ProjectRunError) as ctx:
            assemble_final_video(manifest_path, task_id=self.task_id)

        err_text = str(ctx.exception)
        self.assertIn("Timeline coverage validation failed", err_text)
        self.assertIn("uncovered frames", err_text)
        self.assertIn("43", err_text)

    @patch("app.services.assembly_runner.validate_and_inspect_final_video")
    @patch("app.services.assembly_runner.VideoFileClip")
    @patch("app.services.assembly_runner.concatenate_videoclips")
    def test_assembly_accepts_contiguous_normalized_scenes(
        self,
        mock_concat: MagicMock,
        mock_vfc: MagicMock,
        mock_validate: MagicMock,
    ) -> None:
        """Normalized 468-frame contiguous scene set passes pre-render coverage check."""
        normalized_spans = [(0, 123), (123, 230), (230, 344), (344, 468)]
        scenes: list[EditorSceneEntry] = []
        for i, (s_frame, e_frame) in enumerate(normalized_spans, 1):
            sc_id = f"S{i:03d}"
            sc_rel = f"scenes/{sc_id}_DATA.mp4"
            sc_file = self.export_dir / sc_rel
            sc_file.write_bytes(b"dummy video data for " + sc_id.encode())
            sha = compute_file_sha256(sc_file)

            scenes.append(
                EditorSceneEntry(
                    scene_id=sc_id,
                    order=i,
                    planned_visual_type=VisualType.data,
                    resolved_visual_type=VisualType.data,
                    start_frame=s_frame,
                    end_frame=e_frame,
                    duration_frames=e_frame - s_frame,
                    exported_file=sc_rel,
                    sha256=sha,
                )
            )

        manifest = EditManifest(
            schema_version="1.0",
            project_title="Normalized Assembly Project",
            project_slug="test-project",
            task_id=self.task_id,
            source_project_fingerprint="src-fp-12345",
            export_fingerprint="exp-fp-67890",
            package_status=EditorPackageStatus.complete,
            fps=30,
            resolution=[1920, 1080],
            aspect_ratio="16:9",
            duration_frames=468,
            duration_seconds=15.6,
            narration_file=None,
            scenes=scenes,
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
        )
        manifest_path = self.export_dir / "edit_manifest.json"
        manifest_path.write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")

        mock_clip = MagicMock()
        mock_clip.w = 1920
        mock_clip.h = 1080
        mock_clip.duration = 15.6
        mock_vfc.return_value = mock_clip

        mock_concat_clip = MagicMock()
        mock_concat_clip.duration = 15.6
        mock_concat.return_value = mock_concat_clip

        def fake_write(path, **kwargs):
            Path(path).write_bytes(b"rendered final video content")

        mock_concat_clip.write_videofile.side_effect = fake_write

        mock_validate.return_value = FinalQCReport(
            is_valid=True,
            final_video_file=str(self.export_dir / "final" / "final.mp4"),
            file_size_bytes=len(b"rendered final video content"),
            sha256="final-sha",
            duration_seconds=15.6,
            fps=30.0,
            resolution=[1920, 1080],
            has_video_stream=True,
            has_audio_stream=False,
            checks_passed=["all_ok"],
            errors=[],
        )

        res = assemble_final_video(manifest_path, task_id=self.task_id)
        self.assertEqual(res.status, "complete")
        self.assertIsNotNone(res.final_video_file)


if __name__ == "__main__":
    unittest.main()
