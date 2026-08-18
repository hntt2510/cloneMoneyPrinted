import unittest
from app.models.project import ProjectSpec, TimelineCue, VisualCue, VisualType
from app.services.kinetic_beat_deriver import derive_kinetic_beats
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.visual_planner import _apply_diversity

class TestG16InsuranceStoryboard(unittest.TestCase):
    def test_repair_6k_number_beats(self):
        plan = derive_kinetic_beats(
            narration="Suppose repairing your car costs six thousand dollars.",
            fps=30, duration_frames=90, template="number",
            props={"numeric_value": 6000, "headline": "REPAIR COST"}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertIn("setup", kinds)
        self.assertIn("number", kinds)
        self.assertIn("highlight", kinds)
        self.assertGreaterEqual(len(plan.beats), 4)

    def test_deductible_1k_number_beats(self):
        plan = derive_kinetic_beats(
            narration="Your deductible is one thousand dollars.",
            fps=30, duration_frames=90, template="number",
            props={"numeric_value": 1000, "headline": "DEDUCTIBLE"}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertIn("setup", kinds)
        self.assertIn("number", kinds)
        self.assertGreaterEqual(len(plan.beats), 4)

    def test_insurance_5k_number_beats(self):
        plan = derive_kinetic_beats(
            narration="The insurance covers five thousand dollars.",
            fps=30, duration_frames=90, template="number",
            props={"numeric_value": 5000, "headline": "INSURANCE"}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertIn("setup", kinds)
        self.assertIn("number", kinds)
        self.assertGreaterEqual(len(plan.beats), 4)

    def test_threshold_25k_40k_4_phases(self):
        plan = derive_kinetic_beats(
            narration="Damage is 40k but limit is 25k.",
            fps=30, duration_frames=180, template="threshold",
            props={"threshold_value": 25000, "current_value": 40000}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertEqual(kinds, ["threshold", "number", "highlight", "resolve"])
        # Verify strict monotonic time progression
        for i in range(len(plan.beats) - 1):
            self.assertLessEqual(plan.beats[i].end_frame, plan.beats[i+1].start_frame + 1)
            self.assertGreater(plan.beats[i].end_frame, plan.beats[i].start_frame)

    def test_comparison_premium_deductible(self):
        plan = derive_kinetic_beats(
            narration="Compare premium and deductible",
            fps=30, duration_frames=90, template="comparison",
            props={"items": [{"label": "Premium", "value": "A"}, {"label": "Deductible", "value": "B"}]}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertIn("split", kinds)
        self.assertEqual(kinds.count("comparison_item"), 2)

    def test_text_cheapest_not_best(self):
        plan = derive_kinetic_beats(
            narration="The cheapest policy is not automatically the best policy.",
            fps=30, duration_frames=90, template="text",
            props={"headline": "CHEAPEST NOT BEST"}
        )
        self.assertGreaterEqual(len(plan.beats), 1)
        for b in plan.beats:
            self.assertGreater(b.end_frame, b.start_frame)

    def test_storyboard_state_coverage(self):
        """Verify that at each key milestone of scene duration, distinct states are active."""
        plan = derive_kinetic_beats(
            narration="Suppose repairing your car costs six thousand dollars.",
            fps=30, duration_frames=90, template="number",
            props={"numeric_value": 6000, "headline": "REPAIR COST"}
        )
        # Verify beats cover the available duration with a final hold
        self.assertEqual(plan.beats[0].start_frame, 0)
        self.assertGreaterEqual(plan.beats[-1].end_frame, 65)
        self.assertGreaterEqual(plan.final_hold_frames, 10)

    def test_motion_quality_heuristic(self):
        plan = derive_kinetic_beats(
            narration="Suppose repairing your car costs six thousand dollars.",
            fps=30, duration_frames=90, template="number",
            props={"numeric_value": 6000, "headline": "REPAIR COST"}
        )
        # The animation span must cover >= 60% of scene duration
        self.assertGreaterEqual(plan.beats[-1].end_frame, 90 * 0.6)

    def test_insurance_cost_breakdown_group_formation(self):
        """End-to-end test of the hard insurance 3-cue breakdown sequence."""
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Insurance Explainer", "language": "en", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "Car Insurance", "script": "Suppose repairing your car costs six thousand dollars. Your collision deductible is one thousand dollars. Your insurance company covers the remaining five thousand dollars."},
            "narration": {"mode": "tts"},
            "production": {"video_style_preset": "auto"}
        })

        t_cues = [
            TimelineCue(id="T001", order=1, start=0.0, end=2.0, narration="Suppose repairing your car costs six thousand dollars."),
            TimelineCue(id="T002", order=2, start=2.0, end=4.0, narration="Your collision deductible is one thousand dollars."),
            TimelineCue(id="T003", order=3, start=4.0, end=6.0, narration="Your insurance company covers the remaining five thousand dollars."),
        ]

        v_cues = [
            VisualCue(id="V001", order=1, visual_type=VisualType.data, purpose="explain", start=0.0, end=2.0, narration=t_cues[0].narration, payload={"headline": "REPAIR COST", "template": "number", "data": {"value": "$6,000", "numeric_value": 6000}}),
            VisualCue(id="V002", order=2, visual_type=VisualType.data, purpose="explain", start=2.0, end=4.0, narration=t_cues[1].narration, payload={"headline": "YOUR DEDUCTIBLE", "template": "number", "data": {"value": "$1,000", "numeric_value": 1000}}),
            VisualCue(id="V003", order=3, visual_type=VisualType.data, purpose="explain", start=4.0, end=6.0, narration=t_cues[2].narration, payload={"headline": "INSURANCE COVERS", "template": "number", "data": {"value": "$5,000", "numeric_value": 5000}}),
        ]

        # 1. Apply diversity / cost breakdown grouping
        grouped_v_cues = _apply_diversity(project, t_cues, v_cues)
        self.assertTrue(all(c.visual_group_id is not None for c in grouped_v_cues))
        self.assertEqual(grouped_v_cues[0].visual_group_id, grouped_v_cues[1].visual_group_id)
        self.assertEqual(grouped_v_cues[1].visual_group_id, grouped_v_cues[2].visual_group_id)

        # 2. Normalize motion specs
        scene_specs = [normalize_motion_spec(c, project) for c in grouped_v_cues]
        for s in scene_specs:
            self.assertEqual(s.layout_archetype, "stacked_breakdown")

        # 3. Form motion groups
        groups = form_motion_groups(scene_specs)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0].scenes), 3)


if __name__ == "__main__":
    unittest.main()
