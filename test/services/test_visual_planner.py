import json
import unittest

from app.models.project import (
    BrollPayload,
    DataPayload,
    DataTemplate,
    DocumentPayload,
    ProjectSpec,
    TextPayload,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.visual_planner import (
    classify_narration,
    fallback_visual,
    plan_visuals,
    _build_local_context,
    _validate_grounded_data,
    _validate_grounded_text,
    PlannerError,
    PlannerDecision,
)


def _project(script: str = "Age 65 matters.") -> ProjectSpec:
    return ProjectSpec(
        schema_version="1.0",
        project={"title": "Retirement Gap"},
        script={"subject": "Medicare retirement planning", "script": script},
        narration={"mode": "tts"},
    )


def _cue(index: int, narration: str) -> TimelineCue:
    return TimelineCue(
        id=f"S{index:03d}",
        order=index,
        start=float(index - 1),
        end=float(index),
        narration=narration,
    )


def _decision(
    cue_id: str,
    order: int,
    visual_type: str,
    payload: dict,
    purpose: str = "explain",
) -> PlannerDecision:
    return PlannerDecision(
        id=cue_id,
        order=order,
        visual_type=visual_type,
        purpose=purpose,
        payload=payload,
    )


class TestVisualPayloads(unittest.TestCase):
    def test_payload_contracts_and_rejections(self):
        self.assertEqual(BrollPayload(search_query="senior couple").source_priority, ["pexels", "pixabay", "coverr"])
        self.assertEqual(DataPayload(template=DataTemplate.number, headline="AGE", data={}).headline, "AGE")
        self.assertTrue(DocumentPayload(search_query="IRS Form 1040", source_hint="IRS official").evidence_required)
        self.assertEqual(TextPayload(headline="THE PROBLEM").headline, "THE PROBLEM")
        with self.assertRaises(ValueError):
            BrollPayload(search_query="")
        with self.assertRaises(ValueError):
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload={},
            )

    def test_fallback_classification(self):
        project = _project()
        cases = [
            ("Medicare starts at age 65.", VisualType.data),
            ("That creates a five-year gap.", VisualType.data),
            ("Many retirees review medical bills at home.", VisualType.broll),
            ("According to IRS Form 1040...", VisualType.document),
            ("THE PROBLEM", VisualType.text),
        ]
        for text, expected in cases:
            self.assertEqual(classify_narration(text), expected)
            self.assertEqual(fallback_visual(project, _cue(1, text)).visual_type, expected)

    def test_document_payload_forbids_extras(self):
        """DocumentPayload extra=forbid must reject URL/citation fields."""
        with self.assertRaises(ValueError):
            DocumentPayload(
                search_query="SSA publication",
                source_hint="SSA official",
                url="https://example.com",  # type: ignore[call-arg]
            )
        with self.assertRaises(ValueError):
            DocumentPayload(
                search_query="SSA",
                source_hint="SSA",
                citation="SSA 2024",  # type: ignore[call-arg]
            )


class TestLocalGrounding(unittest.TestCase):
    """Tests for the local-context grounding window (current + adjacent cues)."""

    def _make_timeline(self):
        return [
            _cue(1, "You can retire at age 60."),
            _cue(2, "Medicare begins at age 65."),
            _cue(3, "The gap can be expensive."),
            _cue(4, "Some households spend $12,000."),
        ]

    # ----- Test A: distant script number rejected -----

    def test_distant_script_number_rejected_in_current_cue(self):
        """A number appearing much later in the script must not ground an earlier cue."""
        timeline = self._make_timeline()
        # S001 cue: "You can retire at age 60."
        # $12,000 appears in S004 — 3 cues away
        decision = _decision(
            "S001",
            1,
            "data",
            {"template": "number", "headline": "COST 12,000", "data": {"values": ["12,000"]}},
        )
        local_ctx = _build_local_context(timeline, 0)  # index 0 → S001
        with self.assertRaises(PlannerError) as ctx:
            _validate_grounded_data(decision, timeline[0], local_ctx)
        self.assertIn("12000", str(ctx.exception))

    # ----- Test B: headline-only invalid number rejected -----

    def test_headline_only_invented_number_rejected(self):
        """An ungrounded number in DataPayload.headline (not in data dict) is rejected."""
        timeline = self._make_timeline()
        # Current cue S002: "Medicare begins at age 65."
        # Age 62 does not appear in S001, S002, or S003
        decision = _decision(
            "S002",
            2,
            "data",
            {"template": "age_marker", "headline": "MEDICARE AT 62", "data": {}},
        )
        local_ctx = _build_local_context(timeline, 1)  # index 1 → S002
        with self.assertRaises(PlannerError) as ctx:
            _validate_grounded_data(decision, timeline[1], local_ctx)
        self.assertIn("62", str(ctx.exception))

    # ----- Test C: valid local number accepted -----

    def test_local_valid_number_accepted(self):
        """A number present in the current cue narration must be accepted."""
        timeline = self._make_timeline()
        # S002: "Medicare begins at age 65." — 65 is grounded
        decision = _decision(
            "S002",
            2,
            "data",
            {"template": "age_marker", "headline": "MEDICARE AT 65", "data": {"age": 65}},
        )
        local_ctx = _build_local_context(timeline, 1)
        # Should not raise
        _validate_grounded_data(decision, timeline[1], local_ctx)

    # ----- Test D: adjacent cue number allowed -----

    def test_adjacent_cue_number_allowed(self):
        """A number appearing in the immediately adjacent cue is permitted."""
        timeline = self._make_timeline()
        # S003: "The gap can be expensive."
        # S004 (next) contains $12,000 → allowed for S003
        decision = _decision(
            "S003",
            3,
            "data",
            {"template": "number", "headline": "$12,000 COST", "data": {"amount": "12,000"}},
        )
        local_ctx = _build_local_context(timeline, 2)  # index 2 → S003 (adjacent to S004)
        # Should not raise
        _validate_grounded_data(decision, timeline[2], local_ctx)

    # ----- Test E: non-adjacent (2+ cues away) number rejected -----

    def test_non_adjacent_number_rejected(self):
        """A number 2+ cues away from current cue must be rejected."""
        timeline = self._make_timeline()
        # S001: "You can retire at age 60."
        # $12,000 is in S004 (3 cues away) — not adjacent
        decision = _decision(
            "S001",
            1,
            "data",
            {"template": "number", "headline": "$12,000", "data": {"values": ["12,000"]}},
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision, timeline[0], local_ctx)

    # ----- Test F: TextPayload invented number rejected -----

    def test_text_payload_invented_number_rejected(self):
        """TEXT payload headline containing a number absent from local context is rejected."""
        timeline = [
            _cue(1, "The gap can be expensive."),
            _cue(2, "Plan early for retirement."),
        ]
        decision = _decision(
            "S001",
            1,
            "text",
            {"headline": "THE $50,000 PROBLEM"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError) as ctx:
            _validate_grounded_text(decision, timeline[0], local_ctx)
        self.assertIn("50000", str(ctx.exception))

    def test_text_payload_no_numbers_accepted(self):
        """TEXT payload headline without numbers passes the numeric guard."""
        timeline = [_cue(1, "The gap can be expensive.")]
        decision = _decision(
            "S001",
            1,
            "text",
            {"headline": "THE RETIREMENT GAP"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        # Should not raise
        _validate_grounded_text(decision, timeline[0], local_ctx)

    def test_local_context_window_is_three_cues_maximum(self):
        """Local context must include prev + current + next but NOT cues 2+ away."""
        timeline = [
            _cue(1, "one hundred dollars."),     # S001
            _cue(2, "two hundred dollars."),     # S002
            _cue(3, "three hundred dollars."),   # S003
            _cue(4, "four hundred dollars."),    # S004
            _cue(5, "five hundred dollars."),    # S005
        ]
        # For S003 (index 2): prev=S002, current=S003, next=S004
        ctx = _build_local_context(timeline, 2)
        self.assertIn("two", ctx)
        self.assertIn("three", ctx)
        self.assertIn("four", ctx)
        # S001 and S005 must NOT be in context
        self.assertNotIn("one hundred", ctx)
        self.assertNotIn("five hundred", ctx)


class TestExactNumericEquivalence(unittest.TestCase):
    """Specific regression tests for exact numeric token canonicalization vs substring matching."""

    # 1. context "$12,000", payload 12 -> rejected
    def test_context_12000_payload_12_rejected_in_data_data(self):
        timeline = [_cue(1, "Some households spend $12,000.")]
        decision = _decision(
            "S001", 1, "data",
            {"template": "number", "headline": "COST", "data": {"amount": 12}},
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision, timeline[0], local_ctx)

    def test_context_12000_payload_12_rejected_in_data_headline(self):
        timeline = [_cue(1, "Some households spend $12,000.")]
        decision = _decision(
            "S001", 1, "data",
            {"template": "number", "headline": "COST IS 12", "data": {}},
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision, timeline[0], local_ctx)

    def test_context_12000_payload_12_rejected_in_text_headline(self):
        timeline = [_cue(1, "Some households spend $12,000.")]
        decision = _decision(
            "S001", 1, "text",
            {"headline": "THE 12 DOLLAR PROBLEM"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_text(decision, timeline[0], local_ctx)

    # 2. context "$12,000", payload 12000 -> accepted
    def test_context_12000_payload_12000_accepted(self):
        timeline = [_cue(1, "Some households spend $12,000.")]
        # Test in DATA headline, DATA payload (int), DATA payload (str), TEXT headline, TEXT subheadline
        decision_data = _decision(
            "S001", 1, "data",
            {"template": "number", "headline": "SPEND $12,000", "data": {"amount": 12000, "str_amount": "12000"}},
        )
        decision_text = _decision(
            "S001", 1, "text",
            {"headline": "COST $12,000", "subheadline": "OR 12000 PER YEAR"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        _validate_grounded_data(decision_data, timeline[0], local_ctx)
        _validate_grounded_text(decision_text, timeline[0], local_ctx)

    # 3. context "age 65", payload 6 -> rejected
    def test_context_age_65_payload_6_rejected(self):
        timeline = [_cue(1, "Medicare begins at age 65.")]
        decision_data_headline = _decision(
            "S001", 1, "data",
            {"template": "age_marker", "headline": "AGE 6", "data": {}},
        )
        decision_data_val = _decision(
            "S001", 1, "data",
            {"template": "age_marker", "headline": "AGE", "data": {"age": 6}},
        )
        decision_text = _decision(
            "S001", 1, "text",
            {"headline": "STARTS AT 6"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision_data_headline, timeline[0], local_ctx)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision_data_val, timeline[0], local_ctx)
        with self.assertRaises(PlannerError):
            _validate_grounded_text(decision_text, timeline[0], local_ctx)

    # 4. context "age 65", payload 65 -> accepted
    def test_context_age_65_payload_65_accepted(self):
        timeline = [_cue(1, "Medicare begins at age 65.")]
        decision = _decision(
            "S001", 1, "data",
            {"template": "age_marker", "headline": "MEDICARE AT 65", "data": {"age": 65}},
        )
        local_ctx = _build_local_context(timeline, 0)
        _validate_grounded_data(decision, timeline[0], local_ctx)

    # 5. context "150%", payload "50%" -> rejected
    def test_context_150_percent_payload_50_percent_rejected(self):
        timeline = [_cue(1, "Costs increased by 150% over ten years.")]
        decision_data = _decision(
            "S001", 1, "data",
            {"template": "number", "headline": "50% INCREASE", "data": {"pct": "50%"}},
        )
        decision_text = _decision(
            "S001", 1, "text",
            {"headline": "A 50% JUMP"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision_data, timeline[0], local_ctx)
        with self.assertRaises(PlannerError):
            _validate_grounded_text(decision_text, timeline[0], local_ctx)

    # 6. context "15%", payload "15%" -> accepted
    def test_context_15_percent_payload_15_percent_accepted(self):
        timeline = [_cue(1, "A penalty of 15% applies.")]
        decision = _decision(
            "S001", 1, "data",
            {"template": "number", "headline": "15% PENALTY", "data": {"penalty": "15%"}},
        )
        decision_text = _decision(
            "S001", 1, "text",
            {"headline": "PAY 15% MORE"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        _validate_grounded_data(decision, timeline[0], local_ctx)
        _validate_grounded_text(decision_text, timeline[0], local_ctx)

    # 7. context "5.5%", payload 5 -> rejected
    def test_context_5_point_5_percent_payload_5_rejected(self):
        timeline = [_cue(1, "Interest rates hit 5.5% this month.")]
        decision_data = _decision(
            "S001", 1, "data",
            {"template": "number", "headline": "RATE AT 5%", "data": {"rate": 5}},
        )
        decision_text = _decision(
            "S001", 1, "text",
            {"headline": "5% RATE"},
            purpose="emphasis",
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision_data, timeline[0], local_ctx)
        with self.assertRaises(PlannerError):
            _validate_grounded_text(decision_text, timeline[0], local_ctx)

    # 8. context "15%", payload 15 (plain number) -> rejected
    def test_context_15_percent_payload_15_plain_rejected(self):
        timeline = [_cue(1, "A penalty of 15% applies.")]
        decision = _decision(
            "S001", 1, "data",
            {"template": "number", "headline": "15 DOLLARS", "data": {"val": 15}},
        )
        local_ctx = _build_local_context(timeline, 0)
        with self.assertRaises(PlannerError):
            _validate_grounded_data(decision, timeline[0], local_ctx)


class TestGroundingViaPlanner(unittest.TestCase):
    """End-to-end grounding tests through plan_visuals()."""

    def _distant_number_project(self):
        """Project whose script has $12,000 only in a distant scene."""
        script = (
            "You can retire at age 60. "
            "Medicare begins at age 65. "
            "That leaves a five-year gap. "
            "Some households spend $12,000."
        )
        return _project(script), script

    def test_plan_distant_number_falls_back(self):
        """Planner attempting $12,000 for S001 (only valid in S004) must fall back."""
        project, _ = self._distant_number_project()
        cue_s001 = _cue(1, "You can retire at age 60.")
        cue_s002 = _cue(2, "Medicare begins at age 65.")
        cue_s003 = _cue(3, "That leaves a five-year gap.")
        cue_s004 = _cue(4, "Some households spend $12,000.")
        timeline = [cue_s001, cue_s002, cue_s003, cue_s004]

        def response(_prompt):
            return json.dumps({
                "cues": [
                    {
                        "id": "S001",
                        "order": 1,
                        "visual_type": "data",
                        "purpose": "explain",
                        "payload": {
                            "template": "number",
                            "headline": "$12,000 COST",
                            "data": {"amount": "12,000"},
                        },
                    },
                    {
                        "id": "S002",
                        "order": 2,
                        "visual_type": "data",
                        "purpose": "explain",
                        "payload": {
                            "template": "age_marker",
                            "headline": "MEDICARE AT 65",
                            "data": {"age": 65},
                        },
                    },
                    {
                        "id": "S003",
                        "order": 3,
                        "visual_type": "broll",
                        "purpose": "context",
                        "payload": {"search_query": "retirement gap illustration"},
                    },
                    {
                        "id": "S004",
                        "order": 4,
                        "visual_type": "data",
                        "purpose": "explain",
                        "payload": {
                            "template": "number",
                            "headline": "$12,000 HOUSEHOLD SPEND",
                            "data": {"amount": "12,000"},
                        },
                    },
                ]
            })

        planned = plan_visuals(project, timeline, response_fn=response)
        # S001 must NOT contain $12,000 — it should fall back
        s001 = next(c for c in planned if c.id == "S001")
        self.assertNotIn("12,000", json.dumps(s001.payload))
        # S004 may use $12,000 (grounded in own narration)
        s004 = next(c for c in planned if c.id == "S004")
        # S004 should have accepted the payload
        self.assertIn("12,000", json.dumps(s004.payload))


class TestVisualPlanner(unittest.TestCase):
    def test_repair_then_accepts_strict_batch(self):
        project = _project()
        cue = _cue(1, "Many retirees review medical bills at home.")
        calls = []

        def response(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                return "not json"
            return json.dumps(
                {
                    "cues": [
                        {
                            "id": "S001",
                            "order": 1,
                            "visual_type": "broll",
                            "purpose": "context",
                            "payload": {"search_query": "retirees reviewing medical bills"},
                        }
                    ]
                }
            )

        planned = plan_visuals(project, [cue], response_fn=response)
        self.assertEqual(len(calls), 2)
        self.assertEqual(planned[0].id, "S001")
        self.assertEqual(planned[0].start, cue.start)

    def test_invalid_ai_timing_falls_back_to_canonical_timing(self):
        project = _project()
        cue = _cue(1, "Medicare starts at age 65.")

        def response(_prompt):
            return json.dumps(
                {
                    "cues": [
                        {
                            "id": "S001",
                            "order": 1,
                            "start": 99,
                            "end": 100,
                            "visual_type": "data",
                            "purpose": "explain",
                            "payload": {"template": "age_marker", "headline": "AGE 65", "data": {"values": [65]}},
                        }
                    ]
                }
            )

        planned = plan_visuals(project, [cue], response_fn=response)
        self.assertEqual(planned[0].start, cue.start)
        self.assertEqual(planned[0].end, cue.end)

    def test_ungrounded_data_falls_back_without_fabricated_value(self):
        project = _project()
        cue = _cue(1, "Medicare starts at age 65.")

        def response(_prompt):
            return json.dumps(
                {
                    "cues": [
                        {
                            "id": "S001",
                            "order": 1,
                            "visual_type": "data",
                            "purpose": "explain",
                            "payload": {"template": "number", "headline": "AGE", "data": {"values": [999]}},
                        }
                    ]
                }
            )

        planned = plan_visuals(project, [cue], response_fn=response)
        self.assertNotIn("999", json.dumps(planned[0].payload))

    def test_batches_long_timeline_and_preserves_identity(self):
        project = _project()
        timeline = [_cue(index, f"A person reviews retirement paperwork {index}.") for index in range(1, 26)]
        calls = []

        def response(prompt):
            calls.append(prompt)
            batch = timeline[(len(calls) - 1) * 10 : len(calls) * 10]
            decisions = []
            for cue in batch:
                decisions.append(
                    {
                        "id": cue.id,
                        "order": cue.order,
                        "visual_type": "broll",
                        "purpose": "context",
                        "payload": {"search_query": f"retirement paperwork scene {cue.id}"},
                    }
                )
            return json.dumps({"cues": decisions})

        planned = plan_visuals(project, timeline, response_fn=response)
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual([cue.id for cue in planned], [cue.id for cue in timeline])
        self.assertEqual([cue.order for cue in planned], [cue.order for cue in timeline])
        self.assertEqual([cue.start for cue in planned], [cue.start for cue in timeline])

    def test_contiguous_visual_group_is_canonicalized(self):
        project = _project()
        timeline = [_cue(index, f"Age {60 + index} retirement gap") for index in range(1, 4)]

        def response(_prompt):
            return json.dumps(
                {
                    "cues": [
                        {
                            "id": cue.id,
                            "order": cue.order,
                            "visual_type": "data",
                            "purpose": "compare",
                            "visual_group_id": "raw-group",
                            "payload": {"template": "age_marker", "headline": cue.narration, "data": {"values": [60 + cue.order]}},
                        }
                        for cue in timeline
                    ]
                }
            )

        planned = plan_visuals(project, timeline, response_fn=response)
        self.assertEqual([cue.visual_group_id for cue in planned], ["VG001", "VG001", "VG001"])


if __name__ == "__main__":
    unittest.main()
