import unittest
from app.services.motion_copy_extractor import _truncate_motion_headline, extract_motion_copy
from app.services.kinetic_beat_deriver import derive_kinetic_beats
from app.services.motion_normalizer import normalize_motion_spec
from app.models.project import VisualCue, VisualType

class TestG16MotionStoryboard(unittest.TestCase):
    def test_number_hero_multi_state_beats(self):
        plan = derive_kinetic_beats(
            narration="Suppose repairing your car costs six thousand dollars.",
            fps=30,
            duration_frames=90,
            template="number",
            props={"numeric_value": 6000, "headline": "REPAIR COST"}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertIn("setup", kinds)
        self.assertIn("reveal", kinds)
        self.assertIn("number", kinds)
        self.assertIn("highlight", kinds)
        self.assertGreaterEqual(len(plan.beats), 4)

    def test_headline_not_full_narration(self):
        narration = "Suppose repairing your car costs six thousand dollars which is a lot of money."
        truncated = _truncate_motion_headline(narration)
        self.assertLessEqual(len(truncated.split()), 5)
        self.assertNotEqual(truncated, narration)

    def test_motion_copy_extraction_repair_cost(self):
        mc = extract_motion_copy(
            narration="Suppose repairing your car costs six thousand dollars.",
            payload={"headline": "", "data": {"value": 6000}},
            template="number"
        )
        self.assertEqual(mc.eyebrow, "REPAIR COST")
        self.assertEqual(mc.headline, "TOTAL REPAIR")

    def test_layout_archetype_selection(self):
        from app.models.project import ProjectSpec
        spec_mock = ProjectSpec.model_validate({
            "schema_version": "1.0", "project": {"title": "T", "language": "en", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "S", "script": "S"}, "narration": {"mode": "tts"}, "production": {"video_style_preset": "auto"}
        })
        cue = VisualCue(id="c1", order=1, visual_type=VisualType.data, start=0, end=3, narration="cost 1000", purpose="emphasis", payload={"headline": "H", "template": "number", "data": {"value": 1000}})
        spec = normalize_motion_spec(cue, spec_mock)
        self.assertEqual(spec.layout_archetype, "metric_hero")

    def test_threshold_4phase_beats(self):
        plan = derive_kinetic_beats(
            narration="Your damage is forty thousand but limit is twenty five thousand.",
            fps=30, duration_frames=180, template="threshold",
            props={"threshold_value": 25000, "current_value": 40000}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertIn("threshold", kinds)
        self.assertIn("number", kinds)
        self.assertIn("highlight", kinds)
        self.assertIn("resolve", kinds)

    def test_comparison_2item_divider_beats(self):
        plan = derive_kinetic_beats(
            narration="Compare premium and deductible",
            fps=30, duration_frames=90, template="comparison",
            props={"items": [{"label": "A", "value": "1"}, {"label": "B", "value": "2"}]}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertEqual(kinds.count("comparison_item"), 2)
        self.assertIn("split", kinds)

    def test_counter_beats_multistate(self):
        plan = derive_kinetic_beats(
            narration="Counter goes up to five",
            fps=30, duration_frames=90, template="counter",
            props={"end_value": 5, "headline": "COUNT"}
        )
        kinds = [b.kind for b in plan.beats]
        self.assertIn("setup", kinds)
        self.assertIn("number", kinds)


if __name__ == "__main__":
    unittest.main()
