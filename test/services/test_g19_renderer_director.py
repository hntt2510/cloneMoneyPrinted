from __future__ import annotations

import unittest
from typing import Any

from app.models.motion import (
    BackgroundTreatment,
    CompositionPattern,
    InformationDensity,
    MotionPattern,
    RendererDecision,
    RendererFamily,
    SemanticDataIntent,
    StorytellingTechnique,
    VisualGrammar,
)
from app.services.visual_renderer_director import VisualDiversityMemoryV2, VisualRendererDirector


class TestG19RendererDirector(unittest.TestCase):
    """Deterministic tests for VisualRendererDirector and VisualDiversityMemoryV2."""

    def setUp(self) -> None:
        self.memory = VisualDiversityMemoryV2()
        self.director = VisualRendererDirector(diversity_memory=self.memory)

    def test_single_metric_punch_decision(self) -> None:
        """Section 49: Test single metric maps to metric_punch when no recent repetition exists."""
        props = {"headline": "REVENUE", "value": "$6,000", "numeric_value": 6000.0}
        decision = self.director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.metric,
            template="number",
            props=props,
            narration="Revenue reached six thousand dollars.",
        )
        self.assertEqual(decision.renderer_family, RendererFamily.editorial_remotion)
        self.assertEqual(decision.storytelling_technique, StorytellingTechnique.metric_punch)
        self.assertEqual(decision.composition_pattern, CompositionPattern.centered_hero)
        self.assertEqual(decision.motion_pattern, MotionPattern.punch_in)
        self.assertEqual(decision.density, InformationDensity.low)

    def test_single_metric_context_or_delta_diversity(self) -> None:
        """Section 30 & 49: Test diversity shifts from metric_punch to metric_context or metric_delta."""
        # 1st call -> metric_punch
        d1 = self.director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.metric,
            template="number",
            props={"headline": "METRIC 1", "value": "100"},
            narration="First metric is one hundred.",
        )
        self.assertEqual(d1.storytelling_technique, StorytellingTechnique.metric_punch)

        # 2nd call with same type -> shifts to metric_context to avoid repetition
        d2 = self.director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.metric,
            template="number",
            props={"headline": "METRIC 2", "value": "200"},
            narration="Second metric is two hundred.",
        )
        self.assertEqual(d2.storytelling_technique, StorytellingTechnique.metric_context)

        # 3rd call with delta keywords -> metric_delta
        d3 = self.director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.metric,
            template="number",
            props={"headline": "METRIC 3", "value": "$5,000"},
            narration="Revenue grew from $2,000 to $5,000.",
        )
        self.assertEqual(d3.storytelling_technique, StorytellingTechnique.metric_delta)

    def test_hybrid_broll_gate_strong_vs_weak(self) -> None:
        """Section 27 & 54: Strong B-roll allows HYBRID; weak B-roll falls back to editorial DATA."""
        # Strong B-roll (confidence >= 0.70)
        d_strong = self.director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.metric,
            template="number",
            props={"headline": "COST", "value": "$6,000"},
            narration="The total repair cost was six thousand dollars.",
            broll_candidate_confidence=0.85,
            broll_candidate_path="/path/to/car_damage.mp4",
        )
        self.assertEqual(d_strong.renderer_family, RendererFamily.hybrid_broll_data)
        self.assertEqual(d_strong.storytelling_technique, StorytellingTechnique.hybrid_metric)
        self.assertEqual(d_strong.asset_mode, "video")

        # Weak B-roll (confidence < 0.70) -> fallback to EDITORIAL_REMOTION
        d_weak = self.director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.metric,
            template="number",
            props={"headline": "COST", "value": "$6,000"},
            narration="The total repair cost was six thousand dollars.",
            broll_candidate_confidence=0.45,
            broll_candidate_path="/path/to/random_footage.mp4",
        )
        self.assertEqual(d_weak.renderer_family, RendererFamily.editorial_remotion)

    def test_diagram_flow_decision(self) -> None:
        """Section 23 & 49: System flow narration maps to diagram_reveal."""
        d = self.director.decide_renderer(
            data_intent=SemanticDataIntent.sequence,
            visual_grammar=VisualGrammar.diagram,
            template="diagram",
            props={"headline": "REQUEST LIFECYCLE", "nodes": [{"id": "n1", "label": "API"}]},
            narration="Requests enter the API, hit cache, and query the database.",
        )
        self.assertEqual(d.renderer_family, RendererFamily.diagram_remotion)
        self.assertEqual(d.storytelling_technique, StorytellingTechnique.diagram_reveal)
        self.assertEqual(d.composition_pattern, CompositionPattern.flow_diagram)

    def test_data_grid_kpi_decision(self) -> None:
        """Section 24 & 49: Multi-metric items map to data_grid with high density."""
        props = {
            "headline": "SYSTEM HEALTH",
            "items": [
                {"label": "UPTIME", "value": "99.99%"},
                {"label": "LATENCY", "value": "42ms"},
                {"label": "REQUESTS", "value": "1.2M"},
                {"label": "ERROR RATE", "value": "0.08%"},
            ],
        }
        d = self.director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.data_grid,
            template="data_grid",
            props=props,
            narration="System health shows 99.99% uptime, 42ms latency, and 1.2M requests.",
        )
        self.assertEqual(d.renderer_family, RendererFamily.editorial_remotion)
        self.assertEqual(d.storytelling_technique, StorytellingTechnique.data_grid)
        self.assertEqual(d.composition_pattern, CompositionPattern.data_grid_matrix)
        self.assertEqual(d.density, InformationDensity.high)

    def test_threshold_story_decision(self) -> None:
        """Section 21 & 49: Threshold intent maps to threshold_story."""
        d = self.director.decide_renderer(
            data_intent=SemanticDataIntent.threshold,
            visual_grammar=VisualGrammar.threshold,
            template="threshold",
            props={"headline": "LIMIT EXCEEDED", "threshold_value": 25000, "current_value": 40000},
            narration="If damage exceeds twenty-five thousand dollars.",
        )
        self.assertEqual(d.renderer_family, RendererFamily.editorial_remotion)
        self.assertEqual(d.storytelling_technique, StorytellingTechnique.threshold_story)
        self.assertEqual(d.composition_pattern, CompositionPattern.threshold_gauge)

    def test_d3_narrative_chart_decision(self) -> None:
        """Section 19 & 20: Pie/Donut maps to D3_REMOTION narrative_chart."""
        d = self.director.decide_renderer(
            data_intent=SemanticDataIntent.part_to_whole,
            visual_grammar=VisualGrammar.donut,
            template="donut",
            props={"headline": "TIER SHARE", "items": [{"label": "A", "value": 40}, {"label": "B", "value": 60}]},
            narration="Tier A holds forty percent and Tier B holds sixty percent.",
        )
        self.assertEqual(d.renderer_family, RendererFamily.d3_remotion)
        self.assertEqual(d.storytelling_technique, StorytellingTechnique.narrative_chart)


if __name__ == "__main__":
    unittest.main()
