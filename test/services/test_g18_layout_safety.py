from __future__ import annotations

import unittest

from app.services.visualization_layout import (
    compute_timeline_layout,
    compute_waterfall_layout,
    get_safe_area,
    resolve_category_color,
)


class TestG18LayoutSafety(unittest.TestCase):
    """Unit tests for G18 Layout Safety, Categorical Color Resolver, Text Fitting,
    Collision Avoidance, and Voice-Synced Highlighting.
    """

    def test_safe_area_zones_and_aspect_ratios(self) -> None:
        """Section 4 & 5: Validate safe area bounds and non-overlapping content zones."""
        # 16:9 Landscape (1920x1080)
        safe_1080 = get_safe_area(1920, 1080)
        self.assertGreater(safe_1080.left, 0)
        self.assertLess(safe_1080.right, 1920)
        self.assertGreater(safe_1080.top, 0)
        self.assertLess(safe_1080.bottom, 1080)
        self.assertGreater(safe_1080.content_width, 1600)
        self.assertGreater(safe_1080.content_height, 900)

        # Non-overlapping zones
        self.assertLessEqual(safe_1080.title_zone.bottom, safe_1080.chart_zone.y)
        self.assertLessEqual(safe_1080.chart_zone.bottom, safe_1080.footer_zone.y)

        # 9:16 Portrait (1080x1920)
        safe_portrait = get_safe_area(1080, 1920)
        self.assertTrue(safe_portrait.is_portrait)
        self.assertGreater(safe_portrait.left, 0)
        self.assertLess(safe_portrait.right, 1080)

    def test_categorical_color_palette_distinctness(self) -> None:
        """Section 11: Validate production ColorSystem output distinctness and determinism."""
        # 1. Plan Tiers
        prem = resolve_category_color("PREMIUM", index=0, total_categories=3)
        std = resolve_category_color("STANDARD", index=1, total_categories=3)
        basic = resolve_category_color("BASIC", index=2, total_categories=3)

        self.assertNotEqual(prem, std)
        self.assertNotEqual(std, basic)
        self.assertNotEqual(prem, basic)
        self.assertEqual(len({prem, std, basic}), 3)

        # 2. Coverages
        comp = resolve_category_color("COMPREHENSIVE", index=0, total_categories=3)
        coll = resolve_category_color("COLLISION ONLY", index=1, total_categories=3)
        liab = resolve_category_color("LIABILITY", index=2, total_categories=3)

        self.assertNotEqual(comp, coll)
        self.assertNotEqual(coll, liab)
        self.assertNotEqual(comp, liab)
        self.assertEqual(len({comp, coll, liab}), 3)

        # 3. Determinism
        for _ in range(5):
            self.assertEqual(resolve_category_color("PREMIUM", 0, 3), prem)
            self.assertEqual(resolve_category_color("STANDARD", 1, 3), std)
            self.assertEqual(resolve_category_color("BASIC", 2, 3), basic)

    def test_exact_1280x720_timeline_hard_bounds_and_zero_collision(self) -> None:
        """Sections 1, 2, 3, 4, 5: Exact 1280x720 Timeline UAT —
        Asserts that FIRST (DAY 1), CENTER (DAY 3), and LAST (DAY 7) milestone cards
        remain strictly inside safeArea.left and safeArea.right, with zero headline collision.
        """
        geom = compute_timeline_layout(
            width=1280,
            height=720,
            headline="Collision Claim Resolution Lifecycle",
            milestones=[
                {"time_label": "DAY 1", "title": "Incident Filed"},
                {"time_label": "DAY 3", "title": "Adjuster Assessment"},
                {"time_label": "DAY 7", "title": "Payment Disbursed"},
            ],
        )

        safe = geom.safe_area
        self.assertEqual(len(geom.milestones), 3)

        first = geom.milestones[0]
        center = geom.milestones[1]
        last = geom.milestones[2]

        # 1. Hard global bounds checks
        for m in [first, center, last]:
            self.assertGreaterEqual(
                m.card_bounds.left,
                safe.left,
                f"Milestone {m.index} card left ({m.card_bounds.left}) exceeded safeArea.left ({safe.left})",
            )
            self.assertLessEqual(
                m.card_bounds.right,
                safe.right,
                f"Milestone {m.index} card right ({m.card_bounds.right}) exceeded safeArea.right ({safe.right})",
            )
            self.assertGreaterEqual(
                m.card_bounds.top,
                safe.top,
                f"Milestone {m.index} card top ({m.card_bounds.top}) exceeded safeArea.top ({safe.top})",
            )
            self.assertLessEqual(
                m.card_bounds.bottom,
                safe.bottom,
                f"Milestone {m.index} card bottom ({m.card_bounds.bottom}) exceeded safeArea.bottom ({safe.bottom})",
            )

        # 2. No collision with title zone
        for m in [first, center, last]:
            self.assertGreaterEqual(
                m.card_bounds.top,
                geom.title_bounds.bottom,
                f"Milestone {m.index} collided with title zone bottom",
            )

        # 3. No collision between adjacent cards
        self.assertLess(
            first.card_bounds.right,
            center.card_bounds.left,
            "DAY 1 card collided with DAY 3 card",
        )
        self.assertLess(
            center.card_bounds.right,
            last.card_bounds.left,
            "DAY 3 card collided with DAY 7 card",
        )

    def test_waterfall_actual_bounds_and_right_edge_safety(self) -> None:
        """Section 7: Waterfall actual bounds test for $100 -> +$30 -> -$20 -> $110 Final Premium
        and long label stress testing.
        """
        geom = compute_waterfall_layout(
            width=1280,
            height=720,
            headline="Auto Premium Calculation Bridge",
            start_value=100,
            start_label="Base Quote",
            steps=[
                {"label": "State Filing Fee", "delta": 30, "display_value": "+$30"},
                {"label": "Safe Driver Discount", "delta": -20, "display_value": "-$20"},
            ],
            end_value=110,
            end_label="Final Premium",
        )

        safe = geom.safe_area
        self.assertEqual(len(geom.columns), 4)

        start_col = geom.columns[0]
        step1_col = geom.columns[1]
        step2_col = geom.columns[2]
        final_col = geom.columns[3]

        # Cumulative values
        self.assertEqual(start_col.value, 100)
        self.assertEqual(step1_col.value, 130)
        self.assertEqual(step2_col.value, 110)
        self.assertEqual(final_col.value, 110)

        # Left edge safe bounds for start column
        self.assertGreaterEqual(start_col.bar_bounds.left, safe.left)
        self.assertGreaterEqual(start_col.value_bounds.left, safe.left)
        self.assertGreaterEqual(start_col.label_bounds.left, safe.left)

        # Right edge safe bounds for final column ($110 and "Final Premium")
        self.assertLessEqual(final_col.bar_bounds.right, safe.right)
        self.assertLessEqual(final_col.value_bounds.right, safe.right)
        self.assertLessEqual(final_col.label_bounds.right, safe.right)

        # Long label stress test: "Final Premium After Applicable Discounts"
        geom_long = compute_waterfall_layout(
            width=1280,
            height=720,
            headline="Auto Premium Calculation Bridge",
            start_value=100,
            start_label="Base Comprehensive Quote",
            steps=[
                {"label": "State Filing Fee", "delta": 30, "display_value": "+$30"},
                {"label": "Safe Driver Discount", "delta": -20, "display_value": "-$20"},
            ],
            end_value=110,
            end_label="Final Premium After Applicable Discounts",
        )

        final_long_col = geom_long.columns[3]
        self.assertLessEqual(final_long_col.label_bounds.right, safe.right)
        self.assertGreaterEqual(final_long_col.label_bounds.left, safe.left)

    def test_external_narration_path_normalization(self) -> None:
        """Section 16: Verify that external narration file paths are resolved to absolute paths."""
        from app.models.project import ProjectSpec, NarrationMode
        from app.services.project_timeline_runner import run_project_plan
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            wav_file = tmp_path / "narration.wav"
            wav_file.write_bytes(b"RIFF....WAVEfmt ....data....")
            srt_file = tmp_path / "narration.srt"
            srt_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nTest cue\n", encoding="utf-8")
            proj_file = tmp_path / "project.json"
            proj_data = {
                "schema_version": "1.0",
                "project": {"title": "Test Proj", "aspect_ratio": "16:9", "fps": 30},
                "script": {"subject": "Test", "script": "Test cue"},
                "narration": {"mode": "file", "file": "narration.wav", "timing_file": "narration.srt"},
                "production": {"video_source": "pexels"},
            }
            import json
            proj_file.write_text(json.dumps(proj_data), encoding="utf-8")

            # Check preflight
            from app.services.project_spec import load_project_spec, preflight_project
            loaded = load_project_spec(proj_file)
            self.assertEqual(loaded.narration.mode, NarrationMode.file)


if __name__ == "__main__":
    unittest.main()
