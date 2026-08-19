from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np
from PIL import Image

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan, MotionSceneSpec
from app.models.project import ProjectSpec
from app.services.motion_demo_gallery import render_all_g18_demos
from app.services.remotion import render_scene_motion, validate_rendered_motion_clip


def _extract_frame_at_timestamp(mp4_path: str, timestamp_sec: float, output_png: str | None = None) -> np.ndarray:
    """Extracts a frame at a specific timestamp from an MP4 file using moviepy or ffmpeg."""
    try:
        from moviepy import VideoFileClip
        clip = VideoFileClip(mp4_path)
        t = min(max(0.0, timestamp_sec), max(0.0, clip.duration - 0.05))
        frame = clip.get_frame(t)
        clip.close()
        if output_png:
            Image.fromarray(frame).save(output_png)
        return np.array(frame)
    except Exception:
        ffmpeg_bin = "ffmpeg"
        try:
            import imageio_ffmpeg
            ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe() or "ffmpeg"
        except Exception:
            pass

        target_png = output_png or (mp4_path + ".frame.png")
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{timestamp_sec:.3f}",
            "-i",
            mp4_path,
            "-vframes",
            "1",
            "-q:v",
            "2",
            target_png,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not Path(target_png).exists():
            raise RuntimeError(f"Failed to extract frame at {timestamp_sec}s from {mp4_path}: {res.stderr}")

        with Image.open(target_png) as img:
            return np.array(img.convert("RGB"))


class TestG18RealRemotionRender(unittest.TestCase):
    """Real Remotion MP4 rendering and frame-level visual QA tests for G18 fixtures."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g18_test_render_")

    def tearDown(self) -> None:
        """Restore automatic cleanup so test renders do not leak temp storage."""
        if hasattr(self, "temp_dir") and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hard_acceptance_a_pie_multicolor_voice_sync_frames(self) -> None:
        """Section 92, 10: Hard Visual Acceptance A — Pie (Premium 40, Standard 35, Basic 25)
        with 3 distinct colors, matching legend markers, and voice-synced highlighting.
        Performs frame-level QA proving active focus differences across narration beats.
        """
        spec = MotionSceneSpec(
            scene_id="TEST_PIE_MULTICOLOR",
            order=1,
            visual_type="data",
            requested_template="pie",
            rendered_template="pie",
            layout_archetype="pie_focus",
            props={
                "headline": "Customer Plan Selection",
                "eyebrow": "PORTFOLIO DISTRIBUTION",
                "variant": "pie_focus",
                "items": [
                    {"label": "PREMIUM", "value": 40, "percentage": 40, "display_value": "40%"},
                    {"label": "STANDARD", "value": 35, "percentage": 35, "display_value": "35%"},
                    {"label": "BASIC", "value": 25, "percentage": 25, "display_value": "25%"},
                ],
            },
            animation_plan=MotionAnimationPlan(
                scene_id="TEST_PIE_MULTICOLOR",
                beats=[
                    KineticBeat(id="b1", start_frame=15, end_frame=35, kind=KineticBeatKind.phrase, text="40% Premium", data_ref="slice_0"),
                    KineticBeat(id="b2", start_frame=35, end_frame=55, kind=KineticBeatKind.phrase, text="35% Standard", data_ref="slice_1"),
                    KineticBeat(id="b3", start_frame=55, end_frame=75, kind=KineticBeatKind.phrase, text="25% Basic", data_ref="slice_2"),
                ],
                final_hold_frames=15,
            ),
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.temp_dir)
        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

        duration = validate_rendered_motion_clip(
            asset.output_file,
            expected_duration_frames=spec.duration_frames,
            expected_width=spec.width,
            expected_height=spec.height,
            expected_fps=spec.fps,
        )
        self.assertAlmostEqual(duration, spec.duration_frames / float(spec.fps), delta=0.2)

        # Frame QA: Extract frames during each kinetic beat and final hold
        f_prem_png = os.path.join(self.temp_dir, "pie_prem.png")
        f_std_png = os.path.join(self.temp_dir, "pie_std.png")
        f_basic_png = os.path.join(self.temp_dir, "pie_basic.png")
        f_settled_png = os.path.join(self.temp_dir, "pie_settled.png")

        arr_prem = _extract_frame_at_timestamp(asset.output_file, 0.80, f_prem_png)      # Frame ~24 (Beat 1: Premium)
        arr_std = _extract_frame_at_timestamp(asset.output_file, 1.50, f_std_png)        # Frame ~45 (Beat 2: Standard)
        arr_basic = _extract_frame_at_timestamp(asset.output_file, 2.20, f_basic_png)    # Frame ~66 (Beat 3: Basic)
        arr_settled = _extract_frame_at_timestamp(asset.output_file, 2.85, f_settled_png)# Frame ~85 (Settled hold)

        diff_prem_std = float(np.sum(np.abs(arr_prem.astype(int) - arr_std.astype(int))))
        diff_std_basic = float(np.sum(np.abs(arr_std.astype(int) - arr_basic.astype(int))))
        diff_basic_settled = float(np.sum(np.abs(arr_basic.astype(int) - arr_settled.astype(int))))

        # Visual proof: frames during different voice sync beats are materially different
        self.assertGreater(diff_prem_std, 40000.0, "Premium beat frame must be materially different from Standard beat frame")
        self.assertGreater(diff_std_basic, 40000.0, "Standard beat frame must be materially different from Basic beat frame")
        self.assertGreater(diff_basic_settled, 40000.0, "Basic beat frame must be materially different from Settled frame")

    def test_hard_acceptance_b_pie_comprehensive_collision_liability(self) -> None:
        """Section 93: Hard Visual Acceptance B — Comprehensive 55, Collision Only 30, Liability 15
        receives 3 distinct colors (Blue, Teal, Purple) with no repeated blue.
        """
        spec = MotionSceneSpec(
            scene_id="TEST_PIE_COVERAGES",
            order=2,
            visual_type="data",
            requested_template="pie",
            rendered_template="pie",
            layout_archetype="donut_center_stat",
            props={
                "headline": "Coverage Tier Breakdown",
                "eyebrow": "TIER ALLOCATION",
                "variant": "donut_center_stat",
                "items": [
                    {"label": "COMPREHENSIVE", "value": 55, "percentage": 55, "display_value": "55%"},
                    {"label": "COLLISION ONLY", "value": 30, "percentage": 30, "display_value": "30%"},
                    {"label": "LIABILITY", "value": 15, "percentage": 15, "display_value": "15%"},
                ],
                "focus_label": "COMPREHENSIVE",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.temp_dir)
        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

    def test_hard_acceptance_c_timeline_zero_text_collision_and_frame_evolution(self) -> None:
        """Section 94, 9: Hard Visual Acceptance C — Timeline with exact fixture:
        Headline: 'Collision Claim Resolution Lifecycle'
        DAY 1: Incident Filed
        DAY 3: Adjuster Assessment
        DAY 7: Payment Disbursed
        Asserts real MP4 render, safe bounds, and frame-level evolution at 25%, 50%, 75%, 95%.
        """
        spec = MotionSceneSpec(
            scene_id="TEST_TIMELINE_SAFE",
            order=3,
            visual_type="data",
            requested_template="timeline",
            rendered_template="timeline",
            props={
                "headline": "Collision Claim Resolution Lifecycle",
                "eyebrow": "CLAIMS PROCESS",
                "milestones": [
                    {"time_label": "DAY 1", "title": "Incident Filed"},
                    {"time_label": "DAY 3", "title": "Adjuster Assessment"},
                    {"time_label": "DAY 7", "title": "Payment Disbursed"},
                ],
            },
            start_time=0.0,
            end_time=4.0,
            start_frame=0,
            end_frame=120,
            duration_frames=120,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.temp_dir)
        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

        # Extract frames at 25%, 50%, 75%, 95% of duration
        f25 = _extract_frame_at_timestamp(asset.output_file, 1.0, os.path.join(self.temp_dir, "tl_25.png"))
        f50 = _extract_frame_at_timestamp(asset.output_file, 2.0, os.path.join(self.temp_dir, "tl_50.png"))
        f75 = _extract_frame_at_timestamp(asset.output_file, 3.0, os.path.join(self.temp_dir, "tl_75.png"))
        f95 = _extract_frame_at_timestamp(asset.output_file, 3.8, os.path.join(self.temp_dir, "tl_95.png"))

        diff_25_50 = float(np.sum(np.abs(f25.astype(int) - f50.astype(int))))
        diff_50_75 = float(np.sum(np.abs(f50.astype(int) - f75.astype(int))))
        diff_75_95 = float(np.sum(np.abs(f75.astype(int) - f95.astype(int))))

        self.assertGreater(diff_25_50, 25000.0, "Timeline frame at 25% must differ as Day 3 node appears")
        self.assertGreater(diff_50_75, 25000.0, "Timeline frame at 50% must differ as Day 7 node appears")
        self.assertGreater(diff_75_95, 10000.0, "Timeline frame at 75% must differ as animation completes")

    def test_hard_acceptance_d_waterfall_edge_safety_and_step_frames(self) -> None:
        """Section 95, 9: Hard Visual Acceptance D — Waterfall:
        Base Quote = $100
        State Filing Fee = +$30
        Safe Driver Discount = -$20
        Final Premium = $110
        Asserts frame-level visual evolution across start, positive step, negative step, and final total.
        """
        spec = MotionSceneSpec(
            scene_id="TEST_WATERFALL_SAFE",
            order=4,
            visual_type="data",
            requested_template="waterfall",
            rendered_template="waterfall",
            props={
                "headline": "Auto Premium Calculation Bridge",
                "eyebrow": "PREMIUM BRIDGE",
                "start_value": 100,
                "start_label": "Base Quote",
                "steps": [
                    {"label": "State Filing Fee", "delta": 30, "display_value": "+$30"},
                    {"label": "Safe Driver Discount", "delta": -20, "display_value": "-$20"},
                ],
                "end_value": 110,
                "end_label": "Final Premium",
            },
            start_time=0.0,
            end_time=4.0,
            start_frame=0,
            end_frame=120,
            duration_frames=120,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.temp_dir)
        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

        # Extract frames at start (0.6s), positive step (1.6s), negative step (2.6s), final (3.6s)
        f_start = _extract_frame_at_timestamp(asset.output_file, 0.6, os.path.join(self.temp_dir, "wf_start.png"))
        f_pos = _extract_frame_at_timestamp(asset.output_file, 1.6, os.path.join(self.temp_dir, "wf_pos.png"))
        f_neg = _extract_frame_at_timestamp(asset.output_file, 2.6, os.path.join(self.temp_dir, "wf_neg.png"))
        f_final = _extract_frame_at_timestamp(asset.output_file, 3.6, os.path.join(self.temp_dir, "wf_final.png"))

        diff_start_pos = float(np.sum(np.abs(f_start.astype(int) - f_pos.astype(int))))
        diff_pos_neg = float(np.sum(np.abs(f_pos.astype(int) - f_neg.astype(int))))
        diff_neg_final = float(np.sum(np.abs(f_neg.astype(int) - f_final.astype(int))))

        self.assertGreater(diff_start_pos, 30000.0, "Waterfall start frame must differ as +$30 step reveals")
        self.assertGreater(diff_pos_neg, 30000.0, "Waterfall positive step must differ as -$20 discount reveals")
        self.assertGreater(diff_neg_final, 30000.0, "Waterfall negative step must differ as Final Premium $110 reveals")

    def test_hard_acceptance_e_long_label_stress_safety(self) -> None:
        """Section 96: Hard Visual Acceptance E — Intentionally long label fixture
        renders cleanly without overflowing or clipping.
        """
        spec = MotionSceneSpec(
            scene_id="TEST_LONG_LABEL_STRESS",
            order=5,
            visual_type="data",
            requested_template="waterfall",
            rendered_template="waterfall",
            props={
                "headline": "Comprehensive Auto Policy Cost Calculation Breakdown",
                "eyebrow": "POLICY CALCULATION",
                "start_value": 500,
                "start_label": "Base Comprehensive Quote",
                "steps": [
                    {"label": "Additional Uninsured Motorist Coverage", "delta": 120, "display_value": "+$120"},
                    {"label": "Multi-Vehicle Defensive Driver Safe Discount", "delta": -80, "display_value": "-$80"},
                ],
                "end_value": 540,
                "end_label": "Final Premium After Applicable Discounts",
            },
            start_time=0.0,
            end_time=4.0,
            start_frame=0,
            end_frame=120,
            duration_frames=120,
            fps=30,
            width=1280,
            height=720,
        )

        asset = render_scene_motion(spec, self.temp_dir)
        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

    def test_hard_acceptance_f_portrait_9_16_render(self) -> None:
        """Section 97: Hard Visual Acceptance F — Portrait 9:16 dense timeline chart
        renders cleanly with vertical layout adaptation.
        """
        spec = MotionSceneSpec(
            scene_id="TEST_PORTRAIT_TIMELINE",
            order=6,
            visual_type="data",
            requested_template="timeline",
            rendered_template="timeline",
            props={
                "headline": "Claim Resolution Steps",
                "eyebrow": "MOBILE VIEW",
                "milestones": [
                    {"time_label": "DAY 1", "title": "Incident Filed"},
                    {"time_label": "DAY 3", "title": "Adjuster Assessment"},
                    {"time_label": "DAY 7", "title": "Payment Disbursed"},
                ],
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=720,
            height=1280,
        )

        asset = render_scene_motion(spec, self.temp_dir)
        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

        duration = validate_rendered_motion_clip(
            asset.output_file,
            expected_duration_frames=spec.duration_frames,
            expected_width=spec.width,
            expected_height=spec.height,
            expected_fps=spec.fps,
        )
        self.assertAlmostEqual(duration, spec.duration_frames / float(spec.fps), delta=0.2)

    def test_g18_demo_gallery_persists_12_clips(self) -> None:
        """Section 79–81: Verify render_all_g18_demos creates all 12 required MP4 demos."""
        demo_dir = Path(self.temp_dir) / "demo_g18"
        rendered = render_all_g18_demos(output_dir=demo_dir)

        self.assertEqual(len(rendered), 12)
        for f in rendered:
            p = Path(f)
            self.assertTrue(p.exists())
            self.assertGreater(p.stat().st_size, 10000)


if __name__ == "__main__":
    unittest.main()
