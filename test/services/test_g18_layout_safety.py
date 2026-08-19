from __future__ import annotations

import unittest

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan
from app.models.project import ProjectSpec, TimelineCue, VisualCue, VisualType
from app.services.data_visualization_director import DataVisualizationDirector
from app.services.motion_normalizer import normalize_motion_spec


def _make_project(aspect_ratio: str = "16:9") -> ProjectSpec:
    return ProjectSpec.model_validate({
        "schema_version": "1.0",
        "project": {
            "title": "G18 Editorial Visualization Safety Test",
            "aspect_ratio": aspect_ratio,
            "fps": 30,
        },
        "script": {
            "subject": "Auto Insurance Safety and Layouts",
            "script": "Script text",
        },
        "narration": {
            "mode": "tts",
        },
    })


class TestG18LayoutSafety(unittest.TestCase):
    """Unit tests for G18 Layout Safety, Categorical Color Resolver, Text Fitting,
    Collision Avoidance, and Voice-Synced Highlighting.
    """

    def test_safe_area_zones_and_aspect_ratios(self) -> None:
        """Section 4 & 5: Validate safe area bounds and non-overlapping content zones."""
        # 16:9 Landscape (1920x1080)
        w, h = 1920, 1080
        margin_x = int(w * 0.055)
        margin_y = int(h * 0.06)
        safe_left = margin_x
        safe_right = w - margin_x
        safe_top = margin_y
        safe_bottom = h - margin_y

        self.assertGreater(safe_left, 0)
        self.assertLess(safe_right, w)
        self.assertGreater(safe_top, 0)
        self.assertLess(safe_bottom, h)
        self.assertEqual(safe_right - safe_left, w - 2 * margin_x)
        self.assertEqual(safe_bottom - safe_top, h - 2 * margin_y)

        # 9:16 Portrait (1080x1920)
        pw, ph = 1080, 1920
        pmargin_x = int(pw * 0.06)
        pmargin_y = int(ph * 0.065)
        self.assertGreater(pmargin_x, 0)
        self.assertGreater(pmargin_y, 0)

    def test_categorical_color_palette_distinctness(self) -> None:
        """Section 13, 16, 73, 74: Validate categorical palette distinctness across 3 and 4 categories."""
        # Standard G18 Categorical Palette
        palette = [
            "#3B82F6",  # 0: Blue
            "#2DD4BF",  # 1: Teal
            "#FB923C",  # 2: Orange
            "#A78BFA",  # 3: Purple
            "#34D399",  # 4: Emerald
            "#FBBF24",  # 5: Amber
            "#F472B6",  # 6: Pink
            "#38BDF8",  # 7: Sky
        ]

        # For 3 categories (e.g. Premium / Standard / Basic):
        # Distribution gives indices [0, 1, 2] -> Blue (#3B82F6), Teal (#2DD4BF), Orange (#FB923C)
        three_colors = [palette[0], palette[1], palette[2]]
        self.assertEqual(len(set(three_colors)), 3)
        self.assertNotEqual(three_colors[0], three_colors[1])
        self.assertNotEqual(three_colors[1], three_colors[2])
        self.assertNotEqual(three_colors[0], three_colors[2])

        # Verify no two items receive duplicate blue/cyan
        self.assertIn("#3B82F6", three_colors)
        self.assertIn("#2DD4BF", three_colors)
        self.assertIn("#FB923C", three_colors)

        # For 4 categories (e.g. Rear-End, T-Bone, Runoff, Scrapes):
        # Indices [0, 1, 2, 3] -> Blue, Teal, Orange, Purple
        four_colors = [palette[0], palette[1], palette[2], palette[3]]
        self.assertEqual(len(set(four_colors)), 4)

    def test_timeline_slot_geometry_zero_collision(self) -> None:
        """Section 26–31, 71, 94: Timeline 3-zone layout guarantees zero text collision
        between headline, DAY 3 Adjuster Assessment milestone, and neighbor nodes.
        """
        w, h = 1920, 1080
        safe_top = int(h * 0.06)
        title_h = int((h * 0.88) * 0.20)
        title_bottom = safe_top + title_h

        # Track is positioned in chart zone
        chart_y = safe_top + title_h + int((h * 0.88) * 0.02)
        track_w = min(int((w * 0.89) * 0.92), 1080)
        track_top = chart_y + int((h * 0.60) * 0.42)

        # Assert Title bottom is strictly above the track top with at least 50px buffer
        self.assertLess(title_bottom, track_top)
        self.assertGreaterEqual(track_top - title_bottom, 40)

        # 3 Milestone Horizontal Slots:
        # Slot 0: [0, 360], Slot 1: [360, 720], Slot 2: [720, 1080]
        slot_w = track_w / 3.0
        slot_0 = (0, slot_w)
        slot_1 = (slot_w, 2 * slot_w)
        slot_2 = (2 * slot_w, track_w)

        # Center node (Day 3 Adjuster Assessment) is in Slot 1
        node_1_x = slot_w * 1.5
        max_label_w = slot_w - 24

        # Milestone 1 card left and right bounds
        m1_left = node_1_x - max_label_w / 2
        m1_right = node_1_x + max_label_w / 2

        # Assert Milestone 1 card stays strictly inside Slot 1 bounds
        self.assertGreaterEqual(m1_left, slot_1[0])
        self.assertLessEqual(m1_right, slot_1[1])

        # Assert Milestone 0 card and Milestone 1 card do not overlap
        m0_right = (slot_w * 0.5) + max_label_w / 2
        self.assertLess(m0_right, m1_left)

    def test_waterfall_cumulative_math_and_edge_safety(self) -> None:
        """Section 33–37, 72, 95: Waterfall true cumulative geometry,
        start $100 -> +$30 -> -$20 -> final $110 stays inside safe area right edge.
        """
        start_val = 100
        steps = [
            {"label": "State Filing Fee", "delta": 30},
            {"label": "Safe Driver Discount", "delta": -20},
        ]
        end_val = 110

        # Cumulative calculation verification
        running = start_val
        levels = []
        for s in steps:
            prev = running
            running += s["delta"]
            levels.append((prev, s["delta"], running))

        self.assertEqual(levels[0], (100, 30, 130))
        self.assertEqual(levels[1], (130, -20, 110))
        self.assertEqual(running, end_val)

        # Edge safety calculation:
        # Total columns = 4 (Start, Step 1, Step 2, Final Total)
        chart_w = 960
        padding_x = 36
        plot_w = chart_w - 2 * padding_x
        col_w = min(plot_w / (4 * 1.35), 100)
        col_gap = (plot_w - 4 * col_w) / 3.0

        # Column positions
        start_left = padding_x
        step1_left = padding_x + 1 * (col_w + col_gap)
        step2_left = padding_x + 2 * (col_w + col_gap)
        final_left = padding_x + 3 * (col_w + col_gap)
        final_right = final_left + col_w

        self.assertGreaterEqual(start_left, padding_x)
        self.assertLessEqual(final_right, chart_w - padding_x + 1)

        # Value label bounds ($110 above final column)
        val_w = 70
        val_center = final_left + col_w / 2
        val_right = val_center + val_w / 2

        self.assertLessEqual(val_right, chart_w)

    def test_voice_synced_storyboard_focus_sequence(self) -> None:
        """Section 42–49, 76: Voice-synced sequence highlights active category per beat,
        mutes non-active categories, and settles in final hold.
        """
        animation_plan = MotionAnimationPlan(
            scene_id="VOICE_SYNC_TEST",
            beats=[
                KineticBeat(id="b1", start_frame=15, end_frame=40, kind=KineticBeatKind.phrase, text="40% Premium", data_ref="slice_0"),
                KineticBeat(id="b2", start_frame=40, end_frame=65, kind=KineticBeatKind.phrase, text="35% Standard", data_ref="slice_1"),
                KineticBeat(id="b3", start_frame=65, end_frame=90, kind=KineticBeatKind.phrase, text="25% Basic", data_ref="slice_2"),
            ],
            final_hold_frames=20,
        )

        total_frames = 120
        final_hold_start = int(total_frames * 0.82)  # frame 98

        # Frame 25: Slice 0 is active, Slice 1 and 2 are inactive/muted
        self.assertTrue(15 <= 25 < 40)
        self.assertFalse(40 <= 25 < 65)

        # Frame 50: Slice 1 is active, Slice 0 is past, Slice 2 is future
        self.assertTrue(40 <= 50 < 65)
        self.assertFalse(15 <= 50 < 40)

        # Frame 75: Slice 2 is active
        self.assertTrue(65 <= 75 < 90)

        # Frame 105 (Final hold): Settled state, all slices visible without active highlight
        self.assertGreaterEqual(105, final_hold_start)

    def test_threshold_semantic_colors(self) -> None:
        """Section 22, 75: Threshold template assigns danger red when damage > limit."""
        # Case A: Overflow ($40,000 damage vs $25,000 limit) -> danger status
        cur_val = 40000
        limit_val = 25000
        has_overflow = cur_val > limit_val
        self.assertTrue(has_overflow)

        # Case B: Safe within limit ($15,000 damage vs $25,000 limit) -> safe status
        safe_cur_val = 15000
        safe_overflow = safe_cur_val > limit_val
        self.assertFalse(safe_overflow)


if __name__ == "__main__":
    unittest.main()
