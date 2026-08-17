import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.models.project import (
    DataPayload,
    DataTemplate,
    NarrationSpec,
    ProjectMetadata,
    ProjectSpec,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_scene_motion


class TestG15MotionSync(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.tmp_dir.name)
        self.project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Kinetic Remotion Test", aspect_ratio=VideoAspect.landscape, fps=30),
            script={"subject": "Kinetic Sync", "script": "Test script"},
            narration=NarrationSpec(mode="file", file="test.wav", timing_file="test.srt"),
            timing_source="user_srt",
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def _extract_frame_array(self, video_path: str | Path, t_seconds: float) -> np.ndarray:
        """Extract a single frame as a numpy RGB array using VideoFileClip."""
        with VideoFileClip(str(video_path)) as clip:
            safe_t = min(float(clip.duration) - 0.05, max(0.0, t_seconds))
            return clip.get_frame(safe_t)

    def test_number_template_animates_counter(self):
        """Number template renders an MP4 where early frames differ from late frames as counter animates."""
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Your collision deductible is one thousand dollars.",
            payload=DataPayload(
                template=DataTemplate.number,
                headline="Deductible",
                data={"value": "$1,000", "numeric_value": 1000.0, "prefix": "$"},
            ).model_dump(mode="json"),
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "number")
        self.assertEqual(spec.animation_plan.timing_source, "user_srt")

        asset = render_scene_motion(spec, task_directory=self.task_dir)
        out_path = Path(asset.output_file)
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 1000)

        # Compare early frame vs late frame
        frame_early = self._extract_frame_array(out_path, 0.3)
        frame_mid = self._extract_frame_array(out_path, 1.2)
        frame_late = self._extract_frame_array(out_path, 2.5)

        # Early vs mid must be visibly different (counter counting up)
        diff_early_mid = np.sum(np.abs(frame_early.astype(int) - frame_mid.astype(int)))
        self.assertGreater(diff_early_mid, 10000, "Early frame and mid frame should differ as counter animates")

        # Mid vs late must be visibly different
        diff_mid_late = np.sum(np.abs(frame_mid.astype(int) - frame_late.astype(int)))
        self.assertGreater(diff_mid_late, 5000, "Mid frame and late frame should differ")

    def test_comparison_sequential_reveal(self):
        """Comparison cards enter sequentially according to beat timings (not all visible at frame 0)."""
        cue = VisualCue(
            id="S002",
            order=2,
            visual_type=VisualType.data,
            purpose=VisualPurpose.compare,
            start=0.0,
            end=4.0,
            narration="Repair costs six thousand dollars, deductible is one thousand dollars, insurance covers five thousand dollars.",
            payload=DataPayload(
                template=DataTemplate.comparison,
                headline="Cost Breakdown",
                data={
                    "items": [
                        {"label": "Repair Cost", "value": "$6,000", "numeric_value": 6000.0},
                        {"label": "Deductible", "value": "$1,000", "numeric_value": 1000.0},
                        {"label": "Insurance", "value": "$5,000", "numeric_value": 5000.0},
                    ]
                },
            ).model_dump(mode="json"),
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "comparison")

        comp_beats = [b for b in spec.animation_plan.beats if b.kind == "comparison_item"]
        self.assertEqual(len(comp_beats), 3)

        asset = render_scene_motion(spec, task_directory=self.task_dir)
        out_path = Path(asset.output_file)
        self.assertTrue(out_path.exists())

        # Extract frames across progression
        f_0 = self._extract_frame_array(out_path, 0.5)   # 1st card in
        f_1 = self._extract_frame_array(out_path, 1.8)   # 2nd card in
        f_2 = self._extract_frame_array(out_path, 3.2)   # 3rd card in

        diff_0_1 = np.sum(np.abs(f_0.astype(int) - f_1.astype(int)))
        diff_1_2 = np.sum(np.abs(f_1.astype(int) - f_2.astype(int)))

        self.assertGreater(diff_0_1, 20000, "Frame 1st card vs 2nd card must show progressive card entrance")
        self.assertGreater(diff_1_2, 20000, "Frame 2nd card vs 3rd card must show progressive card entrance")

    def test_threshold_two_phase_render(self):
        """Threshold template renders two-phase animation (threshold line intro + bar growth past threshold)."""
        cue = VisualCue(
            id="S003",
            order=3,
            visual_type=VisualType.data,
            purpose=VisualPurpose.compare,
            start=0.0,
            end=4.0,
            narration="Your policy limit is twenty-five thousand dollars, but the accident damage totals forty thousand dollars.",
            payload=DataPayload(
                template=DataTemplate.threshold,
                headline="Coverage Limit",
                data={
                    "threshold_value": 25000.0,
                    "current_value": 40000.0,
                    "threshold_label": "Policy Limit",
                    "threshold_display": "$25,000",
                    "current_display": "$40,000",
                },
            ).model_dump(mode="json"),
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "threshold")

        asset = render_scene_motion(spec, task_directory=self.task_dir)
        out_path = Path(asset.output_file)
        self.assertTrue(out_path.exists())

        f_start = self._extract_frame_array(out_path, 0.4)
        f_mid = self._extract_frame_array(out_path, 1.8)
        f_late = self._extract_frame_array(out_path, 3.5)

        diff_start_mid = np.sum(np.abs(f_start.astype(int) - f_mid.astype(int)))
        diff_mid_late = np.sum(np.abs(f_mid.astype(int) - f_late.astype(int)))

        self.assertGreater(diff_start_mid, 15000, "Threshold phase 1 (growth to limit) must show progress")
        self.assertGreater(diff_mid_late, 15000, "Threshold phase 2 (crossing limit) must show progress")

    def test_text_progressive_reveal(self):
        """Text template renders progressive phrase states across narration duration."""
        cue = VisualCue(
            id="S004",
            order=4,
            visual_type=VisualType.text,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="The cheapest policy is not automatically the best policy.",
            payload={"headline": "The cheapest policy is not automatically the best policy."},
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "text")

        asset = render_scene_motion(spec, task_directory=self.task_dir)
        out_path = Path(asset.output_file)
        self.assertTrue(out_path.exists())

        f_early = self._extract_frame_array(out_path, 0.4)
        f_late = self._extract_frame_array(out_path, 2.5)

        diff_text = np.sum(np.abs(f_early.astype(int) - f_late.astype(int)))
        self.assertGreater(diff_text, 10000, "Text scene must show visual differences across phrase reveals")


if __name__ == "__main__":
    unittest.main()
