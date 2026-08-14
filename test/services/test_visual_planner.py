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
)


def _project() -> ProjectSpec:
    return ProjectSpec(
        schema_version="1.0",
        project={"title": "Retirement Gap"},
        script={"subject": "Medicare retirement planning", "script": "Age 65 matters."},
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
