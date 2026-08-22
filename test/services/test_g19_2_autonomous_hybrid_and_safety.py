from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models.motion import (
    MotionSceneSpec,
    RendererDecision,
    RendererFamily,
    SemanticDataIntent,
    StorytellingTechnique,
    VisualGrammar,
)
from app.models.project import (
    AssetJob,
    JobStatus,
    ProjectSpec,
    ProjectStatus,
    SelectedBrollAsset,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.broll_runner import run_broll_acquisition
from app.services.data_visualization_director import DataVisualizationDirector
from app.services.motion_normalizer import normalize_motion_spec
from app.services.project_spec import load_project_spec
from app.services.visual_planner import plan_visuals
from app.services.visual_renderer_director import VisualDiversityMemoryV2, VisualRendererDirector


class TestG192AutonomousHybridAndSafety(unittest.TestCase):
    """Hard unit and safety test suite for G19.2 requirements."""

    def setUp(self) -> None:
        self.director = DataVisualizationDirector()
        self.renderer_director = VisualRendererDirector(VisualDiversityMemoryV2())
        self.test_dir = Path(tempfile.mkdtemp(prefix="g19_2_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_dummy_video(self, filename: str = "asset.mp4") -> Path:
        p = self.test_dir / filename
        p.write_bytes(b"\x00\x00\x00 ftypmp42\x00\x00\x00\x00isommp42")
        return p

    def test_autonomous_hybrid_acquisition_high_confidence(self) -> None:
        """Test autonomous hybrid acquisition when stock score >= 0.70 and file exists."""
        dummy_mp4 = self._create_dummy_video("cloud_footage.mp4")

        project = ProjectSpec(
            schema_version="1.0",
            project={"title": "Cloud Platform", "aspect_ratio": "16:9", "fps": 30},
            script={"script": "Our platform generates twelve million dollars ARR.", "subject": "Cloud Computing"},
            narration={"mode": "tts"},
            timeline_cues=[
                TimelineCue(id="C01", order=1, start=0.0, end=5.0, narration="Our platform generates twelve million dollars ARR.")
            ],
            visual_cues=[
                VisualCue(
                    id="C01",
                    order=1,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=0.0,
                    end=5.0,
                    narration="Our platform generates twelve million dollars ARR.",
                    payload={
                        "template": "number",
                        "headline": "ANNUAL REVENUE",
                        "hybrid_eligible": True,
                        "data": {"value": "$12M", "numeric_value": 12000000.0, "label": "ARR"},
                    },
                )
            ],
        )

        # Write planned artifacts into task dir to simulate completed planning
        task_dir = Path("storage/tasks/task_hybrid_high")
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "project.planned.json").write_text(project.model_dump_json(indent=2), encoding="utf-8")
        (task_dir / "visual_plan.json").write_text("{}", encoding="utf-8")

        mock_asset = SelectedBrollAsset(
            scene_id="C01",
            provider="pexels",
            provider_asset_id="px123",
            candidate_id="c_px123",
            download_url="https://example.com/v.mp4",
            width=1920,
            height=1080,
            query_used="cloud datacenter",
            source_file=str(dummy_mp4),
            rendered_file=str(dummy_mp4),
            source_duration=10.0,
            scene_duration=5.0,
            trim_start=0.0,
            trim_end=5.0,
            score=0.88,
            score_breakdown={"relevance": 0.9, "quality": 0.85},
            metadata={"candidate_metadata": {"id": "px123"}},
        )

        with patch("app.services.broll_runner.acquire_broll_scene", return_value=mock_asset), \
             patch("app.services.broll_runner.preflight_project"):
            result = run_broll_acquisition(project, task_id="task_hybrid_high")

        self.assertEqual(result["ready_count"], 1)
        enriched_project = load_project_spec(result["assets_project_file"])
        self.assertEqual(enriched_project.visual_cues[0].payload["asset_path"], str(dummy_mp4))
        self.assertAlmostEqual(enriched_project.visual_cues[0].payload["broll_confidence"], 0.88, places=2)

        # Run motion normalization
        spec = normalize_motion_spec(
            enriched_project.visual_cues[0],
            enriched_project,
            director=self.director,
            renderer_director=self.renderer_director,
        )

        self.assertEqual(spec.rendered_template, "hybrid_broll")
        self.assertEqual(spec.renderer_decision.renderer_family, RendererFamily.hybrid_broll_data)
        self.assertAlmostEqual(spec.renderer_decision.asset_confidence, 0.88, places=2)
        self.assertEqual(spec.props["asset_path"], str(dummy_mp4))

    def test_autonomous_hybrid_weak_candidate_fallback(self) -> None:
        """Test fallback to editorial DATA when stock candidate score < 0.70."""
        dummy_mp4 = self._create_dummy_video("weak_footage.mp4")

        project = ProjectSpec(
            schema_version="1.0",
            project={"title": "Cloud Platform", "aspect_ratio": "16:9", "fps": 30},
            script={"script": "Our platform generates twelve million dollars ARR.", "subject": "Cloud Computing"},
            narration={"mode": "tts"},
            timeline_cues=[
                TimelineCue(id="C01", order=1, start=0.0, end=5.0, narration="Our platform generates twelve million dollars ARR.")
            ],
            visual_cues=[
                VisualCue(
                    id="C01",
                    order=1,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=0.0,
                    end=5.0,
                    narration="Our platform generates twelve million dollars ARR.",
                    payload={
                        "template": "number",
                        "headline": "ANNUAL REVENUE",
                        "hybrid_eligible": True,
                        "data": {"value": "$12M", "numeric_value": 12000000.0, "label": "ARR"},
                    },
                )
            ],
        )

        task_dir = Path("storage/tasks/task_hybrid_weak")
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "project.planned.json").write_text(project.model_dump_json(indent=2), encoding="utf-8")
        (task_dir / "visual_plan.json").write_text("{}", encoding="utf-8")

        mock_asset = SelectedBrollAsset(
            scene_id="C01",
            provider="pexels",
            provider_asset_id="px456",
            candidate_id="c_px456",
            download_url="https://example.com/v_weak.mp4",
            width=1920,
            height=1080,
            query_used="vague search",
            source_file=str(dummy_mp4),
            rendered_file=str(dummy_mp4),
            source_duration=10.0,
            scene_duration=5.0,
            trim_start=0.0,
            trim_end=5.0,
            score=0.52,
            score_breakdown={"relevance": 0.5, "quality": 0.55},
        )

        with patch("app.services.broll_runner.acquire_broll_scene", return_value=mock_asset), \
             patch("app.services.broll_runner.preflight_project"):
            result = run_broll_acquisition(project, task_id="task_hybrid_weak")

        enriched_project = load_project_spec(result["assets_project_file"])
        self.assertIsNone(enriched_project.visual_cues[0].payload.get("asset_path"))
        self.assertAlmostEqual(enriched_project.visual_cues[0].payload.get("broll_confidence"), 0.52, places=2)

        spec = normalize_motion_spec(
            enriched_project.visual_cues[0],
            enriched_project,
            director=self.director,
            renderer_director=self.renderer_director,
        )

        self.assertEqual(spec.rendered_template, "number")
        self.assertEqual(spec.renderer_decision.renderer_family, RendererFamily.editorial_remotion)

    def test_user_provided_local_asset_origin(self) -> None:
        """Test trusted user-provided local media without inventing a fake stock confidence score."""
        dummy_mp4 = self._create_dummy_video("user_upload.mp4")

        project = ProjectSpec(
            schema_version="1.0",
            project={"title": "Demo", "aspect_ratio": "16:9", "fps": 30},
            script={"script": "Revenue reached five million dollars.", "subject": "Finance"},
            narration={"mode": "tts"},
            timeline_cues=[TimelineCue(id="C01", order=1, start=0.0, end=5.0, narration="Revenue reached five million dollars.")],
            visual_cues=[
                VisualCue(
                    id="C01",
                    order=1,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=0.0,
                    end=5.0,
                    narration="Revenue reached five million dollars.",
                    payload={
                        "template": "hybrid_broll",
                        "headline": "REVENUE",
                        "asset_path": str(dummy_mp4),
                        "asset_origin": "user_provided",
                        "data": {"value": "$5M", "numeric_value": 5000000.0, "label": "Revenue"},
                    },
                )
            ],
        )

        spec = normalize_motion_spec(
            project.visual_cues[0],
            project,
            director=self.director,
            renderer_director=self.renderer_director,
        )

        self.assertEqual(spec.rendered_template, "hybrid_broll")
        self.assertEqual(spec.renderer_decision.renderer_family, RendererFamily.hybrid_broll_data)
        self.assertEqual(spec.renderer_decision.asset_origin, "user_provided")
        self.assertEqual(spec.props["asset_path"], str(dummy_mp4))

    def test_metric_delta_positive_direction(self) -> None:
        """Test metric_delta extraction and positive direction for 'Revenue grew from $2M to $3M'."""
        project = ProjectSpec(
            schema_version="1.0",
            project={"title": "Growth", "aspect_ratio": "16:9", "fps": 30},
            script={"script": "Revenue grew from $2M to $3M.", "subject": "Growth"},
            narration={"mode": "tts"},
            timeline_cues=[TimelineCue(id="C01", order=1, start=0.0, end=5.0, narration="Revenue grew from $2M to $3M.")],
            visual_cues=[
                VisualCue(
                    id="C01",
                    order=1,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=0.0,
                    end=5.0,
                    narration="Revenue grew from $2M to $3M.",
                    payload={
                        "template": "number",
                        "headline": "REVENUE GROWTH",
                        "data": {"value": "$3M", "numeric_value": 3000000.0},
                    },
                )
            ],
        )

        spec = normalize_motion_spec(
            project.visual_cues[0],
            project,
            director=self.director,
            renderer_director=self.renderer_director,
        )

        self.assertEqual(spec.rendered_template, "number")
        self.assertEqual(spec.renderer_decision.storytelling_technique, StorytellingTechnique.metric_delta)
        self.assertEqual(spec.props.get("delta_direction"), "positive")
        self.assertEqual(spec.props.get("before_value"), "$2M")
        self.assertEqual(spec.props.get("after_value"), "$3M")
        self.assertEqual(spec.props.get("delta_value"), "+$1M")

    def test_metric_delta_negative_direction(self) -> None:
        """Test metric_delta extraction and negative direction for 'Latency fell from 80ms to 42ms'."""
        project = ProjectSpec(
            schema_version="1.0",
            project={"title": "Optimization", "aspect_ratio": "16:9", "fps": 30},
            script={"script": "Latency fell from 80ms to 42ms.", "subject": "Performance"},
            narration={"mode": "tts"},
            timeline_cues=[TimelineCue(id="C01", order=1, start=0.0, end=5.0, narration="Latency fell from 80ms to 42ms.")],
            visual_cues=[
                VisualCue(
                    id="C01",
                    order=1,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=0.0,
                    end=5.0,
                    narration="Latency fell from 80ms to 42ms.",
                    payload={
                        "template": "number",
                        "headline": "LATENCY IMPROVEMENT",
                        "data": {"value": "42ms", "numeric_value": 42.0},
                    },
                )
            ],
        )

        spec = normalize_motion_spec(
            project.visual_cues[0],
            project,
            director=self.director,
            renderer_director=self.renderer_director,
        )

        self.assertEqual(spec.rendered_template, "number")
        self.assertEqual(spec.renderer_decision.storytelling_technique, StorytellingTechnique.metric_delta)
        self.assertEqual(spec.props.get("delta_direction"), "negative")
        self.assertEqual(spec.props.get("before_value"), "80ms")
        self.assertEqual(spec.props.get("after_value"), "42ms")
        self.assertEqual(spec.props.get("delta_value"), "-38ms")

    def test_metric_non_delta_diversity_never_selects_delta(self) -> None:
        """Test that static metric 'Revenue is $3M' is NEVER mapped to metric_delta due to repetition."""
        memory = VisualDiversityMemoryV2()
        decision_punch = RendererDecision(
            renderer_family=RendererFamily.editorial_remotion,
            storytelling_technique=StorytellingTechnique.metric_punch,
            composition_pattern="centered_hero", # type: ignore
            motion_pattern="punch_in", # type: ignore
        )
        decision_context = RendererDecision(
            renderer_family=RendererFamily.editorial_remotion,
            storytelling_technique=StorytellingTechnique.metric_context,
            composition_pattern="centered_hero", # type: ignore
            motion_pattern="camera_push", # type: ignore
        )
        memory.record(decision_punch)
        memory.record(decision_context)

        renderer_director = VisualRendererDirector(memory)

        cue = VisualCue(
            id="C03",
            order=3,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=10.0,
            end=15.0,
            narration="Current revenue is three million dollars.",
            payload={"template": "number", "headline": "REVENUE", "data": {"value": "$3M", "numeric_value": 3000000.0}},
        )

        decision = renderer_director.decide_renderer(
            data_intent=SemanticDataIntent.single_metric,
            visual_grammar=VisualGrammar.metric,
            template="number",
            props={"value": "$3M", "numeric_value": 3000000.0},
            narration=cue.narration,
        )

        self.assertNotEqual(decision.storytelling_technique, StorytellingTechnique.metric_delta)
        self.assertIn(decision.storytelling_technique, (StorytellingTechnique.metric_punch, StorytellingTechnique.metric_context))

    def test_diagram_grounding_no_invented_technologies(self) -> None:
        """Test diagram extraction strictly respects grounded words without hallucinating prefixes."""
        valid, props, err = self.director.validate_and_build_props(
            grammar=VisualGrammar.diagram,
            variant="flow_diagram",
            intent=SemanticDataIntent.sequence,
            narration="Incoming web traffic flows through cache before querying the database.",
            facts=[],
            headline="SYSTEM FLOW",
            cue_payload={"template": "diagram", "headline": "SYSTEM FLOW"},
        )
        self.assertTrue(valid)
        labels = [n["label"] for n in props["nodes"]]
        self.assertIn("CACHE", labels)
        self.assertNotIn("REDIS CACHE", labels)
        self.assertIn("DATABASE", labels)
        self.assertNotIn("POSTGRES DB", labels)

        valid2, props2, err2 = self.director.validate_and_build_props(
            grammar=VisualGrammar.diagram,
            variant="flow_diagram",
            intent=SemanticDataIntent.sequence,
            narration="Incoming web traffic flows through edge proxy into redis cache before querying the database.",
            facts=[],
            headline="SYSTEM FLOW",
            cue_payload={"template": "diagram", "headline": "SYSTEM FLOW"},
        )
        self.assertTrue(valid2)
        labels2 = [n["label"] for n in props2["nodes"]]
        self.assertIn("EDGE PROXY", labels2)
        self.assertIn("REDIS CACHE", labels2)


if __name__ == "__main__":
    unittest.main()
