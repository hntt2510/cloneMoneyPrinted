from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.models.motion import MotionSceneSpec
from app.models.project import (
    DataPayload,
    DataTemplate,
    ProjectSpec,
    TimelineCue,
    VisualCue,
    VisualPlan,
    VisualPurpose,
    VisualType,
)
from app.services.data_visualization_director import DataVisualizationDirector
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_scene_motion
from app.services.visual_planner import adapt_data_visual_cue, plan_visuals


def _make_project(title: str = "Semantic Arbitration Project") -> ProjectSpec:
    return ProjectSpec.model_validate({
        "schema_version": "1.0",
        "project": {
            "title": title,
            "aspect_ratio": "16:9",
            "fps": 30,
        },
        "script": {
            "subject": "Auto Insurance Overview",
            "script": "Script body",
        },
        "narration": {
            "mode": "tts",
        },
    })


class TestG17SemanticArbitration(unittest.TestCase):
    """G17 Final Semantic Arbitration Hotfix Tests.
    Verifies that DataVisualizationDirector owns the final semantic visualization decision
    on the normal successful LLM planner path without relying on fallback_visual.
    """

    def test_hard_case_a_successful_llm_bar_to_pie_remotion(self):
        """Hard Acceptance Case A (Section 10):
        Narration: '40% chose Premium, 35% Standard, and 25% Basic.'
        Mock LLM returns: visual_type = DATA, template = bar_chart (semantically suboptimal).
        Final production result MUST override to: intent = part_to_whole, grammar = pie/donut.
        Then normalize -> real Remotion render -> valid MP4.
        """
        project = _make_project()
        cue = TimelineCue(
            id="S001",
            order=1,
            start=0.0,
            end=5.0,
            narration="40% chose Premium, 35% Standard, and 25% Basic.",
        )

        def mock_llm_response(prompt: str) -> str:
            return json.dumps({
                "cues": [
                    {
                        "id": "S001",
                        "order": 1,
                        "visual_type": "data",
                        "purpose": "compare",
                        "payload": {
                            "template": "bar_chart",
                            "headline": "TIER DISTRIBUTION",
                            "data": {
                                "items": [
                                    {"label": "Premium", "value": 40},
                                    {"label": "Standard", "value": 35},
                                    {"label": "Basic", "value": 25},
                                ]
                            },
                        },
                    }
                ]
            })

        director = DataVisualizationDirector()
        planned = plan_visuals(
            project=project,
            timeline_cues=[cue],
            response_fn=mock_llm_response,
            director=director,
        )

        self.assertEqual(len(planned), 1)
        res_cue = planned[0]
        self.assertEqual(res_cue.visual_type, VisualType.data)
        # Verify LLM's bar_chart was overridden to pie / donut
        self.assertIn(res_cue.payload.get("template"), (DataTemplate.pie.value, DataTemplate.donut.value))
        self.assertEqual(res_cue.payload.get("data_intent"), "part_to_whole")
        self.assertIn(res_cue.payload.get("visual_grammar"), ("pie", "donut"))

        # Verify labels and percentage values are preserved
        items = res_cue.payload.get("data", {}).get("items", [])
        self.assertEqual(len(items), 3)
        labels = [it["label"].upper() for it in items]
        self.assertIn("PREMIUM", labels)
        self.assertIn("STANDARD", labels)
        self.assertIn("BASIC", labels)

        # Normalize and Render Real Remotion MP4
        spec = normalize_motion_spec(res_cue, project, director=director)
        self.assertIn(spec.rendered_template, ("pie", "donut"))
        self.assertEqual(spec.data_intent.value, "part_to_whole")

        with tempfile.TemporaryDirectory() as tmp_dir:
            asset = render_scene_motion(spec, Path(tmp_dir))
            self.assertTrue(Path(asset.output_file).exists())
            self.assertGreater(Path(asset.output_file).stat().st_size, 1000)

    def test_hard_case_b_successful_llm_pie_to_threshold(self):
        """Hard Acceptance Case B (Section 11):
        Narration: 'Coverage limit is $25,000 while damage is $40,000.'
        Mock successful LLM deliberately returns: template = pie.
        Final production result MUST become: threshold (NOT pie).
        """
        project = _make_project()
        cue = TimelineCue(
            id="S002",
            order=1,
            start=0.0,
            end=4.0,
            narration="Coverage limit is $25,000 while damage is $40,000.",
        )

        def mock_llm_response(prompt: str) -> str:
            return json.dumps({
                "cues": [
                    {
                        "id": "S002",
                        "order": 1,
                        "visual_type": "data",
                        "purpose": "compare",
                        "payload": {
                            "template": "pie",
                            "headline": "POLICY THRESHOLD",
                            "data": {
                                "slices": [
                                    {"label": "Limit", "value": 25000},
                                    {"label": "Damage", "value": 40000},
                                ]
                            },
                        },
                    }
                ]
            })

        director = DataVisualizationDirector()
        planned = plan_visuals(
            project=project,
            timeline_cues=[cue],
            response_fn=mock_llm_response,
            director=director,
        )

        self.assertEqual(len(planned), 1)
        res_cue = planned[0]
        self.assertEqual(res_cue.payload.get("template"), DataTemplate.threshold.value)
        self.assertEqual(res_cue.payload.get("data_intent"), "threshold")
        self.assertEqual(res_cue.payload.get("visual_grammar"), "threshold")

        spec = normalize_motion_spec(res_cue, project, director=director)
        self.assertEqual(spec.rendered_template, "threshold")
        self.assertEqual(spec.props.get("threshold_value"), 25000.0)
        self.assertEqual(spec.props.get("current_value"), 40000.0)

    def test_hard_case_c_successful_llm_number_to_gauge(self):
        """Hard Acceptance Case C (Section 12):
        Narration: '75% of the process is complete.'
        Mock successful LLM returns: number.
        Final production result should become: progress -> gauge.
        """
        project = _make_project()
        cue = TimelineCue(
            id="S003",
            order=1,
            start=0.0,
            end=4.0,
            narration="75% of the process is complete.",
        )

        def mock_llm_response(prompt: str) -> str:
            return json.dumps({
                "cues": [
                    {
                        "id": "S003",
                        "order": 1,
                        "visual_type": "data",
                        "purpose": "explain",
                        "payload": {
                            "template": "number",
                            "headline": "PROGRESS",
                            "data": {
                                "value": "75%",
                                "numeric_value": 75,
                                "label": "Completed",
                            },
                        },
                    }
                ]
            })

        director = DataVisualizationDirector()
        planned = plan_visuals(
            project=project,
            timeline_cues=[cue],
            response_fn=mock_llm_response,
            director=director,
        )

        self.assertEqual(len(planned), 1)
        res_cue = planned[0]
        self.assertEqual(res_cue.payload.get("template"), DataTemplate.gauge.value)
        self.assertEqual(res_cue.payload.get("data_intent"), "progress")
        self.assertEqual(res_cue.payload.get("visual_grammar"), "gauge")

        spec = normalize_motion_spec(res_cue, project, director=director)
        self.assertEqual(spec.rendered_template, "gauge")
        self.assertEqual(spec.props.get("current_value"), 75.0)
        self.assertEqual(spec.props.get("max_value"), 100.0)

    def test_hard_case_d_successful_llm_gauge_to_number(self):
        """Hard Acceptance Case D (Section 13):
        Narration: 'Repair cost is $6,000.'
        Mock LLM returns: gauge (unbounded scalar without max bound).
        Final result MUST become: single_metric -> metric/number (NOT gauge).
        """
        project = _make_project()
        cue = TimelineCue(
            id="S004",
            order=1,
            start=0.0,
            end=4.0,
            narration="Repair cost is $6,000.",
        )

        def mock_llm_response(prompt: str) -> str:
            return json.dumps({
                "cues": [
                    {
                        "id": "S004",
                        "order": 1,
                        "visual_type": "data",
                        "purpose": "explain",
                        "payload": {
                            "template": "gauge",
                            "headline": "REPAIR COST",
                            "data": {
                                "current_value": 6000,
                            },
                        },
                    }
                ]
            })

        director = DataVisualizationDirector()
        planned = plan_visuals(
            project=project,
            timeline_cues=[cue],
            response_fn=mock_llm_response,
            director=director,
        )

        self.assertEqual(len(planned), 1)
        res_cue = planned[0]
        self.assertNotEqual(res_cue.payload.get("template"), DataTemplate.gauge.value)
        self.assertIn(res_cue.payload.get("template"), (DataTemplate.number.value, DataTemplate.counter.value, DataTemplate.callout.value))

        spec = normalize_motion_spec(res_cue, project, director=director)
        self.assertNotEqual(spec.rendered_template, "gauge")
        self.assertIn(spec.rendered_template, ("number", "counter", "callout"))

    def test_long_form_12_cues_successful_llm_diversity(self):
        """Section 14: 12-cue long-form diversity simulation with SUCCESSFUL LLM responses.
        Asserts that final sequence produced by plan_visuals with valid JSON contains rich diversity.
        """
        project = _make_project("12-Cue Explainer Diversity")
        narrations = [
            "40% chose Premium, 35% Standard, and 25% Basic.",
            "Premium increased from $120 in 2022 to $180 in 2026.",
            "Plan A costs $120, Plan B $180, and Plan C $230.",
            "75% of the inspection process is complete.",
            "Started at $100, added a $30 fee, received a $20 discount, and finished at $110.",
            "Coverage limit is $25,000 while damage is $40,000.",
            "Before filing the claim it was $120, after it jumped to $210.",
            "The top 3 causes are speeding at 45%, distraction at 30%, and weather at 25%.",
            "Total repair was $6,000, deductible was $1,000, and insurer covered $5,000.",
            "Next year reserve reached $850,000.",
            "80% of policyholders renewed, 20% switched.",
            "Remember that liability protects your life savings.",
        ]

        cues = [
            TimelineCue(
                id=f"S{i+1:03d}",
                order=i + 1,
                start=float(i * 4),
                end=float((i + 1) * 4),
                narration=narr,
            )
            for i, narr in enumerate(narrations)
        ]

        def successful_llm_response(prompt: str) -> str:
            # Parse requested cues from prompt and return valid generic structured DATA payloads
            parsed_cues = []
            for c in cues:
                parsed_cues.append({
                    "id": c.id,
                    "order": c.order,
                    "visual_type": "data",
                    "purpose": "explain",
                    "payload": {
                        "template": "callout",
                        "headline": "KEY DATA",
                        "data": {"emphasis": "Data Point"},
                    },
                })
            return json.dumps({"cues": parsed_cues})

        director = DataVisualizationDirector()
        planned = plan_visuals(
            project=project,
            timeline_cues=cues,
            response_fn=successful_llm_response,
            director=director,
        )

        self.assertEqual(len(planned), 12)
        templates_used = [c.payload.get("template") for c in planned if c.visual_type == VisualType.data]
        grammars_used = [c.payload.get("visual_grammar") for c in planned if c.visual_type == VisualType.data]

        distinct_grammars = set(grammars_used)
        # Should have at least 6 distinct grammars across the 12 cues
        self.assertGreaterEqual(len(distinct_grammars), 6)

        # Single director history should record exactly 1 entry per DATA cue (no double counting)
        self.assertEqual(director.memory.total_records, len(templates_used))
        self.assertEqual(len(director.memory.history), min(6, len(templates_used)))

    def test_single_memory_accounting_no_duplicates(self):
        """Section 8: Audit that direct_visual_specification records usage once
        and plan_visuals does not double-record into VisualDiversityMemory.
        """
        project = _make_project()
        cues = [
            TimelineCue(id="C1", order=1, start=0.0, end=4.0, narration="40% Premium and 60% Basic."),
            TimelineCue(id="C2", order=2, start=4.0, end=8.0, narration="Increased from $100 in 2022 to $200 in 2026."),
            TimelineCue(id="C3", order=3, start=8.0, end=12.0, narration="75% complete."),
        ]

        def mock_llm_response(prompt: str) -> str:
            return json.dumps({
                "cues": [
                    {
                        "id": c.id,
                        "order": c.order,
                        "visual_type": "data",
                        "purpose": "explain",
                        "payload": {"template": "callout", "headline": "DATA", "data": {}},
                    }
                    for c in cues
                ]
            })

        director = DataVisualizationDirector()
        planned = plan_visuals(
            project=project,
            timeline_cues=cues,
            response_fn=mock_llm_response,
            director=director,
        )

        self.assertEqual(len(planned), 3)
        self.assertEqual(director.memory.total_records, 3)
        self.assertEqual(len(director.memory.history), 3)


if __name__ == "__main__":
    unittest.main()
