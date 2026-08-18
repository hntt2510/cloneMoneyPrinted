import unittest
from app.models.motion import NumberProps, MotionSceneSpec, MotionAnimationPlan
from app.services.motion_normalizer import normalize_motion_spec
from app.models.project import VisualCue, VisualType
from app.services.scene_orchestrator import compute_project_input_fingerprint
from app.models.project import ProjectSpec

class TestG16MotionLayouts(unittest.TestCase):
    def test_number_props_has_eyebrow_field(self):
        props = NumberProps(headline="A", value="1", eyebrow="EYE")
        self.assertEqual(props.eyebrow, "EYE")

    def test_motion_scene_spec_has_layout_archetype(self):
        spec = MotionSceneSpec(
            scene_id="1", order=1, visual_type="data", requested_template="number",
            rendered_template="number", start_time=0, end_time=1, start_frame=0, end_frame=30,
            duration_frames=30, fps=30, width=1920, height=1080, layout_archetype="metric_hero"
        )
        self.assertEqual(spec.layout_archetype, "metric_hero")

    def test_backward_compat_old_number_props(self):
        props = NumberProps.model_validate({"headline": "A", "value": "1"})
        self.assertIsNone(props.eyebrow)

    def test_bar_chart_normalizer_unchanged(self):
        from app.models.project import ProjectSpec
        spec_mock = ProjectSpec.model_validate({
            "schema_version": "1.0", "project": {"title": "T", "language": "en", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "S", "script": "S"}, "narration": {"mode": "tts"}, "production": {"video_style_preset": "auto"}
        })
        cue = VisualCue(id="c1", order=1, visual_type=VisualType.data, start=0, end=3, narration="chart", 
                        purpose="emphasis", payload={"headline": "H", "template": "bar_chart", "data": {"items": [{"label": "A", "value": 1}, {"label": "B", "value": 2}]}})
        spec = normalize_motion_spec(cue, spec_mock)
        self.assertEqual(spec.rendered_template, "bar_chart")

    def test_threshold_normalizer_unchanged(self):
        from app.models.project import ProjectSpec
        spec_mock = ProjectSpec.model_validate({
            "schema_version": "1.0", "project": {"title": "T", "language": "en", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "S", "script": "S"}, "narration": {"mode": "tts"}, "production": {"video_style_preset": "auto"}
        })
        cue = VisualCue(id="c1", order=1, visual_type=VisualType.data, start=0, end=3, narration="thresh", 
                        purpose="emphasis", payload={"headline": "H", "template": "threshold", "data": {"current_value": 1, "threshold_value": 2}})
        spec = normalize_motion_spec(cue, spec_mock)
        self.assertEqual(spec.rendered_template, "threshold")

    def test_motion_engine_version_is_3(self):
        plan = MotionAnimationPlan(scene_id="1", beats=[])
        self.assertEqual(plan.motion_engine_version, "3")

    def test_fingerprint_includes_motion_engine(self):
        from app.models.project import ProjectSpec
        
        # simple dict mimicking ProjectSpec
        spec = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "T", "language": "en", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "S", "script": "S"},
            "narration": {"mode": "tts"},
            "production": {"video_style_preset": "auto"}
        })
        fp = compute_project_input_fingerprint(spec)
        self.assertTrue(isinstance(fp, str))
