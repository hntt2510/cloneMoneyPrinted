from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan, MotionSceneSpec
from app.services.kinetic_beat_deriver import (
    derive_kinetic_beats,
    resolve_progressive_copy,
    resolve_threshold_copy_state,
)
from app.services.remotion import render_scene_motion, validate_rendered_motion_clip
from test.services.test_g18_real_remotion_render import _extract_frame_at_timestamp


class TestG184ThresholdRebalance(unittest.TestCase):
    """Targeted tests for G18.4 & G18.4.1 Threshold Layout Rebalancing and Voice-Synced Progressive Copy."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g18_4_threshold_test_")

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir") and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_threshold_kinetic_beats_five_phases(self) -> None:
        """Verify that derive_kinetic_beats produces distinct, voice-aligned phases."""
        narration = "The API request limit is ten thousand requests, but traffic reaches fifteen thousand requests."
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=105,
            template="threshold",
            scene_id="S001",
            props={
                "threshold_value": 10000,
                "threshold_display": "10,000",
                "threshold_label": "Request Limit",
                "current_value": 15000,
                "current_display": "15,000",
            },
        )
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.beats), 4)

        limit_beat = plan.beats[0]
        grow_beat = plan.beats[1]
        cross_beat = plan.beats[2]
        resolve_beat = plan.beats[3]

        self.assertEqual(limit_beat.kind, KineticBeatKind.threshold)
        self.assertEqual(grow_beat.kind, KineticBeatKind.number)
        self.assertEqual(cross_beat.kind, KineticBeatKind.highlight)
        self.assertEqual(resolve_beat.kind, KineticBeatKind.resolve)

        self.assertLess(limit_beat.start_frame, grow_beat.start_frame)
        self.assertLess(grow_beat.start_frame, cross_beat.start_frame)
        self.assertLess(cross_beat.start_frame, resolve_beat.start_frame)

    def test_resolve_progressive_copy_word_by_word(self) -> None:
        """Verify that resolve_progressive_copy builds words progressively across frames (no typewriter)."""
        text = "DAMAGE EXCEEDS LIMIT"
        start_f = 68
        end_f = 90

        # Before start
        self.assertEqual(resolve_progressive_copy(text, start_f, end_f, 60), [])

        # Frame 68: First word "DAMAGE" reveals
        self.assertEqual(resolve_progressive_copy(text, start_f, end_f, 68), ["DAMAGE"])

        # Frame 76: Second word "EXCEEDS" reveals
        self.assertEqual(resolve_progressive_copy(text, start_f, end_f, 76), ["DAMAGE", "EXCEEDS"])

        # Frame 85: Third word "LIMIT" reveals (full conclusion)
        self.assertEqual(resolve_progressive_copy(text, start_f, end_f, 85), ["DAMAGE", "EXCEEDS", "LIMIT"])

    def test_threshold_copy_states_deterministic(self) -> None:
        """Assert deterministic copy states across all 5 threshold motion phases."""
        headline = "DAMAGE EXCEEDS LIMIT"
        eyebrow = "PROPERTY DAMAGE LIABILITY"
        threshold_label = "Coverage Limit"
        threshold_value = 25000
        current_value = 40000
        duration_frames = 105

        plan = MotionAnimationPlan(
            scene_id="S_TEST",
            beats=[
                KineticBeat(id="b_limit", start_frame=0, end_frame=20, kind=KineticBeatKind.threshold, text="Limit", data_ref="threshold"),
                KineticBeat(id="b_grow", start_frame=24, end_frame=65, kind=KineticBeatKind.number, text="Current", data_ref="current_value"),
                KineticBeat(id="b_cross", start_frame=68, end_frame=80, kind=KineticBeatKind.highlight, text="cross", data_ref="current_value"),
                KineticBeat(id="b_resolve", start_frame=82, end_frame=98, kind=KineticBeatKind.resolve, text="over", data_ref="resolve"),
            ],
            final_hold_frames=12,
        )

        # State A (Setup / Limit Reveal - Frame 15):
        # Neutral subject shown; conclusion headline is NOT shown.
        s1 = resolve_threshold_copy_state(
            headline, eyebrow, threshold_label, threshold_value, current_value, 15, duration_frames, plan
        )
        self.assertFalse(s1["show_conclusion"])
        self.assertFalse(s1["is_full_conclusion_visible"])
        self.assertEqual(s1["eyebrow"], "COVERAGE LIMIT")
        self.assertIn("PROPERTY", s1["headline_words"])
        self.assertNotIn("EXCEEDS", s1["headline_words"])

        # State C (Bar Growing - Frame 45):
        # Bar is growing; conclusion is still NOT visible.
        s2 = resolve_threshold_copy_state(
            headline, eyebrow, threshold_label, threshold_value, current_value, 45, duration_frames, plan
        )
        self.assertFalse(s2["show_conclusion"])
        self.assertFalse(s2["is_full_conclusion_visible"])
        self.assertEqual(s2["headline_text"], "PROPERTY DAMAGE LIABILITY")

        # State D (Crossing Partial - Frame 70):
        # Bar crossed threshold; conclusion begins revealing word-by-word.
        s3 = resolve_threshold_copy_state(
            headline, eyebrow, threshold_label, threshold_value, current_value, 70, duration_frames, plan
        )
        self.assertTrue(s3["show_conclusion"])
        self.assertEqual(s3["eyebrow"], "LIMIT EXCEEDED")
        self.assertEqual(s3["headline_words"], ["DAMAGE"])
        self.assertFalse(s3["is_full_conclusion_visible"])

        # State E (Resolution - Frame 85+):
        # Full conclusion headline and consequence active.
        s4 = resolve_threshold_copy_state(
            headline, eyebrow, threshold_label, threshold_value, current_value, 85, duration_frames, plan
        )
        self.assertTrue(s4["show_conclusion"])
        self.assertTrue(s4["is_full_conclusion_visible"])
        self.assertEqual(s4["headline_text"], "DAMAGE EXCEEDS LIMIT")
        self.assertTrue(s4["consequence_visible"])

    def test_generic_domain_no_insurance_leakage(self) -> None:
        """Section 10: Test generic API request threshold and assert ZERO insurance domain leakage."""
        headline = "REQUESTS EXCEED LIMIT"
        eyebrow = "API REQUESTS"
        threshold_label = "Request Limit"
        threshold_value = 10000
        current_value = 15000
        duration_frames = 105

        plan = derive_kinetic_beats(
            narration="The API request limit is ten thousand requests, but traffic reaches fifteen thousand requests.",
            fps=30,
            duration_frames=105,
            template="threshold",
            scene_id="S001",
            props={
                "threshold_value": 10000,
                "threshold_display": "10,000",
                "threshold_label": "Request Limit",
                "current_value": 15000,
                "current_display": "15,000",
            },
        )

        forbidden_words = {"POLICY", "INSURANCE", "COVERAGE", "LIABILITY"}

        # Inspect states at frames 10, 40, 75, 95
        for test_frame in [10, 40, 75, 95]:
            state = resolve_threshold_copy_state(
                headline, eyebrow, threshold_label, threshold_value, current_value, test_frame, duration_frames, plan
            )
            combined_text = f"{state['eyebrow']} {state['headline_text']}".upper()
            for forbidden in forbidden_words:
                self.assertNotIn(
                    forbidden,
                    combined_text,
                    f"Forbidden domain keyword '{forbidden}' leaked into generic threshold at frame {test_frame}!",
                )

    def test_threshold_progressive_copy_and_crossing_choreography_render(self) -> None:
        """Real Remotion render test validating:
        1. Clean centered layout and safe bounds.
        2. 5 distinct visual states across rendered frames (01_setup, 02_limit, 03_actual, 04_crossing_partial, 05_conclusion).
        3. Progressive copy reveal and crossing choreography.
        """
        spec = MotionSceneSpec(
            scene_id="S_TEST_THRESH_PROGRESSIVE",
            order=1,
            visual_type="data",
            requested_template="threshold",
            rendered_template="threshold",
            layout_archetype="threshold_v2",
            props={
                "headline": "DAMAGE EXCEEDS LIMIT",
                "eyebrow": "PROPERTY DAMAGE LIABILITY",
                "threshold_value": 25000,
                "threshold_display": "$25,000",
                "threshold_label": "Coverage Limit",
                "current_value": 40000,
                "current_display": "$40,000",
            },
            animation_plan=MotionAnimationPlan(
                scene_id="S_TEST_THRESH_PROGRESSIVE",
                beats=[
                    KineticBeat(id="b_limit", start_frame=0, end_frame=20, kind=KineticBeatKind.threshold, text="Coverage Limit: $25,000", data_ref="threshold"),
                    KineticBeat(id="b_grow", start_frame=24, end_frame=65, kind=KineticBeatKind.number, text="Current: $40,000", data_ref="current_value"),
                    KineticBeat(id="b_cross", start_frame=68, end_frame=80, kind=KineticBeatKind.highlight, text="crossing", data_ref="current_value"),
                    KineticBeat(id="b_resolve", start_frame=82, end_frame=98, kind=KineticBeatKind.resolve, text="OVER LIMIT", data_ref="resolve"),
                ],
                final_hold_frames=12,
                timing_source="user_srt",
                kinetic_timing_source="user_srt_cue_exact+intra_cue_estimated",
            ),
            start_time=0.0,
            end_time=3.5,
            start_frame=0,
            end_frame=105,
            duration_frames=105,
            fps=30,
            width=1920,
            height=1080,
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

        out_path = asset.output_file

        # Extract frames at 5 representative moments:
        # 01_setup: ~0.3s (frame 9)
        # 02_limit: ~0.8s (frame 24)
        # 03_actual: ~1.5s (frame 45)
        # 04_crossing_partial: ~2.35s (frame 70)
        # 05_conclusion: ~3.1s (frame 93)
        f1 = _extract_frame_at_timestamp(str(out_path), 0.3)
        f2 = _extract_frame_at_timestamp(str(out_path), 0.8)
        f3 = _extract_frame_at_timestamp(str(out_path), 1.5)
        f4 = _extract_frame_at_timestamp(str(out_path), 2.35)
        f5 = _extract_frame_at_timestamp(str(out_path), 3.1)

        # Save to permanent QA directory
        qa_dir = Path("storage/uat/insurance_full/qa_frames/rebalanced_threshold")
        qa_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(f1).save(qa_dir / "01_setup.png")
        Image.fromarray(f2).save(qa_dir / "02_limit.png")
        Image.fromarray(f3).save(qa_dir / "03_actual.png")
        Image.fromarray(f4).save(qa_dir / "04_crossing_partial.png")
        Image.fromarray(f5).save(qa_dir / "05_conclusion.png")

        # Assert visual differences across all consecutive stages
        diff_1_2 = float(np.sum(np.abs(f1.astype(int) - f2.astype(int))))
        diff_2_3 = float(np.sum(np.abs(f2.astype(int) - f3.astype(int))))
        diff_3_4 = float(np.sum(np.abs(f3.astype(int) - f4.astype(int))))
        diff_4_5 = float(np.sum(np.abs(f4.astype(int) - f5.astype(int))))

        self.assertGreater(diff_1_2, 35000.0, "01_setup and 02_limit must visually differ (Limit Reveal)")
        self.assertGreater(diff_2_3, 35000.0, "02_limit and 03_actual must visually differ (Bar Growth)")
        self.assertGreater(diff_3_4, 35000.0, "03_actual and 04_crossing_partial must visually differ (Crossing Event)")
        self.assertGreater(diff_4_5, 35000.0, "04_crossing_partial and 05_conclusion must visually differ (Consequence Badge)")


if __name__ == "__main__":
    unittest.main()
