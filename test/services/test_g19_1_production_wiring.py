from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.models.motion import (
    MotionSceneSpec,
    RendererFamily,
    SemanticDataIntent,
    VisualGrammar,
)
from app.models.project import (
    ProjectSpec,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import MotionRenderValidationError, render_scene_motion
from app.services.visual_renderer_director import VisualDiversityMemoryV2, VisualRendererDirector


class TestG191ProductionWiring(unittest.TestCase):
    """Hard assertion unit tests for G19.1 production wiring hardening."""

    def setUp(self) -> None:
        self.project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Production Wiring Test", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "technology", "script": "Testing production wiring."},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

    def test_diagram_normalizer_valid(self) -> None:
        """Assert diagram input parses to rendered_template == 'diagram' with valid nodes and edges."""
        cue = VisualCue(
            id="diag_01",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=4.0,
            narration="Requests flow from ingress proxy through cache into the database.",
            payload={
                "template": "diagram",
                "headline": "SYSTEM PIPELINE",
                "data": {
                    "nodes": [
                        {"id": "n1", "label": "INGRESS"},
                        {"id": "n2", "label": "CACHE"},
                        {"id": "n3", "label": "DATABASE"},
                    ],
                    "edges": [
                        {"from_node": "n1", "to_node": "n2", "label": "lookup"},
                        {"from_node": "n2", "to_node": "n3", "label": "miss"},
                    ],
                    "flow_direction": "horizontal",
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "diagram")
        self.assertEqual(spec.visual_grammar, VisualGrammar.diagram)
        self.assertEqual(spec.data_intent, SemanticDataIntent.sequence)
        self.assertIsNone(spec.fallback_reason)
        nodes = spec.props.get("nodes", [])
        edges = spec.props.get("edges", [])
        self.assertEqual(len(nodes), 3)
        self.assertEqual(len(edges), 2)
        self.assertEqual(nodes[0].get("id"), "n1")
        self.assertEqual(edges[0].get("from_node"), "n1")

    def test_diagram_normalizer_invalid_fallback(self) -> None:
        """Assert invalid diagram input (<2 nodes or bad edge IDs) cleanly falls back to callout."""
        cue = VisualCue(
            id="diag_02",
            order=2,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Isolated node without connections.",
            payload={
                "template": "diagram",
                "headline": "BROKEN DIAGRAM",
                "data": {"nodes": [{"id": "single_node", "label": "ALONE"}]},
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "callout")
        self.assertIsNotNone(spec.fallback_reason)

    def test_data_grid_normalizer_valid(self) -> None:
        """Assert data_grid input parses to rendered_template == 'data_grid' with preserved items."""
        cue = VisualCue(
            id="grid_01",
            order=3,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=4.0,
            narration="Platform health telemetry displays high availability across core regions.",
            payload={
                "template": "data_grid",
                "headline": "SYSTEM METRICS",
                "data": {
                    "items": [
                        {"label": "UPTIME", "value": "99.99%", "status": "nominal", "highlight": True},
                        {"label": "LATENCY", "value": "28ms", "status": "nominal"},
                        {"label": "REQUESTS", "value": "1.4M/s", "status": "nominal"},
                        {"label": "ERROR RATE", "value": "0.02%", "status": "nominal"},
                    ],
                    "columns": 2,
                    "eyebrow": "PLATFORM TELEMETRY",
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "data_grid")
        self.assertEqual(spec.visual_grammar, VisualGrammar.data_grid)
        self.assertIsNone(spec.fallback_reason)
        items = spec.props.get("items", [])
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0].get("label"), "UPTIME")
        self.assertEqual(items[0].get("value"), "99.99%")
        self.assertEqual(spec.props.get("columns"), 2)

    def test_data_grid_normalizer_invalid_fallback(self) -> None:
        """Assert invalid data_grid input (<3 items) cleanly falls back to callout."""
        cue = VisualCue(
            id="grid_02",
            order=4,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Insufficient grid metrics.",
            payload={
                "template": "data_grid",
                "headline": "TOO FEW ITEMS",
                "data": {"items": [{"label": "A", "value": "1"}, {"label": "B", "value": "2"}]},
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "callout")
        self.assertIsNotNone(spec.fallback_reason)

    def test_hybrid_broll_normalizer_with_real_file(self) -> None:
        """Assert valid hybrid B-roll with existing asset on disk resolves to rendered_template == 'hybrid_broll'."""
        real_asset = Path("test/resources/1.png.mp4").resolve()
        self.assertTrue(real_asset.exists(), f"Fixture missing: {real_asset}")

        cue = VisualCue(
            id="hyb_01",
            order=5,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Datacenter throughput scales up to 100 gigabits per second.",
            payload={
                "template": "hybrid_broll",
                "headline": "NETWORK THROUGHPUT",
                "data": {
                    "asset_path": str(real_asset),
                    "value": "100 Gbps",
                    "label": "Throughput",
                    "broll_confidence": 0.88,
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "hybrid_broll")
        self.assertEqual(spec.visual_grammar, VisualGrammar.hybrid_broll)
        self.assertIsNone(spec.fallback_reason)
        self.assertEqual(spec.props.get("asset_path"), str(real_asset))
        self.assertEqual(spec.renderer_decision.renderer_family, RendererFamily.hybrid_broll_data)

    def test_hybrid_broll_normalizer_missing_file_fallback(self) -> None:
        """Assert hybrid B-roll with missing file falls back to editorial number/callout, NOT placeholder."""
        cue = VisualCue(
            id="hyb_02",
            order=6,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Datacenter throughput scales up to 100 gigabits per second.",
            payload={
                "template": "hybrid_broll",
                "headline": "NETWORK THROUGHPUT",
                "data": {
                    "asset_path": "nonexistent_directory/nonexistent_file.mp4",
                    "value": "100 Gbps",
                    "numeric_value": 100.0,
                    "label": "Throughput",
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project)
        self.assertEqual(spec.rendered_template, "number")
        self.assertIn("Hybrid B-roll asset missing", spec.fallback_reason or "")
        self.assertEqual(spec.props.get("value"), "100 Gbps")

    def test_shared_renderer_director_diversity_memory(self) -> None:
        """Assert a single shared VisualRendererDirector across multiple metric cues provides diverse storytelling techniques."""
        director = VisualRendererDirector(VisualDiversityMemoryV2())
        metric_cues = [
            VisualCue(
                id="cue_m1", order=1, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=0.0, end=3.0, narration="First metric hits five hundred.",
                payload={"template": "number", "headline": "FIRST METRIC", "data": {"value": "500", "numeric_value": 500.0}},
            ),
            VisualCue(
                id="cue_m2", order=2, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=3.0, end=6.0, narration="Second metric reaches eight hundred.",
                payload={"template": "number", "headline": "SECOND METRIC", "data": {"value": "800", "numeric_value": 800.0}},
            ),
            VisualCue(
                id="cue_m3", order=3, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=6.0, end=9.0, narration="Third metric climbs to one thousand two hundred.",
                payload={"template": "number", "headline": "THIRD METRIC", "data": {"value": "1,200", "numeric_value": 1200.0}},
            ),
        ]

        specs = [
            normalize_motion_spec(c, self.project, renderer_director=director)
            for c in metric_cues
        ]

        techniques = [
            s.renderer_decision.storytelling_technique.value
            if hasattr(s.renderer_decision.storytelling_technique, "value")
            else str(s.renderer_decision.storytelling_technique)
            for s in specs
        ]
        self.assertEqual(len(techniques), 3)
        self.assertEqual(techniques[0], "metric_punch")
        self.assertEqual(techniques[1], "metric_context")
        self.assertEqual(techniques[2], "metric_delta")

    def test_pre_render_hybrid_rejection_without_file(self) -> None:
        """Assert render_scene_motion strictly raises MotionRenderValidationError if hybrid_broll asset does not exist on disk."""
        spec = MotionSceneSpec(
            scene_id="hyb_raw",
            order=1,
            visual_type="data",
            requested_template="hybrid_broll",
            rendered_template="hybrid_broll",
            props={"headline": "TEST", "asset_path": "fake/missing.mp4"},
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1920,
            height=1080,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(MotionRenderValidationError):
                render_scene_motion(spec, Path(tmpdir))


if __name__ == "__main__":
    unittest.main()
