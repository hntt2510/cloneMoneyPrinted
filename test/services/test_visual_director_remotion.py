import json
import unittest
from app.models.motion import MotionSceneSpec
from app.models.project import (
    DataPayload,
    DataTemplate,
    NarrationSpec,
    ProjectMetadata,
    ProjectSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.motion_normalizer import normalize_motion_spec
from app.services.visual_planner import (
    PlannerDecision,
    PlannerError,
    _build_local_context,
    _canonical_visual,
    _fallback_payload,
    _validate_grounded_data,
    classify_narration,
    fallback_visual,
    plan_visuals,
)


def _make_project(script: str = "Test script", search_terms: list[str] | None = None) -> ProjectSpec:
    return ProjectSpec(
        schema_version="1.0",
        project=ProjectMetadata(title="Insurance Breakdown", aspect_ratio=VideoAspect.landscape, fps=30),
        script={
            "subject": "Auto Insurance Claims",
            "script": script,
            "search_terms": search_terms or ["auto insurance", "car accident claim", "deductible coverage"],
        },
        narration=NarrationSpec(mode="tts"),
    )


class TestVisualDirectorRemotion(unittest.TestCase):
    def test_insurance_cost_breakdown_numerical_scene(self):
        """Hard Acceptance Case 2A: Insurance cost breakdown.
        Narration: 'The total repair cost is $6,000. You pay a $1,000 deductible, and the insurer covers the remaining $5,000.'
        Must produce a structured comparison with grounded items, not a generic callout fallback.
        """
        project = _make_project()
        cue = TimelineCue(
            id="S001",
            order=1,
            start=0.0,
            end=5.0,
            narration="The total repair cost is $6,000. You pay a $1,000 deductible, and the insurer covers the remaining $5,000.",
        )

        visual = fallback_visual(project, cue)
        self.assertEqual(visual.visual_type, VisualType.data)
        self.assertEqual(visual.payload.get("template"), "comparison")

        # Verify structured items in fallback payload
        items = visual.payload.get("data", {}).get("items", [])
        self.assertGreaterEqual(len(items), 2)
        values = [it["value"] for it in items]
        self.assertIn("$1,000", values)
        self.assertIn("$5,000", values)

        # Verify normalization creates a valid comparison template
        spec = normalize_motion_spec(visual, project)
        self.assertEqual(spec.rendered_template, "comparison")
        self.assertIsNone(spec.fallback_reason)
        self.assertGreaterEqual(len(spec.props.get("items", [])), 2)

    def test_coverage_limit_threshold_numerical_scene(self):
        """Hard Acceptance Case 2B: Coverage limit vs damage amount.
        Narration: 'If you have a $25,000 property damage coverage limit and cause $40,000 in damage, you exceed your policy limit.'
        Must produce a structured threshold template with grounded current_value and threshold_value.
        """
        project = _make_project()
        cue = TimelineCue(
            id="S002",
            order=2,
            start=5.0,
            end=10.0,
            narration="If you have a $25,000 property damage coverage limit and cause $40,000 in damage, you exceed your policy limit.",
        )

        visual = fallback_visual(project, cue)
        self.assertEqual(visual.visual_type, VisualType.data)
        self.assertEqual(visual.payload.get("template"), "threshold")

        data = visual.payload.get("data", {})
        self.assertEqual(data.get("current_value"), 40000.0)
        self.assertEqual(data.get("threshold_value"), 25000.0)
        self.assertEqual(data.get("threshold_label"), "Coverage Limit")

        # Verify normalization renders threshold
        spec = normalize_motion_spec(visual, project)
        self.assertEqual(spec.rendered_template, "threshold")
        self.assertIsNone(spec.fallback_reason)
        self.assertEqual(spec.props.get("current_value"), 40000.0)
        self.assertEqual(spec.props.get("threshold_value"), 25000.0)

    def test_multi_cue_visual_grouping_grounding(self):
        """Verify cues sharing a visual_group_id ground facts across the entire visual group."""
        cues = [
            TimelineCue(id="S001", order=1, start=0.0, end=3.0, narration="Your comprehensive policy has a $500 deductible."),
            TimelineCue(id="S002", order=2, start=3.0, end=6.0, narration="Hail causes $3,200 in storm damage."),
            TimelineCue(id="S003", order=3, start=6.0, end=9.0, narration="Your insurer pays $2,700 after deductible."),
        ]

        # S003 references $500 (from S001) in its comparison visual
        group_id = "vg_hail_claim"
        decisions = [
            PlannerDecision(id="S001", order=1, visual_type="data", purpose="explain", payload={"template": "number", "headline": "DEDUCTIBLE", "data": {"value": "$500"}}, visual_group_id=group_id),
            PlannerDecision(id="S002", order=2, visual_type="broll", purpose="context", payload={"search_query": "hail storm damage car"}, visual_group_id=group_id),
            PlannerDecision(
                id="S003",
                order=3,
                visual_type="data",
                purpose="compare",
                payload={
                    "template": "comparison",
                    "headline": "CLAIM BREAKDOWN",
                    "data": {
                        "items": [
                            {"label": "Deductible", "value": "$500"},
                            {"label": "Insurance Pays", "value": "$2,700", "highlight": True},
                        ]
                    },
                },
                visual_group_id=group_id,
            ),
        ]

        # Build context for S003 with visual_group_id
        context_grouped = _build_local_context(cues, 2, visual_group_id=group_id, all_decisions=decisions)
        self.assertIn("$500", context_grouped, "Grouped context must include $500 from S001")
        self.assertIn("$2,700", context_grouped, "Grouped context must include $2,700 from S003")

        # Grounding validation must succeed for S003
        _validate_grounded_data(decisions[2], cues[2], context_grouped)

    def test_ungrounded_numeric_facts_are_strictly_rejected(self):
        """Verify fabricated numbers not present in local narration context are rejected."""
        cue = TimelineCue(id="S001", order=1, start=0.0, end=4.0, narration="The repair costs $1,000.")
        decision_fabricated = PlannerDecision(
            id="S001",
            order=1,
            visual_type="data",
            purpose="explain",
            payload={
                "template": "comparison",
                "headline": "COST",
                "data": {
                    "items": [
                        {"label": "Deductible", "value": "$1,000"},
                        {"label": "Invented Claim", "value": "$99,999"},  # Fabricated!
                    ]
                },
            },
        )
        local_context = _build_local_context([cue], 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision_fabricated, cue, local_context)

    def test_all_10_motion_templates_normalization(self):
        """Verify all Remotion motion templates normalize cleanly with typed structured props."""
        project = _make_project()

        # 1. Number
        v_num = VisualCue(id="S001", order=1, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                          payload={"template": "number", "headline": "SAVINGS", "data": {"value": "$250", "prefix": "$", "label": "Annual Savings"}})
        s_num = normalize_motion_spec(v_num, project)
        self.assertEqual(s_num.rendered_template, "number")
        self.assertEqual(s_num.props.get("value"), "$250")

        # 2. Counter
        v_cnt = VisualCue(id="S002", order=2, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                          payload={"template": "counter", "headline": "COVERAGE", "data": {"start_value": 0, "end_value": 50000, "label": "Max Limit"}})
        s_cnt = normalize_motion_spec(v_cnt, project)
        self.assertEqual(s_cnt.rendered_template, "counter")
        self.assertEqual(s_cnt.props.get("end_value"), 50000.0)

        # 3. Comparison
        v_cmp = VisualCue(id="S003", order=3, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.compare,
                          payload={"template": "comparison", "headline": "PLAN A VS B", "data": {"items": [{"label": "Plan A", "value": "$100"}, {"label": "Plan B", "value": "$150"}]}})
        s_cmp = normalize_motion_spec(v_cmp, project)
        self.assertEqual(s_cmp.rendered_template, "comparison")

        # 4. Bar Chart
        v_bar = VisualCue(id="S004", order=4, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                          payload={"template": "bar_chart", "headline": "GROWTH", "data": {"items": [{"label": "Q1", "value": 10}, {"label": "Q2", "value": 20}]}})
        s_bar = normalize_motion_spec(v_bar, project)
        self.assertEqual(s_bar.rendered_template, "bar_chart")

        # 5. Line Chart
        v_line = VisualCue(id="S005", order=5, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                           payload={"template": "line_chart", "headline": "TREND", "data": {"points": [{"x_label": "2020", "y_value": 100}, {"x_label": "2024", "y_value": 200}]}})
        s_line = normalize_motion_spec(v_line, project)
        self.assertEqual(s_line.rendered_template, "line_chart")

        # 6. Timeline
        v_time = VisualCue(id="S006", order=6, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                           payload={"template": "timeline", "headline": "PROCESS", "data": {"milestones": [{"time_label": "Step 1", "title": "File Claim"}, {"time_label": "Step 2", "title": "Adjuster Review"}]}})
        s_time = normalize_motion_spec(v_time, project)
        self.assertEqual(s_time.rendered_template, "timeline")

        # 7. Threshold
        v_thr = VisualCue(id="S007", order=7, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                          payload={"template": "threshold", "headline": "POLICY CAP", "data": {"current_value": 30000, "threshold_value": 25000}})
        s_thr = normalize_motion_spec(v_thr, project)
        self.assertEqual(s_thr.rendered_template, "threshold")

        # 8. Age Marker
        v_age = VisualCue(id="S008", order=8, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                          payload={"template": "age_marker", "headline": "RETIREMENT", "data": {"markers": [{"age": 65, "label": "Medicare"}]}})
        s_age = normalize_motion_spec(v_age, project)
        self.assertEqual(s_age.rendered_template, "age_marker")

        # 9. Callout
        v_call = VisualCue(id="S009", order=9, start=0.0, end=3.0, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                           payload={"template": "callout", "headline": "NOTE", "data": {"emphasis": "IMPORTANT"}})
        s_call = normalize_motion_spec(v_call, project)
        self.assertEqual(s_call.rendered_template, "callout")

        # 10. Text
        v_txt = VisualCue(id="S010", order=10, start=0.0, end=3.0, visual_type=VisualType.text, purpose=VisualPurpose.emphasis,
                          payload={"headline": "SUMMARY", "subheadline": "Final takeaway"})
        s_txt = normalize_motion_spec(v_txt, project)
        self.assertEqual(s_txt.rendered_template, "text")


if __name__ == "__main__":
    unittest.main()
