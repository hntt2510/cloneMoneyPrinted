import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.models.motion import (
    KineticBeat,
    KineticBeatKind,
    MotionAnimationPlan,
    MotionSceneSpec,
)
from app.services.remotion import render_scene_motion


def _extract_frame_rgb(video_path: str, timestamp_s: float) -> np.ndarray:
    """Extract RGB frame array from video at exact timestamp using imageio/moviepy."""
    from moviepy.video.io.VideoFileClip import VideoFileClip

    clip = VideoFileClip(video_path)
    frame = clip.get_frame(timestamp_s)
    clip.close()
    return np.array(frame, dtype=np.int32)


class TestG17RealRemotionRender(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="g17_remotion_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_render_donut_chart_visual_evolution(self):
        """Render Donut chart and verify visual evolution across entrance, slice reveal, and center focus."""
        spec = MotionSceneSpec(
            scene_id="TEST_DONUT",
            order=1,
            visual_type="data",
            requested_template="pie",
            rendered_template="pie",
            layout_archetype="donut_center_stat",
            props={
                "headline": "Plan Market Share",
                "eyebrow": "PORTFOLIO",
                "variant": "donut_center_stat",
                "layout_archetype": "donut_center_stat",
                "items": [
                    {"label": "Premium", "value": 40, "percentage": 40, "display_value": "40%", "highlight": True},
                    {"label": "Standard", "value": 35, "percentage": 35, "display_value": "35%", "highlight": False},
                    {"label": "Basic", "value": 25, "percentage": 25, "display_value": "25%", "highlight": False},
                ],
                "focus_label": "Premium",
            },
            start_time=0.0,
            end_time=2.5,
            start_frame=0,
            end_frame=75,
            duration_frames=75,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.tmp_dir)
        self.assertTrue(Path(asset.output_file).exists())
        self.assertEqual(asset.width, 1280)
        self.assertEqual(asset.height, 720)

        # Extract frames at 0.3s (early ring entrance), 1.2s (slices drawn), 2.2s (center stat resolved)
        f_early = _extract_frame_rgb(asset.output_file, 0.3)
        f_mid = _extract_frame_rgb(asset.output_file, 1.2)
        f_late = _extract_frame_rgb(asset.output_file, 2.2)

        # Visual difference assertion
        diff_early_mid = np.sum(np.abs(f_mid - f_early))
        diff_mid_late = np.sum(np.abs(f_late - f_mid))

        self.assertGreater(diff_early_mid, 50_000, "Donut should evolve significantly between early entrance and mid reveal")
        self.assertGreater(diff_mid_late, 20_000, "Donut center focus should evolve between mid and late hold")

    def test_render_gauge_visual_evolution(self):
        """Render Radial Gauge and verify track reveal and arc fill progression."""
        spec = MotionSceneSpec(
            scene_id="TEST_GAUGE",
            order=1,
            visual_type="data",
            requested_template="gauge",
            rendered_template="gauge",
            layout_archetype="radial_gauge",
            props={
                "headline": "Underwriting Verification",
                "eyebrow": "PROGRESS",
                "current_value": 75,
                "max_value": 100,
                "min_value": 0,
                "display_value": "75%",
                "unit": "%",
                "label": "Audit Complete",
                "variant": "radial_gauge",
                "layout_archetype": "radial_gauge",
            },
            start_time=0.0,
            end_time=2.5,
            start_frame=0,
            end_frame=75,
            duration_frames=75,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.tmp_dir)
        self.assertTrue(Path(asset.output_file).exists())

        f_early = _extract_frame_rgb(asset.output_file, 0.3)
        f_mid = _extract_frame_rgb(asset.output_file, 1.3)
        f_late = _extract_frame_rgb(asset.output_file, 2.2)

        diff_early_mid = np.sum(np.abs(f_mid - f_early))
        self.assertGreater(diff_early_mid, 50_000, "Gauge arc and counter should animate actively between 0.3s and 1.3s")

    def test_render_waterfall_visual_evolution(self):
        """Render Waterfall chart and verify sequential floating step appearance."""
        spec = MotionSceneSpec(
            scene_id="TEST_WATERFALL",
            order=1,
            visual_type="data",
            requested_template="waterfall",
            rendered_template="waterfall",
            layout_archetype="waterfall_steps",
            props={
                "headline": "Policy Rate Calculation",
                "eyebrow": "ADJUSTMENTS",
                "start_value": 100,
                "start_label": "Base Quote",
                "steps": [
                    {"label": "State Filing Fee", "delta": 30, "display_value": "+$30"},
                    {"label": "Safe Driver Discount", "delta": -20, "display_value": "-$20"},
                ],
                "end_value": 110,
                "end_label": "Final Rate",
                "variant": "waterfall_steps",
                "layout_archetype": "waterfall_steps",
            },
            start_time=0.0,
            end_time=2.5,
            start_frame=0,
            end_frame=75,
            duration_frames=75,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.tmp_dir)
        self.assertTrue(Path(asset.output_file).exists())

        f_early = _extract_frame_rgb(asset.output_file, 0.3)
        f_mid = _extract_frame_rgb(asset.output_file, 1.2)
        f_late = _extract_frame_rgb(asset.output_file, 2.2)

        diff_early_mid = np.sum(np.abs(f_mid - f_early))
        diff_mid_late = np.sum(np.abs(f_late - f_mid))
        self.assertGreater(diff_early_mid, 50_000, "Waterfall start bar -> floating delta evolution")
        self.assertGreater(diff_mid_late, 30_000, "Waterfall delta -> final total column resolution")

    def test_render_ranked_list_visual_evolution(self):
        """Render Ranked List and verify staggered row entry."""
        spec = MotionSceneSpec(
            scene_id="TEST_RANKED",
            order=1,
            visual_type="data",
            requested_template="ranked_list",
            rendered_template="ranked_list",
            layout_archetype="ranked_horizontal_bars",
            props={
                "headline": "Top Claim Causes",
                "eyebrow": "RANKINGS",
                "variant": "ranked_horizontal_bars",
                "layout_archetype": "ranked_horizontal_bars",
                "items": [
                    {"rank": 1, "label": "Rear-End", "value": 38, "display_value": "38%", "highlight": True},
                    {"rank": 2, "label": "T-Bone", "value": 27, "display_value": "27%", "highlight": False},
                    {"rank": 3, "label": "Runoff", "value": 21, "display_value": "21%", "highlight": False},
                ],
            },
            start_time=0.0,
            end_time=2.5,
            start_frame=0,
            end_frame=75,
            duration_frames=75,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.tmp_dir)
        self.assertTrue(Path(asset.output_file).exists())

        f_early = _extract_frame_rgb(asset.output_file, 0.3)
        f_mid = _extract_frame_rgb(asset.output_file, 1.4)
        diff_early_mid = np.sum(np.abs(f_mid - f_early))
        self.assertGreater(diff_early_mid, 50_000, "Ranked list items should stagger in actively")


if __name__ == "__main__":
    unittest.main()
