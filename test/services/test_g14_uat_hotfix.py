import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from app.services.numeric_parser import (
    CanonicalNumericFact,
    extract_canonical_numeric_facts,
)
from app.services.scene_orchestrator import run_all_project
from app.services.visual_planner import (
    PlannerBatch,
    PlannerDecision,
    classify_narration,
    fallback_visual,
    plan_visuals,
)


class TestG14UATHotfix(unittest.TestCase):
    def test_spoken_numbers_canonical_extraction(self):
        """Verify spoken number extraction and numeric grounding equivalence."""
        script_phrases = [
            ("Suppose repairing your car costs six thousand dollars.", 6000.0, "$6,000"),
            ("Your collision deductible is one thousand dollars.", 1000.0, "$1,000"),
            ("while the insurance company could cover the remaining five thousand dollars,", 5000.0, "$5,000"),
            ("Imagine you have twenty-five thousand dollars of property damage liability coverage,", 25000.0, "$25,000"),
            ("but you cause forty thousand dollars in covered damage.", 40000.0, "$40,000"),
        ]
        for phrase, expected_val, expected_disp in script_phrases:
            facts = extract_canonical_numeric_facts(phrase)
            self.assertEqual(len(facts), 1, f"Failed for phrase: {phrase}")
            self.assertEqual(facts[0].value, expected_val)
            self.assertEqual(facts[0].display, expected_disp)
            self.assertTrue(facts[0].is_currency)

    def test_spoken_numbers_grounding_allows_digit_payload(self):
        """Spoken narration fact grounds digit payload fact."""
        cue = TimelineCue(
            id="S013",
            order=13,
            start=0.0,
            end=4.0,
            narration="Suppose repairing your car costs six thousand dollars.",
        )
        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Test", aspect_ratio=VideoAspect.landscape),
            script={"subject": "Car Insurance", "script": cue.narration},
            narration=NarrationSpec(mode="tts"),
        )

        def response(_prompt):
            return json.dumps(
                {
                    "cues": [
                        {
                            "id": "S013",
                            "order": 13,
                            "visual_type": "data",
                            "purpose": "explain",
                            "payload": {
                                "template": "number",
                                "headline": "Repair Cost: $6,000",
                                "data": {
                                    "value": "$6,000",
                                    "numeric_value": 6000,
                                    "label": "Repair Cost",
                                },
                            },
                        }
                    ]
                }
            )

        planned = plan_visuals(project, [cue], response_fn=response)
        self.assertEqual(len(planned), 1)
        self.assertEqual(planned[0].visual_type, VisualType.data)
        self.assertEqual(planned[0].payload.get("data", {}).get("numeric_value"), 6000)

    def test_batch_blast_radius_isolation(self):
        """Hard Acceptance: 1 invalid DATA decision out of 10 must NOT corrupt the other 9 valid decisions."""
        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Test", aspect_ratio=VideoAspect.landscape),
            script={"subject": "Car Insurance", "script": "10 cue script"},
            narration=NarrationSpec(mode="tts"),
        )
        timeline = [
            TimelineCue(id=f"S{i:03d}", order=i, start=float(i - 1), end=float(i), narration=f"Narration cue {i}")
            for i in range(1, 11)
        ]

        def response(_prompt):
            decisions = []
            for cue in timeline:
                if cue.id == "S005":
                    # Un-grounded fabricated number 999999
                    decisions.append(
                        {
                            "id": cue.id,
                            "order": cue.order,
                            "visual_type": "data",
                            "purpose": "explain",
                            "payload": {
                                "template": "number",
                                "headline": "Ungrounded",
                                "data": {"value": "$999,999", "numeric_value": 999999},
                            },
                        }
                    )
                else:
                    decisions.append(
                        {
                            "id": cue.id,
                            "order": cue.order,
                            "visual_type": "broll",
                            "purpose": "context",
                            "payload": {
                                "search_query": f"custom valid query for {cue.id}",
                                "fallback_queries": ["fallback query"],
                                "query_tiers": {"tier1": f"custom valid query for {cue.id}"},
                            },
                        }
                    )
            return json.dumps({"cues": decisions})

        planned = plan_visuals(project, timeline, response_fn=response)
        self.assertEqual(len(planned), 10)

        # 9 valid decisions must preserve their custom query
        for cue in planned:
            if cue.id != "S005":
                self.assertEqual(cue.visual_type, VisualType.broll)
                self.assertEqual(cue.payload.get("search_query"), f"custom valid query for {cue.id}")
            else:
                # S005 was invalid and fell back
                self.assertNotIn("999999", json.dumps(cue.payload))

    def test_real_insurance_script_visual_director_planning(self):
        """Verify the exact spoken-number insurance narrative produces rich structured DATA visuals."""
        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Insurance Breakdown", aspect_ratio=VideoAspect.landscape),
            script={
                "subject": "Car Insurance Coverage",
                "script": "Insurance Breakdown",
                "search_terms": ["car insurance", "collision coverage", "storm damage"],
            },
            narration=NarrationSpec(mode="tts"),
            timeline_cues=[
                TimelineCue(id="S013", order=13, start=0.0, end=3.5, narration="Suppose repairing your car costs six thousand dollars."),
                TimelineCue(id="S014", order=14, start=3.5, end=6.5, narration="Your collision deductible is one thousand dollars."),
                TimelineCue(id="S015", order=15, start=6.5, end=10.0, narration="You would generally be responsible for the first one thousand dollars,"),
                TimelineCue(id="S016", order=16, start=10.0, end=14.0, narration="while the insurance company could cover the remaining five thousand dollars,"),
                TimelineCue(id="S018", order=18, start=14.0, end=17.5, narration="Your premium is what you pay to keep the insurance policy active versus your deductible."),
                TimelineCue(id="S022", order=22, start=17.5, end=21.5, narration="Your car is parked outside during a storm, and a tree branch falls on it."),
                TimelineCue(id="S030", order=30, start=21.5, end=25.5, narration="Imagine you have twenty-five thousand dollars of property damage liability coverage,"),
                TimelineCue(id="S031", order=31, start=25.5, end=30.0, narration="but you cause forty thousand dollars in covered damage."),
            ],
        )

        planned = plan_visuals(
            project,
            project.timeline_cues,
            response_fn=lambda p: json.dumps({"cues": []}),  # Force deterministic fallback evaluation
        )

        planned_by_id = {c.id: c for c in planned}

        # S013: 6000 -> DATA Number / Repair Cost
        self.assertEqual(planned_by_id["S013"].visual_type, VisualType.data)
        self.assertEqual(planned_by_id["S013"].payload.get("data", {}).get("value"), "$6,000")

        # S014: 1000 -> DATA Number / Deductible
        self.assertEqual(planned_by_id["S014"].visual_type, VisualType.data)
        self.assertEqual(planned_by_id["S014"].payload.get("data", {}).get("value"), "$1,000")

        # S016: 5000 -> DATA Number / Coverage
        self.assertEqual(planned_by_id["S016"].visual_type, VisualType.data)
        self.assertEqual(planned_by_id["S016"].payload.get("data", {}).get("value"), "$5,000")

        # S018: Premium vs Deductible -> DATA Comparison
        self.assertEqual(planned_by_id["S018"].visual_type, VisualType.data)
        self.assertEqual(planned_by_id["S018"].payload.get("template"), "comparison")

        # S022: Tree branch storm -> BROLL with action intent
        self.assertEqual(planned_by_id["S022"].visual_type, VisualType.broll)
        intent = planned_by_id["S022"].payload.get("semantic_intent", {})
        self.assertIn("tree branch", intent.get("must_show_concepts", []))

        # S030 + S031: 25000 vs 40000 -> DATA
        self.assertEqual(planned_by_id["S030"].visual_type, VisualType.data)
        self.assertEqual(planned_by_id["S031"].visual_type, VisualType.data)

    def test_broll_failure_fallback_in_orchestrator(self):
        """B-roll acquisition failure must trigger Remotion TEXT fallback and resolve cleanly in manifest."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            cue = VisualCue(
                id="S027",
                order=27,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                start=0.0,
                end=3.0,
                narration="Collision is mainly about crash damage to your own vehicle.",
                payload={"search_query": "damaged vehicle at repair shop"},
            )
            project = ProjectSpec(
                schema_version="1.0",
                project=ProjectMetadata(title="Test", aspect_ratio=VideoAspect.landscape, fps=30),
                script={"subject": "Car Insurance", "script": cue.narration},
                narration=NarrationSpec(mode="tts"),
                timeline_cues=[
                    TimelineCue(id=cue.id, order=cue.order, start=cue.start, end=cue.end, narration=cue.narration)
                ],
                visual_cues=[cue],
            )

            # Mock B-roll acquisition to fail
            with patch("app.services.scene_orchestrator.run_broll_acquisition") as mock_broll:
                mock_broll.return_value = {
                    "status": "failed",
                    "ready_count": 0,
                    "failed_count": 1,
                    "error": "All candidates failed download",
                }
                with patch("app.services.scene_orchestrator._is_planning_reusable", return_value=(False, "new")):
                    with patch("app.services.scene_orchestrator.run_project_plan") as mock_plan:
                        mock_plan.return_value = {"status": "complete"}
                        # Write planned project
                        (task_dir / "project.planned.json").write_text(
                            json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8"
                        )
                        (task_dir / "project.normalized.json").write_text(
                            json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8"
                        )
                        (task_dir / "visual_plan.json").write_text(
                            json.dumps({"schema_version": "1.0", "cues": [cue.model_dump(mode="json")]}), encoding="utf-8"
                        )
                        (task_dir / "timeline.json").write_text(
                            json.dumps({"cues": [{"id": "S027", "order": 27, "start": 0.0, "end": 3.0}], "duration": 3.0}), encoding="utf-8"
                        )

                        # Mock Remotion render to produce dummy mp4
                        with patch("app.services.scene_orchestrator.render_scene_motion") as mock_motion:
                            dummy_mp4 = task_dir / "motion" / "S027_TEXT.mp4"
                            dummy_mp4.parent.mkdir(parents=True, exist_ok=True)
                            dummy_mp4.write_bytes(b"dummy")
                            mock_asset = MagicMock()
                            mock_asset.output_file = str(dummy_mp4)
                            mock_asset.duration_frames = 90
                            mock_asset.fps = 30
                            mock_asset.metadata = {"spec_fingerprint": "fp123"}
                            mock_motion.return_value = mock_asset

                            with (
                                patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(task_dir)),
                                patch("app.services.scene_orchestrator.validate_rendered_motion_clip", return_value=3.0),
                            ):
                                res = run_all_project(
                                    project_input=project,
                                    task_id="test-broll-fb-001",
                                )
                                self.assertEqual(res.get("status"), "complete")
                                self.assertEqual(res.get("ready_scenes"), 1)
                                self.assertEqual(res.get("failed_scenes"), 0)

                                em_path = task_dir / "execution_manifest.json"
                                self.assertTrue(em_path.exists())
                                em = json.loads(em_path.read_text(encoding="utf-8"))
                                scene_rec = em["scenes"][0]
                                self.assertEqual(scene_rec["scene_id"], "S027")
                                self.assertEqual(scene_rec["planned_visual_type"], "broll")
                                self.assertEqual(scene_rec["resolved_visual_type"], "text")
                                self.assertEqual(scene_rec["fallback_from"], "broll")
                                self.assertEqual(scene_rec["status"], "ready")


if __name__ == "__main__":
    unittest.main()
