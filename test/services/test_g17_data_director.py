import unittest

from app.models.motion import (
    SemanticDataIntent,
    VisualGrammar,
)
from app.services.data_visualization_director import (
    DataVisualizationDirector,
    VisualDiversityMemory,
)
from app.services.numeric_parser import extract_canonical_numeric_facts


class TestG17DataVisualizationDirector(unittest.TestCase):
    def setUp(self):
        self.memory = VisualDiversityMemory(max_history=5)
        self.director = DataVisualizationDirector(memory=self.memory)

    def test_uat_case_a_part_to_whole_donut(self):
        """Case A: '40% chose premium, 35% standard, and 25% basic' -> part_to_whole -> pie/donut."""
        narration = "40% chose premium, 35% standard, and 25% basic."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="Plan Selection Breakdown",
            eyebrow="DISTRIBUTION",
            source_cue_id="C001",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.part_to_whole)
        self.assertIn(spec.grammar, (VisualGrammar.pie, VisualGrammar.donut))
        self.assertTrue(len(spec.props.get("items", [])) >= 3)
        self.assertIn(spec.variant, ("donut_center_stat", "donut_reveal", "pie_focus", "segmented_ring"))
        self.assertEqual(spec.confidence, 1.0)

    def test_uat_case_b_trend_over_time_line(self):
        """Case B: 'Premium increased from $120 in 2022 to $180 in 2026' -> trend_over_time -> line."""
        narration = "Premium increased from $120 in 2022 to $180 in 2026."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="5-Year Premium Trend",
            eyebrow="GROWTH",
            source_cue_id="C002",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.trend_over_time)
        self.assertEqual(spec.grammar, VisualGrammar.line)
        self.assertTrue(len(spec.props.get("points", [])) >= 2)
        self.assertIn(spec.variant, ("line_draw", "line_with_points", "line_focus_latest"))

    def test_uat_case_c_category_comparison_bar(self):
        """Case C: 'Plan A $120, Plan B $180, Plan C $230' -> category_comparison -> bar."""
        narration = "Plan A costs $120, Plan B is $180, and Plan C is $230."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="Coverage Tier Pricing",
            eyebrow="COMPARISON",
            source_cue_id="C003",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.category_comparison)
        self.assertEqual(spec.grammar, VisualGrammar.bar)
        self.assertEqual(len(spec.props.get("items", [])), 3)

    def test_uat_case_d_breakdown_stacked_breakdown(self):
        """Case D: '$8K total = $2K deductible + $6K insurer' -> breakdown -> stacked_breakdown."""
        narration = "The total repair cost is $8,000. Your deductible is $2,000 and insurance covers $6,000."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="Repair Cost Breakdown",
            eyebrow="SETTLEMENT",
            source_cue_id="C004",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.breakdown)
        self.assertEqual(spec.grammar, VisualGrammar.breakdown)
        self.assertEqual(spec.variant, "stacked_breakdown")

    def test_uat_case_e_threshold(self):
        """Case E: 'Coverage limit $25K, damage $40K' -> threshold."""
        narration = "Your coverage limit is $25,000, but accident damage reached $40,000."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="Policy Limit vs Actual Damage",
            eyebrow="THRESHOLD",
            source_cue_id="C005",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.threshold)
        self.assertEqual(spec.grammar, VisualGrammar.threshold)
        self.assertEqual(spec.props.get("threshold_value"), 25000)
        self.assertEqual(spec.props.get("current_value"), 40000)

    def test_uat_case_f_progress_gauge(self):
        """Case F: '75% of the process is complete' -> progress -> gauge."""
        narration = "75% of the underwriting process is complete."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="Underwriting Progress",
            eyebrow="STATUS",
            source_cue_id="C006",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.progress)
        self.assertEqual(spec.grammar, VisualGrammar.gauge)
        self.assertEqual(spec.props.get("current_value"), 75)
        self.assertIn(spec.variant, ("radial_gauge", "progress_ring", "linear_meter"))

    def test_uat_case_g_waterfall(self):
        """Case G: 'Started at $100, +$30 fee, -$20 discount, final $110' -> waterfall."""
        narration = "Starting at $100, plus a $30 state fee, minus a $20 discount, resulting in a final rate of $110."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="Rate Calculation Breakdown",
            eyebrow="ADJUSTMENTS",
            source_cue_id="C007",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.positive_negative_change)
        self.assertEqual(spec.grammar, VisualGrammar.waterfall)
        self.assertEqual(spec.props.get("start_value"), 100)
        self.assertEqual(spec.props.get("end_value"), 110)
        self.assertEqual(len(spec.props.get("steps", [])), 2)

    def test_uat_case_h_ranked_list(self):
        """Case H: 'Top 5 claim causes' -> ranked_categories -> ranked_list."""
        narration = "The top 4 claim causes are rear collisions at 38%, T-bones at 27%, runoffs at 21%, and scrapes at 14%."
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="Top Claim Causes",
            eyebrow="RANKINGS",
            source_cue_id="C008",
        )
        self.assertEqual(spec.intent, SemanticDataIntent.ranked_categories)
        self.assertEqual(spec.grammar, VisualGrammar.ranked_list)
        self.assertEqual(len(spec.props.get("items", [])), 4)

    def test_negative_case_limit_damage_rejected_from_pie(self):
        """Negative: $25K limit vs $40K damage must NOT be rendered as a pie chart."""
        narration = "Your coverage limit is $25,000 while total damage is $40,000."
        facts = extract_canonical_numeric_facts(narration)
        is_valid, _, error = self.director.validate_and_build_props(
            grammar=VisualGrammar.pie,
            variant="donut_center_stat",
            intent=SemanticDataIntent.part_to_whole,
            narration=narration,
            facts=facts,
            headline="Limit vs Damage",
        )
        self.assertFalse(is_valid)
        self.assertIn("threshold", error.lower())

    def test_negative_case_time_series_rejected_from_pie(self):
        """Negative: 2022, 2023, 2024 time series must NOT be rendered as a pie chart."""
        narration = "Rates in 2022 were $120, rising in 2024 to $150 and in 2026 to $200."
        facts = extract_canonical_numeric_facts(narration)
        is_valid, _, error = self.director.validate_and_build_props(
            grammar=VisualGrammar.pie,
            variant="donut_center_stat",
            intent=SemanticDataIntent.trend_over_time,
            narration=narration,
            facts=facts,
            headline="Rates over Time",
        )
        self.assertFalse(is_valid)
        self.assertIn("time series", error.lower())

    def test_negative_case_unbounded_scalar_rejected_from_gauge(self):
        """Negative: Single $6000 repair cost without max bound must NOT become a gauge."""
        narration = "Repairing your car costs $6,000."
        facts = extract_canonical_numeric_facts(narration)
        is_valid, _, error = self.director.validate_and_build_props(
            grammar=VisualGrammar.gauge,
            variant="radial_gauge",
            intent=SemanticDataIntent.progress,
            narration=narration,
            facts=facts,
            headline="Repair Cost",
        )
        self.assertFalse(is_valid)
        self.assertIn("unbounded", error.lower())

    def test_negative_case_mismatched_waterfall_arithmetic_rejected(self):
        """Negative: Broken waterfall math (100 + 30 - 20 = 150) must reject and trigger fallback."""
        narration = "Starting at $100, plus a $30 fee, minus a $20 discount, final is $150."
        facts = extract_canonical_numeric_facts(narration)
        is_valid, _, error = self.director.validate_and_build_props(
            grammar=VisualGrammar.waterfall,
            variant="waterfall_steps",
            intent=SemanticDataIntent.positive_negative_change,
            narration=narration,
            facts=facts,
            headline="Mismatched Waterfall",
        )
        self.assertFalse(is_valid)
        self.assertIn("mismatch", error.lower())

    def test_long_form_diversity_simulation_12_cues(self):
        """Simulate an 8-minute explainer with 12 DATA moments, verifying rich rhythm without chart misuse."""
        cue_narrations = [
            ("Repairing your car costs six thousand dollars.", SemanticDataIntent.single_metric, VisualGrammar.metric),
            ("40% chose premium, 35% standard, and 25% basic.", SemanticDataIntent.part_to_whole, VisualGrammar.pie),
            ("Premium increased from $120 in 2022 to $180 in 2026.", SemanticDataIntent.trend_over_time, VisualGrammar.line),
            ("Plan A costs $120, Plan B is $180, and Plan C is $230.", SemanticDataIntent.category_comparison, VisualGrammar.bar),
            ("The total repair is $8,000: $2,000 deductible plus $6,000 insurer.", SemanticDataIntent.breakdown, VisualGrammar.breakdown),
            ("Your coverage limit is $25,000, but accident damage reached $40,000.", SemanticDataIntent.threshold, VisualGrammar.threshold),
            ("80% of claim audits are now completed.", SemanticDataIntent.progress, VisualGrammar.gauge),
            ("Starting at $100, plus a $30 fee, minus a $20 discount, final rate is $110.", SemanticDataIntent.positive_negative_change, VisualGrammar.waterfall),
            ("The top 4 claim causes are rear-end at 38%, T-bone at 27%, runoff at 21%, and scrape at 14%.", SemanticDataIntent.ranked_categories, VisualGrammar.ranked_list),
            ("Cumulative reserves reached $12M in Q1 and $38M in Q4.", SemanticDataIntent.composition_over_time, VisualGrammar.area),
            ("Before policy renewal you paid $140/mo, now you pay $95/mo after switching.", SemanticDataIntent.before_after, VisualGrammar.before_after),
            ("The cheapest policy is not automatically the best policy.", SemanticDataIntent.takeaway, VisualGrammar.kinetic_statement),
        ]

        specs = []
        for idx, (narr, exp_intent, exp_grammar) in enumerate(cue_narrations):
            spec = self.director.direct_visual_specification(
                narration=narr,
                headline=f"Moment {idx + 1}",
                source_cue_id=f"D{idx + 1:02d}",
            )
            specs.append(spec)
            self.assertEqual(spec.intent, exp_intent, f"Cue {idx + 1} intent mismatch")
            self.assertEqual(spec.grammar, exp_grammar, f"Cue {idx + 1} grammar mismatch")

        # Verify diverse grammars across the sequence
        grammars = [s.grammar.value for s in specs]
        unique_grammars = set(grammars)
        self.assertGreaterEqual(len(unique_grammars), 8, f"Expected at least 8 unique grammars in 12 moments, got {len(unique_grammars)}")


if __name__ == "__main__":
    unittest.main()
