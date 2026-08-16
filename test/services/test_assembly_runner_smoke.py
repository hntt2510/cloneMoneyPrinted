from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from moviepy import ColorClip, VideoFileClip

from app.models.assembly import AssemblyConfig, AssemblyStatus
from app.models.export import EditManifest, EditorPackageStatus, EditorSceneEntry
from app.models.project import VisualType
from app.services.assembly_runner import assemble_final_video, validate_and_inspect_final_video
from app.services.evidence_sources import compute_file_sha256


class TestAssemblyRunnerSmoke(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "smoke-assembly-task-001"
        self.export_dir = Path(self.temp_dir) / "exports" / "smoke-assembly-project"
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.scenes_dir = self.export_dir / "scenes"
        self.scenes_dir.mkdir(parents=True, exist_ok=True)
        self.narration_dir = self.export_dir / "narration"
        self.narration_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_real_moviepy_assembly_smoke(self) -> None:
        # Create 2 real short silent video clips (each 1 second, 1920x1080, 30fps)
        clip1_path = self.scenes_dir / "S001_DATA.mp4"
        clip2_path = self.scenes_dir / "S002_TEXT.mp4"

        c1 = ColorClip(size=(1920, 1080), color=(100, 50, 50), duration=1.0)
        c1.write_videofile(str(clip1_path), fps=30, codec="libx264", logger=None)
        c1.close()

        c2 = ColorClip(size=(1920, 1080), color=(50, 100, 50), duration=1.0)
        c2.write_videofile(str(clip2_path), fps=30, codec="libx264", logger=None)
        c2.close()

        sha1 = compute_file_sha256(clip1_path)
        sha2 = compute_file_sha256(clip2_path)

        # Create dummy narration audio file
        # Using a small sine-wave or silent mp3/wav
        import wave
        import struct

        narr_path = self.narration_dir / "narration.wav"
        with wave.open(str(narr_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            # 2.0 seconds of audio
            frames = bytearray()
            for _ in range(44100 * 2):
                frames.extend(struct.pack("<h", 0))
            wf.writeframes(frames)

        narr_sha = compute_file_sha256(narr_path)

        # Build edit_manifest.json
        scenes = [
            EditorSceneEntry(
                scene_id="S001",
                order=1,
                planned_visual_type=VisualType.data,
                resolved_visual_type=VisualType.data,
                start_frame=0,
                end_frame=30,
                duration_frames=30,
                exported_file="scenes/S001_DATA.mp4",
                sha256=sha1,
            ),
            EditorSceneEntry(
                scene_id="S002",
                order=2,
                planned_visual_type=VisualType.text,
                resolved_visual_type=VisualType.text,
                start_frame=30,
                end_frame=60,
                duration_frames=30,
                exported_file="scenes/S002_TEXT.mp4",
                sha256=sha2,
            ),
        ]

        manifest = EditManifest(
            schema_version="1.0",
            project_title="Smoke Assembly Project",
            project_slug="smoke-assembly-project",
            task_id=self.task_id,
            source_project_fingerprint="src-smoke-fp",
            export_fingerprint="exp-smoke-fp",
            package_status=EditorPackageStatus.complete,
            fps=30,
            resolution=[1920, 1080],
            aspect_ratio="16:9",
            duration_frames=60,
            duration_seconds=2.0,
            narration_file="narration/narration.wav",
            narration_sha256=narr_sha,
            subtitle_file=None,
            subtitle_sha256=None,
            scenes=scenes,
            source_provenance=[],
            missing_scenes=[],
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
            outputs={"export_dir": str(self.export_dir)},
        )

        manifest_file = self.export_dir / "edit_manifest.json"
        manifest_file.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")

        # Execute assembly
        cfg = AssemblyConfig(fps=30, resolution=[1920, 1080], crf=20)
        res = assemble_final_video(manifest_file, task_id=self.task_id, config=cfg)

        self.assertEqual(res.status, AssemblyStatus.complete.value)
        final_mp4 = Path(res.final_video_file)
        self.assertTrue(final_mp4.exists())
        self.assertGreater(final_mp4.stat().st_size, 1000)

        # Inspect final mp4 with VideoFileClip
        final_clip = VideoFileClip(str(final_mp4))
        self.assertEqual(final_clip.w, 1920)
        self.assertEqual(final_clip.h, 1080)
        self.assertAlmostEqual(final_clip.duration, 2.0, delta=0.2)
        self.assertIsNotNone(final_clip.audio)
        final_clip.close()

        # Check QC report
        qc_file = Path(res.qc_report_file)
        self.assertTrue(qc_file.exists())
        qc_data = json.loads(qc_file.read_text(encoding="utf-8"))
        self.assertTrue(qc_data["is_valid"])
        self.assertEqual(qc_data["resolution"], [1920, 1080])
        self.assertTrue(qc_data["has_video_stream"])
        self.assertTrue(qc_data["has_audio_stream"])


if __name__ == "__main__":
    unittest.main()
