from __future__ import annotations

import unittest
from pydantic import ValidationError

from app.models.project import NarrationMode, ProjectSpec
from app.models.schema import VideoAspect, VideoConcatMode, VideoSource, VideoTransitionMode
from app.services.project_builder import build_project_spec_from_ui


class TestProjectBuilder(unittest.TestCase):
    def test_build_project_spec_defaults(self):
        spec = build_project_spec_from_ui(subject="Electric Vehicle Acceleration")
        self.assertIsInstance(spec, ProjectSpec)
        self.assertEqual(spec.schema_version, "1.0")
        self.assertEqual(spec.project.title, "Electric Vehicle Acceleration")
        self.assertEqual(spec.project.aspect_ratio, VideoAspect.landscape)
        self.assertEqual(spec.project.fps, 30)
        self.assertEqual(spec.script.subject, "Electric Vehicle Acceleration")
        self.assertEqual(spec.script.script, "")
        self.assertEqual(spec.narration.mode, NarrationMode.tts)
        self.assertEqual(spec.production.video_source, VideoSource.pexels)
        self.assertTrue(spec.production.subtitle_enabled)

    def test_build_project_spec_custom_options(self):
        spec = build_project_spec_from_ui(
            title="Custom Title",
            subject="Electric Motors",
            script="Direct drive motors have immediate torque.",
            language="zh-CN",
            aspect_ratio="9:16",
            fps=60,
            video_style_preset="cinematic_vlog",
            voice_name="zh-CN-XiaoxiaoNeural",
            voice_rate=1.1,
            voice_volume=0.9,
            subtitle_enabled=False,
            video_source="pixabay",
            n_threads=8,
            search_terms=["ev torque", "electric motor", " "],
            video_clip_duration=7,
            match_materials_to_script=True,
            video_concat_mode="sequential",
            video_transition_mode="FadeIn",
            reference_mode_enabled=True,
            reference_image_sources=["pexels", "pixabay"],
            reference_image_count=5,
        )
        self.assertEqual(spec.project.title, "Custom Title")
        self.assertEqual(spec.project.language, "zh-CN")
        self.assertEqual(spec.project.aspect_ratio, VideoAspect.portrait)
        self.assertEqual(spec.project.fps, 60)
        self.assertEqual(spec.script.script, "Direct drive motors have immediate torque.")
        self.assertEqual(spec.script.search_terms, ["ev torque", "electric motor"])
        self.assertEqual(spec.narration.voice_name, "zh-CN-XiaoxiaoNeural")
        self.assertEqual(spec.narration.voice_rate, 1.1)
        self.assertEqual(spec.narration.voice_volume, 0.9)
        self.assertFalse(spec.production.subtitle_enabled)
        self.assertEqual(spec.production.video_source, VideoSource.pixabay)
        self.assertEqual(spec.production.video_style_preset, "cinematic_vlog")
        self.assertEqual(spec.production.n_threads, 8)
        self.assertEqual(spec.production.video_clip_duration, 7)
        self.assertTrue(spec.production.match_materials_to_script)
        self.assertEqual(spec.production.video_concat_mode, VideoConcatMode.sequential)
        self.assertEqual(spec.production.video_transition_mode, VideoTransitionMode.fade_in)
        self.assertTrue(spec.production.reference_mode_enabled)
        self.assertEqual(spec.production.reference_image_sources, ["pexels", "pixabay"])
        self.assertEqual(spec.production.reference_image_count, 5)

    def test_build_project_spec_file_narration(self):
        spec = build_project_spec_from_ui(
            subject="Audio Narration Test",
            narration_mode="file",
            custom_audio_file="storage/uploads/voice.mp3",
        )
        self.assertEqual(spec.narration.mode, NarrationMode.file)
        self.assertEqual(spec.narration.file, "storage/uploads/voice.mp3")

    def test_build_project_spec_file_narration_missing_file_raises(self):
        with self.assertRaises(ValueError):
            build_project_spec_from_ui(
                subject="Audio Narration Test",
                narration_mode="file",
                custom_audio_file=None,
            )

    def test_build_project_spec_empty_subject_raises(self):
        with self.assertRaises(ValueError):
            build_project_spec_from_ui(subject="   ")

    def test_build_project_spec_local_source_missing_materials_raises(self):
        with self.assertRaises(ValueError):
            build_project_spec_from_ui(
                subject="Local Video Test",
                video_source="local",
                local_materials=[],
            )

    def test_build_project_spec_local_source_with_materials(self):
        spec = build_project_spec_from_ui(
            subject="Local Video Test",
            video_source="local",
            local_materials=["clip1.mp4", "clip2.mp4"],
        )
        self.assertEqual(spec.production.video_source, VideoSource.local)
        self.assertEqual(spec.production.local_materials, ["clip1.mp4", "clip2.mp4"])


if __name__ == "__main__":
    unittest.main()
