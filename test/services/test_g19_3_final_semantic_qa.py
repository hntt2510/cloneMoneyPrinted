from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.models.motion import RendererDecision, RendererFamily, StorytellingTechnique, VisualGrammar
from app.models.project import DataPayload, JobStatus, ProjectSpec, TimelineCue, VisualCue, VisualPurpose, VisualType
from app.services.broll_runner import run_broll_acquisition
from app.services.data_visualization_director import DataVisualizationDirector, extract_grounded_timeline_milestones
from app.services.motion_normalizer import normalize_motion_spec
from app.services.visual_planner import adapt_data_visual_cue
from app.services.visual_renderer_director import VisualDiversityMemoryV2, VisualRendererDirector


class TestG193FinalSemanticQA(unittest.TestCase):
    """G19.3 Final Semantic QA Closure unit tests."""

    def setUp(self) -> None:
        self.director = DataVisualizationDirector()
        self.renderer_director = VisualRendererDirector(VisualDiversityMemoryV2())
        self.project_stub = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Test Project", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "Test", "script": "Narration text."},
            "narration": {"mode": "tts"},
            "timeline_cues": [],
            "visual_cues": [],
        })

    def test_timeline_fact_grounding_no_fabrication(self) -> None:
        """Requirement 1 & 11.A: 'Revenue was $2M in 2022 and $4M in 2026.' must NOT contain 'Beta Launch' or 'Global Scaling'."""
        narration = "Revenue was $2M in 2022 and $4M in 2026."
        milestones = extract_grounded_timeline_milestones(narration)

        self.assertEqual(len(milestones), 2)
        self.assertEqual(milestones[0]["time"], "2022")
        self.assertEqual(milestones[1]["time"], "2026")

        # Titles must be strictly grounded ($2M, $4M or neutral START/END)
        titles_combined = " ".join(m["title"] for m in milestones).upper()
        self.assertNotIn("BETA LAUNCH", titles_combined)
        self.assertNotIn("GLOBAL SCALING", titles_combined)
        self.assertNotIn("GLOBAL EXPANSION", titles_combined)
        self.assertNotIn("MIGRATION", titles_combined)
        self.assertNotIn("RELEASE", titles_combined)

        # Full director validation
        spec = self.director.direct_visual_specification(
            narration=narration,
            headline="REVENUE GROWTH",
            cue_payload={"template": "timeline", "headline": "REVENUE GROWTH"},
            source_cue_id="C001",
        )
        self.assertEqual(spec.grammar, VisualGrammar.timeline)
        directed_titles = " ".join(m["title"] for m in spec.props.get("milestones", [])).upper()
        self.assertNotIn("BETA LAUNCH", directed_titles)
        self.assertNotIn("GLOBAL SCALING", directed_titles)

    def test_timeline_grounded_event_extraction(self) -> None:
        """Requirement 2 & 11.B: 'Between 2022 beta launch and 2026 global expansion...' produces exact grounded titles."""
        narration = "Between 2022 beta launch and 2026 global expansion, platform traffic surged."
        milestones = extract_grounded_timeline_milestones(narration)

        self.assertEqual(len(milestones), 2)
        self.assertEqual(milestones[0]["time"], "2022")
        self.assertEqual(milestones[0]["title"], "BETA LAUNCH")
        self.assertEqual(milestones[1]["time"], "2026")
        self.assertEqual(milestones[1]["title"], "GLOBAL EXPANSION")

        # Also works with spoken years
        spoken_narration = "Between twenty twenty-two beta launch and twenty twenty-six global expansion, cluster footprint expanded worldwide."
        spoken_milestones = extract_grounded_timeline_milestones(spoken_narration)
        self.assertEqual(len(spoken_milestones), 2)
        self.assertEqual(spoken_milestones[0]["time"], "2022")
        self.assertEqual(spoken_milestones[0]["title"], "BETA LAUNCH")
        self.assertEqual(spoken_milestones[1]["time"], "2026")
        self.assertEqual(spoken_milestones[1]["title"], "GLOBAL EXPANSION")

    def test_timeline_neutral_fallback(self) -> None:
        """Requirement 2: 'From 2022 to 2026 revenue doubled.' produces neutral labels without fabricating event names."""
        narration = "From 2022 to 2026 revenue doubled."
        milestones = extract_grounded_timeline_milestones(narration)
        self.assertEqual(len(milestones), 2)
        self.assertEqual(milestones[0]["time"], "2022")
        self.assertEqual(milestones[1]["time"], "2026")
        self.assertIn(milestones[0]["title"], ("START", "PHASE 1", ""))
        self.assertIn(milestones[1]["title"], ("END", "PHASE 2", ""))
        for forbidden in ("BETA LAUNCH", "GLOBAL SCALING", "EXPANSION", "RELEASE", "MIGRATION"):
            self.assertNotIn(forbidden, milestones[0]["title"].upper())
            self.assertNotIn(forbidden, milestones[1]["title"].upper())

    def test_delta_direction_vs_sentiment_neutral_decrease(self) -> None:
        """Requirement 3 & 11.C: 'Latency fell from 80ms to 42ms.' -> negative direction, neutral sentiment (not warning red)."""
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=5.0,
            narration="Latency fell from 80ms to 42ms.",
            payload=DataPayload(
                template="number",
                headline="SYSTEM LATENCY",
                data={"value": "42ms", "numeric_value": 42.0},
            ).model_dump(mode="json"),
        )
        spec = normalize_motion_spec(cue, self.project_stub)
        props = spec.props

        # Mathematical direction is negative (fell / decreased)
        self.assertEqual(props.get("delta_direction"), "negative")
        self.assertEqual(props.get("before_value"), "80ms")
        self.assertEqual(props.get("after_value"), "42ms")

        # Semantic sentiment is neutral/unknown (not automatically warning red)
        self.assertEqual(props.get("delta_sentiment"), "neutral")

    def test_delta_direction_vs_sentiment_positive_improvement(self) -> None:
        """Requirement 4 & 11.D: 'Latency improved from 80ms to 42ms.' -> negative direction, positive sentiment."""
        cue = VisualCue(
            id="S002",
            order=2,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=5.0,
            narration="Latency improved from 80ms to 42ms across all edge nodes.",
            payload=DataPayload(
                template="number",
                headline="EDGE LATENCY",
                data={"value": "42ms", "numeric_value": 42.0},
            ).model_dump(mode="json"),
        )
        spec = normalize_motion_spec(cue, self.project_stub)
        props = spec.props

        self.assertEqual(props.get("delta_direction"), "negative")
        self.assertEqual(props.get("delta_sentiment"), "positive")

    def test_delta_direction_vs_sentiment_negative_worsening(self) -> None:
        """Requirement 4: 'Error rate worsened from 2% to 5%.' -> positive direction, negative sentiment."""
        cue = VisualCue(
            id="S003",
            order=3,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=5.0,
            narration="The daily error rate worsened from 2% to 5% after the deployment.",
            payload=DataPayload(
                template="number",
                headline="ERROR RATE",
                data={"value": "5%", "numeric_value": 5.0},
            ).model_dump(mode="json"),
        )
        spec = normalize_motion_spec(cue, self.project_stub)
        props = spec.props

        self.assertEqual(props.get("delta_direction"), "positive")
        self.assertEqual(props.get("delta_sentiment"), "negative")

    def test_user_provided_asset_score_truthfulness(self) -> None:
        """Requirement 5 & 11.E: User-provided media has asset_origin='user_provided' without fake 1.0 stock score."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            user_media = Path(tmp_dir) / "custom_user_clip.mp4"
            user_media.write_bytes(b"\x00" * 1024)

            # 1. Test Director decision
            decision = self.renderer_director.decide_renderer(
                data_intent=None,
                visual_grammar=None,
                template="number",
                props={"asset_path": str(user_media), "asset_origin": "user_provided"},
                narration="Annual recurring revenue reached twelve million dollars.",
                broll_candidate_confidence=0.0,
                broll_candidate_path=str(user_media),
            )
            self.assertEqual(decision.renderer_family, RendererFamily.hybrid_broll_data)
            self.assertEqual(decision.asset_origin, "user_provided")
            self.assertIsNone(decision.asset_confidence, "User provided media must not claim fake 1.0 confidence")
            self.assertEqual(decision.asset_score_source, "not_scored_user_provided")

            # 2. Test B-roll acquisition runner truthfulness
            spec = ProjectSpec.model_validate({
                "schema_version": "1.0",
                "project": {"title": "User Asset Truth Test", "aspect_ratio": "16:9", "fps": 30},
                "script": {"subject": "Test", "script": "Revenue is twelve million dollars."},
                "narration": {"mode": "tts"},
                "timeline_cues": [
                    {"id": "C01", "order": 1, "start": 0.0, "end": 5.0, "narration": "Revenue is twelve million dollars."},
                ],
                "visual_cues": [
                    {
                        "id": "C01",
                        "order": 1,
                        "visual_type": "data",
                        "purpose": "explain",
                        "start": 0.0,
                        "end": 5.0,
                        "narration": "Revenue is twelve million dollars.",
                        "payload": {
                            "template": "number",
                            "headline": "ARR",
                            "hybrid_eligible": True,
                            "asset_origin": "user_provided",
                            "asset_path": str(user_media),
                        },
                    }
                ],
            })
            task_id = "task_user_truth"
            from app.utils import utils
            t_dir = Path(utils.task_dir(task_id))
            t_dir.mkdir(parents=True, exist_ok=True)
            proj_data = spec.model_dump(mode="json")
            proj_planned = t_dir / "project.planned.json"
            proj_planned.write_text(json.dumps(proj_data), encoding="utf-8")
            (t_dir / "visual_plan.json").write_text(json.dumps({"plan": "ok"}), encoding="utf-8")

            res = run_broll_acquisition(str(proj_planned), task_id=task_id)
            self.assertEqual(res["ready_count"], 1)

            # Inspect updated cue payload in project.assets.json
            assets_proj = json.loads((t_dir / "project.assets.json").read_text(encoding="utf-8"))
            asset_cue = assets_proj["visual_cues"][0]
            self.assertEqual(asset_cue["payload"].get("asset_origin"), "user_provided")
            self.assertIsNone(asset_cue["payload"].get("broll_confidence"))
            self.assertEqual(asset_cue["payload"].get("asset_score_source"), "not_scored_user_provided")

    def test_stock_asset_preserves_actual_score(self) -> None:
        """Requirement 6 & 11.F: Stock asset preserves actual acquisition score."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            stock_clip = Path(tmp_dir) / "stock_clip.mp4"
            stock_clip.write_bytes(b"\x00" * 1024)

            decision = self.renderer_director.decide_renderer(
                data_intent=None,
                visual_grammar=None,
                template="number",
                props={},
                narration="Platform revenue reached twelve million dollars.",
                broll_candidate_confidence=0.88,
                broll_candidate_path=str(stock_clip),
            )
            self.assertEqual(decision.renderer_family, RendererFamily.hybrid_broll_data)
            self.assertEqual(decision.asset_origin, "stock_search")
            self.assertEqual(decision.asset_confidence, 0.88)
            self.assertEqual(decision.asset_score_source, "stock_search")


if __name__ == "__main__":
    unittest.main()
