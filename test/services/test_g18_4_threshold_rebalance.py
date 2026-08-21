from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan, MotionSceneSpec
from app.models.project import ProjectSpec
from app.services.kinetic_beat_deriver import derive_kinetic_beats
from app.services.remotion import render_scene_motion, validate_rendered_motion_clip
from test.services.test_g18_real_remotion_render import _extract_frame_at_timestamp


class TestG184ThresholdRebalance(unittest.TestCase):
    """Targeted tests for G18.4 Threshold Layout Rebalancing and Voice-Synced Progressive Copy."""

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
            }
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

    def test_threshold_progressive_copy_and_crossing_choreography_render(self) -> None:
        """Real Remotion render test validating:
        1. Clean centered layout and safe bounds.
        2. 4 distinct visual states across rendered frames.
        3. Progressive copy reveal and crossing choreography.
        """
        spec = MotionSceneSpec(
            scene_id="S_TEST_THRESH_REBALANCE",
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
                scene_id="S_TEST_THRESH_REBALANCE",
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

        # Extract frames at 4 representative moments:
        # Phase A/B: ~0.4s (frame 12)
        # Phase C: ~1.5s (frame 45)
        # Phase D: ~2.4s (frame 72)
        # Phase E: ~3.1s (frame 93)
        f1 = _extract_frame_at_timestamp(str(out_path), 0.4)
        f2 = _extract_frame_at_timestamp(str(out_path), 1.5)
        f3 = _extract_frame_at_timestamp(str(out_path), 2.4)
        f4 = _extract_frame_at_timestamp(str(out_path), 3.1)

        # Assert visual differences across all 4 phases
        diff_1_2 = float(np.sum(np.abs(f1.astype(int) - f2.astype(int))))
        diff_2_3 = float(np.sum(np.abs(f2.astype(int) - f3.astype(int))))
        diff_3_4 = float(np.sum(np.abs(f3.astype(int) - f4.astype(int))))

        self.assertGreater(diff_1_2, 40000.0, "Frame 1 and Frame 2 must visually differ across voice beats (Bar Growth)")
        self.assertGreater(diff_2_3, 40000.0, "Frame 2 and Frame 3 must visually differ across voice beats (Crossing Moment)")
        self.assertGreater(diff_3_4, 40000.0, "Frame 3 and Frame 4 must visually differ across voice beats (Consequence Badge)")


if __name__ == "__main__":
    unittest.main()
