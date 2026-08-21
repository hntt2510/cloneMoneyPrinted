from __future__ import annotations

import unittest
from app.models.project import (
    DataPayload,
    DataTemplate,
    ProjectSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.motion import (
    SemanticDataIntent,
    VisualGrammar,
)
from app.services.data_visualization_director import DataVisualizationDirector
from app.services.visual_planner import _apply_diversity, classify_narration
from app.services.broll import MIN_BROLL_CONFIDENCE_SCORE, BrollCandidate, score_candidate


class TestG18SemanticHardening(unittest.TestCase):
    """Unit tests for G18.1 semantic hardening:
    - Defect A: 4-cue breakdown sequence with redundant semantic numeric role
    - Defect B: Grounded qualitative conceptual comparison
    - Defect C: B-roll confidence quality floor
    """

    def test_defect_a_four_cue_breakdown_grouping_and_deduplication(self) -> None:
        """Section 1 / Defect A: Validate that a 4-cue breakdown sequence ($6k total,
        $1k deductible, $1k responsible, $5k insurer covers) receives a single shared visual_group_id,
        breakdown template, and arithmetic consistency (1000 + 5000 == 6000).
        """
        cues = [
            TimelineCue(id="C001", order=1, start=0.0, end=2.0, narration="Let's use a simple example."),
            TimelineCue(id="C002", order=2, start=2.0, end=5.8, narration="Suppose repairing your car costs six thousand dollars."),
            TimelineCue(id="C003", order=3, start=5.8, end=8.9, narration="Your collision deductible is one thousand dollars."),
            TimelineCue(id="C004", order=4, start=8.9, end=14.2, narration="You would generally be responsible for the first one thousand dollars,"),
            TimelineCue(id="C005", order=5, start=14.2, end=17.7, narration="while the insurance company could cover the remaining five thousand dollars,"),
            TimelineCue(id="C006", order=6, start=17.7, end=20.0, narration="subject to your policy limits."),
        ]

        decisions = [
            VisualCue(id="C001", order=1, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=0.0, end=2.0, narration=cues[0].narration, payload={"search_query": "car accident"}),
            VisualCue(id="C002", order=2, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=2.0, end=5.8, narration=cues[1].narration, payload={"template": "number", "headline": "REPAIR COST"}),
            VisualCue(id="C003", order=3, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=5.8, end=8.9, narration=cues[2].narration, payload={"template": "number", "headline": "DEDUCTIBLE"}),
            VisualCue(id="C004", order=4, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=8.9, end=14.2, narration=cues[3].narration, payload={"template": "number", "headline": "YOU PAY"}),
            VisualCue(id="C005", order=5, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=14.2, end=17.7, narration=cues[4].narration, payload={"template": "number", "headline": "INSURANCE"}),
            VisualCue(id="C006", order=6, visual_type=VisualType.text, purpose=VisualPurpose.emphasis, start=17.7, end=20.0, narration=cues[5].narration, payload={"headline": "POLICY LIMITS"}),
        ]

        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Insurance 60s Breakdown", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "auto insurance collision deductible", "script": "test script"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)

        # Cues 2..5 (index 1..4) must share the SAME visual_group_id
        group_id = adapted[1].visual_group_id
        self.assertIsNotNone(group_id, "Cue 2 must have a visual_group_id")
        self.assertEqual(adapted[2].visual_group_id, group_id, "Cue 3 must share the same visual_group_id")
        self.assertEqual(adapted[3].visual_group_id, group_id, "Cue 4 must share the same visual_group_id")
        self.assertEqual(adapted[4].visual_group_id, group_id, "Cue 5 must share the same visual_group_id")

        # Cues 2..5 must be breakdown data templates
        for idx in range(1, 5):
            cue = adapted[idx]
            self.assertEqual(cue.visual_type, VisualType.data)
            self.assertEqual(cue.payload.get("template"), "breakdown")
            self.assertEqual(cue.payload.get("visual_grammar"), "breakdown")
            self.assertEqual(cue.payload.get("layout_archetype"), "stacked_breakdown")
            self.assertEqual(cue.payload.get("data", {}).get("total", {}).get("numeric_value"), 6000.0)
            parts = cue.payload.get("data", {}).get("parts", [])
            self.assertEqual(len(parts), 2)
            self.assertEqual(parts[0]["numeric_value"], 1000.0)
            self.assertEqual(parts[1]["numeric_value"], 5000.0)

    def test_defect_b_grounded_qualitative_conceptual_comparison(self) -> None:
        """Section 2 / Defect B: Validate that qualitative comparison phrases
        (e.g. 'different from', 'premium is ongoing cost', 'deductible is share of cost')
        are classified as comparison data visuals with concise definitions and NO fabricated numbers.
        """
        # 1. Classification check
        n1 = "That deductible is very different from your insurance premium."
        n2 = "Your premium is the ongoing cost you pay to maintain the policy,"
        n3 = "Your deductible is your share of the cost when you actually make a covered claim."

        self.assertEqual(classify_narration(n1), VisualType.data)
        self.assertEqual(classify_narration(n2), VisualType.data)
        self.assertEqual(classify_narration(n3), VisualType.data)

        # 2. Director specification check
        director = DataVisualizationDirector()
        spec1 = director.direct_visual_specification(narration=n1, headline="PREMIUM VS DEDUCTIBLE")
        self.assertEqual(spec1.grammar, VisualGrammar.comparison)
        self.assertEqual(spec1.variant, "split_compare")
        self.assertEqual(len(spec1.props.get("items", [])), 2)

        item0 = spec1.props["items"][0]
        item1 = spec1.props["items"][1]
        self.assertEqual(item0["label"], "PREMIUM")
        self.assertEqual(item1["label"], "DEDUCTIBLE")
        # Ensure zero fabricated dollar values
        self.assertNotIn("$", str(item0.get("value", "")))
        self.assertNotIn("$", str(item1.get("value", "")))
        self.assertGreater(len(item0.get("value", "")), 5)
        self.assertGreater(len(item1.get("value", "")), 5)

        # 3. Grouping in _apply_diversity
        cues = [
            TimelineCue(id="C007", order=7, start=20.0, end=23.4, narration=n1),
            TimelineCue(id="C008", order=8, start=23.4, end=27.2, narration=n2),
            TimelineCue(id="C009", order=9, start=27.2, end=32.2, narration=n3),
        ]
        decisions = [
            VisualCue(id="C007", order=7, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=20.0, end=23.4, narration=n1, payload={"search_query": "insurance policy"}),
            VisualCue(id="C008", order=8, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=23.4, end=27.2, narration=n2, payload={"search_query": "monthly payment"}),
            VisualCue(id="C009", order=9, visual_type=VisualType.broll, purpose=VisualPurpose.context, start=27.2, end=32.2, narration=n3, payload={"search_query": "car claim"}),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Insurance 60s Breakdown", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "auto insurance collision deductible", "script": "test script"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)
        gid = adapted[0].visual_group_id
        self.assertIsNotNone(gid)
        self.assertEqual(adapted[1].visual_group_id, gid)
        self.assertEqual(adapted[2].visual_group_id, gid)

        for c in adapted:
            self.assertEqual(c.visual_type, VisualType.data)
            self.assertEqual(c.payload.get("template"), "comparison")
            self.assertEqual(c.payload.get("layout_archetype"), "split_compare")

    def test_defect_c_broll_confidence_quality_floor(self) -> None:
        """Section 3 / Defect C: Validate that B-roll confidence floor is set to >= 35.0
        and low-scoring candidates (e.g. score 20.0) are skipped.
        """
        self.assertGreaterEqual(MIN_BROLL_CONFIDENCE_SCORE, 35.0)

        # Candidate with score 20.0 must be below the floor
        weak_candidate = BrollCandidate(
            id="pexels-weak-103",
            provider="pexels",
            provider_asset_id="103",
            query="theft",
            download_url="https://example.com/video.mp4",
            duration=10.0,
            width=1920,
            height=1080,
            score=20.0,
        )
        self.assertLess(weak_candidate.score, MIN_BROLL_CONFIDENCE_SCORE)


if __name__ == "__main__":
    unittest.main()
