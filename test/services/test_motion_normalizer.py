from __future__ import annotations

import unittest

from app.models.project import (
    NarrationMode,
    NarrationSpec,
    ProjectMetadata,
    ProjectSpec,
    ScriptSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.motion_normalizer import normalize_motion_spec


def _make_dummy_project(fps: int = 30, aspect: VideoAspect = VideoAspect.landscape) -> ProjectSpec:
    return ProjectSpec(
        schema_version="1.0",
        project=ProjectMetadata(
            title="Test Motion Project",
            aspect_ratio=aspect,
            fps=fps,
        ),
        script=ScriptSpec(
            subject="Test subject",
            script="Hook. Core. Resolution.",
        ),
        narration=NarrationSpec(mode=NarrationMode.tts, voice_name="alloy"),
        timeline_cues=[
            TimelineCue(id="S001", order=1, start=0.0, end=2.0, narration="Scene 1"),
        ],
        visual_cues=[
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=2.0,
                narration="Scene 1",
                payload={"template": "number", "headline": "REVENUE", "data": {"value": "$10,000"}},
            )
        ],
    )


class TestMotionNormalizer(unittest.TestCase):
    def setUp(self):
        self.project = _make_dummy_project()

    def test_normalize_text_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.text,
            purpose=VisualPurpose.emphasis,
            start=1.0,
            end=4.0,
            narration="Text narration",
            payload={"headline": "CHAPTER 1", "subheadline": "THE BEGINNING"},
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.visual_type, "text")
        self.assertEqual(spec.requested_template, "text")
        self.assertEqual(spec.rendered_template, "text")
        self.assertEqual(spec.props["headline"], "CHAPTER 1")
        self.assertEqual(spec.props["subheadline"], "THE BEGINNING")
        self.assertEqual(spec.start_frame, 30)
        self.assertEqual(spec.end_frame, 120)
        self.assertEqual(spec.duration_frames, 90)

    def test_normalize_number_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=2.5,
            narration="Number narration",
            payload={
                "template": "number",
                "headline": "TOTAL SAVINGS",
                "data": {"value": "$50,000", "label": "ANNUAL", "subtext": "Tax-advantaged"},
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "number")
        self.assertEqual(spec.props["value"], "$50,000")
        self.assertEqual(spec.props["numeric_value"], 50000.0)
        self.assertEqual(spec.props["label"], "ANNUAL")

    def test_normalize_counter_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Counter narration",
            payload={
                "template": "counter",
                "headline": "PORTFOLIO GROWTH",
                "data": {"start_value": 1000, "end_value": 50000, "prefix": "$"},
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "counter")
        self.assertEqual(spec.props["end_value"], 50000.0)
        self.assertEqual(spec.props["prefix"], "$")

    def test_normalize_comparison_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.compare,
            start=0.0,
            end=3.0,
            narration="Comparison narration",
            payload={
                "template": "comparison",
                "headline": "TRADITIONAL VS ROTH",
                "data": {
                    "items": [
                        {"label": "Traditional", "value": "$100K"},
                        {"label": "Roth", "value": "$135K", "highlight": True},
                    ]
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "comparison")
        self.assertEqual(len(spec.props["items"]), 2)
        self.assertEqual(spec.props["items"][1]["highlight"], True)

    def test_normalize_timeline_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Timeline narration",
            payload={
                "template": "timeline",
                "headline": "ROADMAP",
                "data": {
                    "milestones": [
                        {"time_label": "2024", "title": "Start"},
                        {"time_label": "2030", "title": "Midpoint"},
                        {"time_label": "2040", "title": "Retire"},
                    ]
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "timeline")
        self.assertEqual(len(spec.props["milestones"]), 3)

    def test_normalize_bar_chart_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Bar chart narration",
            payload={
                "template": "bar_chart",
                "headline": "EXPENSES",
                "data": {
                    "items": [
                        {"label": "Housing", "value": 2500},
                        {"label": "Food", "value": 800},
                    ],
                    "unit": "$",
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "bar_chart")
        self.assertEqual(len(spec.props["items"]), 2)

    def test_normalize_line_chart_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Line chart narration",
            payload={
                "template": "line_chart",
                "headline": "MARKET TREND",
                "data": {
                    "points": [
                        {"x_label": "Year 1", "y_value": 100},
                        {"x_label": "Year 5", "y_value": 180},
                    ]
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "line_chart")
        self.assertEqual(len(spec.props["points"]), 2)

    def test_normalize_threshold_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Threshold narration",
            payload={
                "template": "threshold",
                "headline": "CONTRIBUTION LIMIT",
                "data": {"current_value": 5500, "threshold_value": 7000, "threshold_label": "IRA Limit"},
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "threshold")
        self.assertEqual(spec.props["current_value"], 5500.0)
        self.assertEqual(spec.props["threshold_value"], 7000.0)

    def test_normalize_age_marker_cue(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Age marker narration",
            payload={
                "template": "age_marker",
                "headline": "KEY AGES",
                "data": {
                    "markers": [
                        {"age": 62, "label": "Early SS"},
                        {"age": 65, "label": "Medicare", "highlight": True},
                    ]
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "age_marker")
        self.assertEqual(len(spec.props["markers"]), 2)

    def test_normalize_callout_fallback_on_insufficient_data(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=2.0,
            narration="Fallback narration",
            payload={
                "template": "comparison",
                "headline": "INSUFFICIENT COMPARISON",
                "data": {"items": [{"label": "Single Option", "value": "$100"}]},
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.requested_template, "comparison")
        self.assertEqual(spec.rendered_template, "callout")
        self.assertIsNotNone(spec.fallback_reason)
        self.assertEqual(spec.props["headline"], "INSUFFICIENT COMPARISON")

    def test_numeric_parsing_scales_and_formats(self):
        test_cases = [
            ("$12,000", 12000.0),
            ("$12K", 12000.0),
            ("12k", 12000.0),
            ("$1.5M", 1500000.0),
            ("1.5m", 1500000.0),
            ("2B", 2000000000.0),
            ("2b", 2000000000.0),
            ("5.5%", 5.5),
            ("0", 0.0),
            (0, 0.0),
            (0.0, 0.0),
            ("$0", 0.0),
            ("100", 100.0),
        ]
        for val_str, expected_num in test_cases:
            cue = VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=2.0,
                narration="Scale test",
                payload={"template": "number", "headline": "SCALE TEST", "data": {"value": val_str}},
            )
            spec = normalize_motion_spec(cue, self.project)
            self.assertEqual(spec.rendered_template, "number")
            self.assertEqual(spec.props["numeric_value"], expected_num)
            self.assertEqual(spec.props["value"], str(val_str))

    def test_zero_value_preservation_across_templates(self):
        # Counter with start_value 0 and end_value 0
        cue_counter = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=2.0,
            narration="Zero counter",
            payload={"template": "counter", "headline": "ZERO COUNTER", "data": {"start_value": 0, "end_value": 0}},
        )
        spec_counter = normalize_motion_spec(cue_counter, self.project)
        self.assertEqual(spec_counter.rendered_template, "counter")
        self.assertEqual(spec_counter.props["start_value"], 0.0)
        self.assertEqual(spec_counter.props["end_value"], 0.0)

        # Threshold with current_value 0
        cue_thresh = VisualCue(
            id="S002",
            order=2,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=2.0,
            end=4.0,
            narration="Zero threshold",
            payload={"template": "threshold", "headline": "ZERO THRESH", "data": {"current_value": 0, "threshold_value": 100}},
        )
        spec_thresh = normalize_motion_spec(cue_thresh, self.project)
        self.assertEqual(spec_thresh.rendered_template, "threshold")
        self.assertEqual(spec_thresh.props["current_value"], 0.0)
        self.assertEqual(spec_thresh.props["threshold_value"], 100.0)


if __name__ == "__main__":
    unittest.main()
