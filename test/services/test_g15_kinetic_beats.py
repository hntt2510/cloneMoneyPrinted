import unittest

from app.models.motion import KineticBeatKind
from app.services.kinetic_beat_deriver import derive_kinetic_beats, validate_animation_plan_quality


class TestG15KineticBeats(unittest.TestCase):
    def test_comparison_with_spoken_numbers_mapping(self):
        """Spoken numbers match structured comparison items by canonical numeric value."""
        narration = "Repair costs six thousand dollars, you pay a deductible of one thousand dollars, and insurance covers five thousand dollars."
        props = {
            "items": [
                {"label": "Repair Cost", "value": "$6,000", "numeric_value": 6000.0},
                {"label": "Deductible", "value": "$1,000", "numeric_value": 1000.0},
                {"label": "Insurance", "value": "$5,000", "numeric_value": 5000.0},
            ]
        }
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=150,
            timing_source="user_srt",
            template="comparison",
            scene_id="S010",
            props=props,
        )

        self.assertEqual(plan.timing_source, "user_srt")
        self.assertEqual(plan.kinetic_timing_source, "user_srt_cue_exact+intra_cue_estimated")

        comp_beats = [b for b in plan.beats if b.kind == KineticBeatKind.comparison_item]
        self.assertEqual(len(comp_beats), 3)

        # Check sequential start frames
        self.assertLess(comp_beats[0].start_frame, comp_beats[1].start_frame)
        self.assertLess(comp_beats[1].start_frame, comp_beats[2].start_frame)

        # Check mapping to item references
        self.assertEqual(comp_beats[0].data_ref, "item_0")
        self.assertEqual(comp_beats[1].data_ref, "item_1")
        self.assertEqual(comp_beats[2].data_ref, "item_2")

    def test_conceptual_comparison_without_numbers(self):
        """Comparison between concepts (e.g. Premium vs Deductible) produces item_0 and item_1 beats."""
        narration = "A high premium means lower out-of-pocket costs, while a high deductible lowers your monthly rate."
        props = {
            "items": [
                {"label": "High Premium", "value": "Low Deductible"},
                {"label": "High Deductible", "value": "Low Premium"},
            ]
        }
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=90,
            timing_source="tts",
            template="comparison",
            scene_id="S011",
            props=props,
        )

        comp_beats = [b for b in plan.beats if b.kind == KineticBeatKind.comparison_item]
        self.assertEqual(len(comp_beats), 2)
        self.assertEqual(comp_beats[0].data_ref, "item_0")
        self.assertEqual(comp_beats[1].data_ref, "item_1")
        self.assertLess(comp_beats[0].start_frame, comp_beats[1].start_frame)

    def test_bar_chart_item_beats(self):
        """Bar chart template maps 3 structured bars to 3 chart_item beats in sequential order."""
        narration = "Sedans average thirty miles per gallon, SUVs average twenty-two, and hybrid vehicles exceed fifty."
        props = {
            "items": [
                {"label": "Sedan", "value": 30.0},
                {"label": "SUV", "value": 22.0},
                {"label": "Hybrid", "value": 50.0},
            ]
        }
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=120,
            timing_source="user_srt",
            template="bar_chart",
            scene_id="S012",
            props=props,
        )

        chart_beats = [b for b in plan.beats if b.kind == KineticBeatKind.chart_item]
        self.assertEqual(len(chart_beats), 3)
        self.assertEqual(chart_beats[0].data_ref, "bar_0")
        self.assertEqual(chart_beats[1].data_ref, "bar_1")
        self.assertEqual(chart_beats[2].data_ref, "bar_2")
        self.assertLess(chart_beats[0].start_frame, chart_beats[1].start_frame)
        self.assertLess(chart_beats[1].start_frame, chart_beats[2].start_frame)

    def test_line_chart_points_mapping(self):
        """Line chart points produce chart_item beats."""
        narration = "Prices began at one hundred in January, dropped to eighty in March, and recovered to one twenty by June."
        props = {
            "points": [
                {"x_label": "Jan", "y_value": 100.0},
                {"x_label": "Mar", "y_value": 80.0},
                {"x_label": "Jun", "y_value": 120.0},
            ]
        }
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=120,
            timing_source="user_srt",
            template="line_chart",
            scene_id="S013",
            props=props,
        )

        chart_beats = [b for b in plan.beats if b.kind == KineticBeatKind.chart_item]
        self.assertEqual(len(chart_beats), 3)
        self.assertEqual(chart_beats[0].data_ref, "point_0")
        self.assertEqual(chart_beats[1].data_ref, "point_1")
        self.assertEqual(chart_beats[2].data_ref, "point_2")

    def test_timeline_milestones_mapping(self):
        """Timeline template produces milestone beats."""
        narration = "First submit the claim, second await inspection, and third receive payment."
        props = {
            "milestones": [
                {"time_label": "Step 1", "title": "Submit Claim"},
                {"time_label": "Step 2", "title": "Inspection"},
                {"time_label": "Step 3", "title": "Payment"},
            ]
        }
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=100,
            timing_source="user_srt",
            template="timeline",
            scene_id="S014",
            props=props,
        )

        m_beats = [b for b in plan.beats if b.kind == KineticBeatKind.milestone]
        self.assertEqual(len(m_beats), 3)
        self.assertEqual(m_beats[0].data_ref, "m_0")
        self.assertEqual(m_beats[1].data_ref, "m_1")
        self.assertEqual(m_beats[2].data_ref, "m_2")

    def test_threshold_two_phase_beats(self):
        """Threshold template derives threshold introduction and current/growth phase beats."""
        narration = "Your policy limit is twenty-five thousand dollars, but the accident damage totals forty thousand dollars."
        props = {
            "threshold_value": 25000.0,
            "current_value": 40000.0,
            "threshold_label": "Policy Limit",
        }
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=90,
            timing_source="user_srt",
            template="threshold",
            scene_id="S015",
            props=props,
        )

        thresh_beats = [b for b in plan.beats if b.kind == KineticBeatKind.threshold]
        num_beats = [b for b in plan.beats if b.kind == KineticBeatKind.number]

        self.assertGreaterEqual(len(thresh_beats), 1)
        self.assertGreaterEqual(len(num_beats), 1)
        self.assertEqual(thresh_beats[0].data_ref, "threshold")
        self.assertEqual(num_beats[0].data_ref, "current_value")
        self.assertLess(thresh_beats[0].start_frame, num_beats[0].start_frame)

    def test_number_template_beat(self):
        """Number template extracts canonical number beat with target grounding."""
        narration = "Your deductible is one thousand dollars. Remember to review your comprehensive terms."
        props = {"value": "$1,000", "numeric_value": 1000.0}
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=90,
            timing_source="user_srt",
            template="number",
            scene_id="S016",
            props=props,
        )

        num_beats = [b for b in plan.beats if b.kind == KineticBeatKind.number]
        self.assertEqual(len(num_beats), 1)
        self.assertEqual(num_beats[0].data_ref, "number")

    def test_text_template_phrase_beats(self):
        """Text template derives multiple sequential phrase beats from narration clauses."""
        narration = "The cheapest policy is not automatically the best policy."
        plan = derive_kinetic_beats(
            narration=narration,
            fps=30,
            duration_frames=90,
            timing_source="user_srt",
            template="text",
            scene_id="S017",
            props={"headline": "The cheapest policy is not automatically the best policy."},
        )

        self.assertGreaterEqual(len(plan.beats), 1)
        for b in plan.beats:
            self.assertIn(b.kind, (KineticBeatKind.phrase, KineticBeatKind.takeaway))

    def test_anti_plateau_validator(self):
        """validate_animation_plan_quality detects premature animation completion."""
        # Case 1: Normal healthy distribution
        plan = derive_kinetic_beats(
            narration="Repair costs six thousand dollars, deductible is one thousand, insurance pays five thousand.",
            fps=30,
            duration_frames=120,
            template="comparison",
            scene_id="S018",
            props={"items": [{"label": "A", "value": "1"}, {"label": "B", "value": "2"}]},
        )
        warnings = validate_animation_plan_quality(plan, duration_frames=120)
        self.assertEqual(len(warnings), 0)

        # Case 2: Artificial premature termination
        from app.models.motion import KineticBeat, MotionAnimationPlan
        premature_plan = MotionAnimationPlan(
            scene_id="S019",
            beats=[KineticBeat(id="b0", start_frame=0, end_frame=5, kind=KineticBeatKind.number, text="test")],
            final_hold_frames=10,
        )
        warnings_premature = validate_animation_plan_quality(premature_plan, duration_frames=100)
        self.assertGreater(len(warnings_premature), 0)
        self.assertIn("plateau", warnings_premature[0].lower())


if __name__ == "__main__":
    unittest.main()
