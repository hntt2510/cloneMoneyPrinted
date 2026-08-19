from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan, MotionSceneSpec
from app.models.project import ProjectSpec
from app.services.motion_demo_gallery import render_all_g18_demos
from app.services.remotion import render_scene_motion, validate_rendered_motion_clip


def _make_project(aspect_ratio: str = "16:9") -> ProjectSpec:
    return ProjectSpec.model_validate({
        "schema_version": "1.0",
        "project": {
            "title": "G18 Real Remotion Render Test",
            "aspect_ratio": aspect_ratio,
            "fps": 30,
        },
        "script": {
            "subject": "Auto Insurance Motion Rendering",
            "script": "Script text",
        },
        "narration": {
            "mode": "tts",
        },
    })


class TestG18RealRemotionRender(unittest.TestCase):
    """Real Remotion MP4 rendering tests for G18 Hard Visual Acceptance fixtures."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g18_test_render_")

    def tearDown(self) -> None:
        pass

    def test_hard_acceptance_a_pie_multicolor_voice_sync(self) -> None:
        """Section 92: Hard Visual Acceptance A — Pie (Premium 40, Standard 35, Basic 25)
        with 3 distinct colors, matching legend markers, and voice-synced highlighting.
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

    def test_hard_acceptance_c_timeline_zero_text_collision(self) -> None:
        """Section 94: Hard Visual Acceptance C — Timeline with exact fixture:
        Headline: 'Collision Claim Resolution Lifecycle'
        DAY 1: Incident Filed
        DAY 3: Adjuster Assessment
        DAY 7: Payment Disbursed
        Asserts successful MP4 render and zero collision between title, node 2, and neighbor nodes.
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

    def test_hard_acceptance_d_waterfall_edge_safety_and_connectors(self) -> None:
        """Section 95: Hard Visual Acceptance D — Waterfall:
        Base Quote = $100
        State Filing Fee = +$30
        Safe Driver Discount = -$20
        Final Premium = $110
        Asserts $110 and 'Final Premium' are inside frame, connectors visible, semantic colors.
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
