import os
import shutil
import tempfile
import unittest
from pathlib import Path

from app.models.motion import (
    SemanticDataIntent,
    VisualGrammar,
)
from app.models.project import (
    DataPayload,
    DataTemplate,
    ProjectSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.data_visualization_director import (
    DataVisualizationDirector,
    VisualDiversityMemory,
)
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_scene_motion, validate_rendered_motion_clip
from app.services.visual_planner import fallback_visual, plan_visuals


def _create_minimal_project() -> ProjectSpec:
    return ProjectSpec.model_validate(
        {
            "schema_version": "1.0",
            "project": {
                "title": "G17 Production Wiring Test",
                "aspect_ratio": "16:9",
                "fps": 30,
            },
            "script": {
                "subject": "Auto Insurance and Data Analysis",
                "script": "Narration text",
            },
            "narration": {
                "mode": "tts",
            },
        }
    )


class TestG17ProductionWiring(unittest.TestCase):
    def setUp(self) -> None:
        self.project = _create_minimal_project()
        self.director = DataVisualizationDirector()

    def test_data_template_enum_has_all_g17_templates(self) -> None:
        """Requirement 2: DataTemplate contract includes all G17 templates."""
        expected = {
            "number",
            "counter",
            "comparison",
            "timeline",
            "bar_chart",
            "line_chart",
            "threshold",
            "age_marker",
            "callout",
            "breakdown",
            "pie",
            "donut",
            "gauge",
            "waterfall",
            "ranked_list",
            "area",
            "before_after",
            "stacked_bar",
        }
        actual = {t.value for t in DataTemplate}
        self.assertTrue(expected.issubset(actual), f"Missing templates: {expected - actual}")

    def test_production_case_a_part_to_whole_pie(self) -> None:
        """Requirement 10 Case A: 40% Premium, 35% Standard, 25% Basic -> pie/donut."""
        cue = TimelineCue(
            id="C001",
            order=1,
            start=0.0,
            end=4.0,
            narration="40% chose Premium, 35% Standard, and 25% Basic.",
        )
        vis = fallback_visual(self.project, cue, director=self.director)
        self.assertEqual(vis.visual_type, VisualType.data)
        self.assertIn(vis.payload["template"], (DataTemplate.pie.value, DataTemplate.donut.value))
        self.assertIn("items", vis.payload["data"])
        self.assertEqual(len(vis.payload["data"]["items"]), 3)

        # Normalize through motion_normalizer
        spec = normalize_motion_spec(vis, self.project, director=self.director)
        self.assertEqual(spec.data_intent, SemanticDataIntent.part_to_whole)
        self.assertIn(spec.visual_grammar, (VisualGrammar.pie, VisualGrammar.donut))
        self.assertIn(spec.rendered_template, ("pie", "donut"))

    def test_production_case_b_trend_over_time_line(self) -> None:
        """Requirement 10 Case B: Premium increased from $120 in 2022 to $180 in 2026 -> line."""
        cue = TimelineCue(
            id="C002",
            order=2,
            start=4.0,
            end=8.0,
            narration="Premium increased from $120 in 2022 to $180 in 2026.",
        )
        vis = fallback_visual(self.project, cue, director=self.director)
        self.assertEqual(vis.visual_type, VisualType.data)
        self.assertEqual(vis.payload["template"], DataTemplate.line_chart.value)

        spec = normalize_motion_spec(vis, self.project, director=self.director)
        self.assertEqual(spec.data_intent, SemanticDataIntent.trend_over_time)
        self.assertEqual(spec.visual_grammar, VisualGrammar.line)
        self.assertEqual(spec.rendered_template, "line_chart")

    def test_production_case_c_category_comparison_bar(self) -> None:
        """Requirement 10 Case C: Plan A costs $120, Plan B $180, Plan C $230 -> bar."""
        cue = TimelineCue(
            id="C003",
            order=3,
            start=8.0,
            end=12.0,
            narration="Plan A costs $120, Plan B $180, Plan C $230.",
        )
        vis = fallback_visual(self.project, cue, director=self.director)
        self.assertEqual(vis.visual_type, VisualType.data)
        self.assertEqual(vis.payload["template"], DataTemplate.bar_chart.value)

        spec = normalize_motion_spec(vis, self.project, director=self.director)
        self.assertEqual(spec.data_intent, SemanticDataIntent.category_comparison)
        self.assertEqual(spec.visual_grammar, VisualGrammar.bar)
        self.assertEqual(spec.rendered_template, "bar_chart")

    def test_production_case_d_progress_gauge(self) -> None:
        """Requirement 10 Case D: 75% of the process is complete -> gauge."""
        cue = TimelineCue(
            id="C004",
            order=4,
            start=12.0,
            end=16.0,
            narration="75% of the process is complete.",
        )
        vis = fallback_visual(self.project, cue, director=self.director)
        self.assertEqual(vis.visual_type, VisualType.data)
        self.assertEqual(vis.payload["template"], DataTemplate.gauge.value)

        spec = normalize_motion_spec(vis, self.project, director=self.director)
        self.assertEqual(spec.data_intent, SemanticDataIntent.progress)
        self.assertEqual(spec.visual_grammar, VisualGrammar.gauge)
        self.assertEqual(spec.rendered_template, "gauge")

    def test_production_case_e_waterfall(self) -> None:
        """Requirement 10 Case E: Started at $100, added a $30 fee, received a $20 discount, and finished at $110."""
        cue = TimelineCue(
            id="C005",
            order=5,
            start=16.0,
            end=20.0,
            narration="Started at $100, added a $30 fee, received a $20 discount, and finished at $110.",
        )
        vis = fallback_visual(self.project, cue, director=self.director)
        self.assertEqual(vis.visual_type, VisualType.data)
        self.assertEqual(vis.payload["template"], DataTemplate.waterfall.value)

        spec = normalize_motion_spec(vis, self.project, director=self.director)
        self.assertEqual(spec.data_intent, SemanticDataIntent.positive_negative_change)
        self.assertEqual(spec.visual_grammar, VisualGrammar.waterfall)
        self.assertEqual(spec.rendered_template, "waterfall")

    def test_production_case_f_threshold_not_pie(self) -> None:
        """Requirement 10 Case F: Coverage limit is $25,000 while covered damage is $40,000 -> threshold, NOT pie."""
        cue = TimelineCue(
            id="C006",
            order=6,
            start=20.0,
            end=24.0,
            narration="Coverage limit is $25,000 while covered damage is $40,000.",
        )
        vis = fallback_visual(self.project, cue, director=self.director)
        self.assertEqual(vis.visual_type, VisualType.data)
        self.assertEqual(vis.payload["template"], DataTemplate.threshold.value)
        self.assertNotEqual(vis.payload["template"], DataTemplate.pie.value)

        spec = normalize_motion_spec(vis, self.project, director=self.director)
        self.assertEqual(spec.data_intent, SemanticDataIntent.threshold)
        self.assertEqual(spec.visual_grammar, VisualGrammar.threshold)
        self.assertEqual(spec.rendered_template, "threshold")

    def test_gauge_safety_rejects_unbounded_scalar(self) -> None:
        """Requirement 8: An arbitrary scalar like '$6,000' without percentage or max bound must NOT become a gauge."""
        cue = VisualCue(
            id="C_UNBOUNDED",
            order=1,
            start=0.0,
            end=3.0,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            narration="Suppose repairing your car costs $6,000.",
            payload={
                "template": "gauge",
                "headline": "REPAIR COST",
                "data": {
                    "current_value": 6000,
                    "display_value": "$6,000",
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project, director=self.director)
        # Must NOT be gauge
        self.assertNotEqual(spec.rendered_template, "gauge")
        self.assertEqual(spec.rendered_template, "number")
        self.assertIn("max", spec.fallback_reason.lower())

    def test_stacked_bar_safety_fallback_to_bar_without_whole(self) -> None:
        """Requirement 9: Stacked bar without grounded whole or matching sum falls back to ordinary bar chart."""
        cue = VisualCue(
            id="C_STACKED_INVALID",
            order=1,
            start=0.0,
            end=3.0,
            visual_type=VisualType.data,
            purpose=VisualPurpose.compare,
            narration="Option A is $100 and Option B is $200.",
            payload={
                "template": "stacked_bar",
                "headline": "OPTIONS",
                "data": {
                    "total": 500,  # Sum is 300 != 500
                    "segments": [
                        {"label": "Option A", "value": 100},
                        {"label": "Option B", "value": 200},
                    ],
                },
            },
        )
        spec = normalize_motion_spec(cue, self.project, director=self.director)
        self.assertEqual(spec.rendered_template, "bar_chart")
        self.assertEqual(spec.visual_grammar, VisualGrammar.bar)

    def test_long_form_12_cues_shared_diversity_memory(self) -> None:
        """Requirement 12: Simulate 12 DATA cues in one project using single shared Director."""
        cues = [
            TimelineCue(id="C01", order=1, start=0.0, end=3.0, narration="Repair cost was $6,000."),
            TimelineCue(id="C02", order=2, start=3.0, end=6.0, narration="40% chose Premium, 35% Standard, and 25% Basic."),
            TimelineCue(id="C03", order=3, start=6.0, end=9.0, narration="Prices rose from $100 in 2021 to $180 in 2025."),
            TimelineCue(id="C04", order=4, start=9.0, end=12.0, narration="Plan A costs $50, Plan B $80, Plan C $120."),
            TimelineCue(id="C05", order=5, start=12.0, end=15.0, narration="Policy limit is $25,000 while damage is $40,000."),
            TimelineCue(id="C06", order=6, start=15.0, end=18.0, narration="Top 3 causes: Speeding 45%, Distraction 30%, Weather 25%."),
            TimelineCue(id="C07", order=7, start=18.0, end=21.0, narration="85% of the inspection is completed."),
            TimelineCue(id="C08", order=8, start=21.0, end=24.0, narration="Step 1: File claim. Step 2: Assessment. Step 3: Payout."),
            TimelineCue(id="C09", order=9, start=24.0, end=27.0, narration="Started at $200, fee of $50 added, $30 discount applied, ending at $220."),
            TimelineCue(id="C10", order=10, start=27.0, end=30.0, narration="Premium is $150 compared to Deductible of $500."),
            TimelineCue(id="C11", order=11, start=30.0, end=33.0, narration="Total budget $10,000 consists of $6,000 parts and $4,000 labor."),
            TimelineCue(id="C12", order=12, start=33.0, end=36.0, narration="Remember to review coverage annually."),
        ]

        shared_director = DataVisualizationDirector()
        # Use fallback path for deterministic fast test
        def _mock_llm_fail(prompt: str) -> str:
            raise ValueError("Deterministic test fallback mode")

        planned_cues = plan_visuals(self.project, cues, response_fn=_mock_llm_fail, director=shared_director)
        self.assertEqual(len(planned_cues), 12)

        rendered_templates = []
        for p_cue in planned_cues:
            if p_cue.visual_type == VisualType.data:
                spec = normalize_motion_spec(p_cue, self.project, director=shared_director)
                rendered_templates.append(spec.rendered_template)

        # Ensure semantic diversity across the 12 cues
        unique_templates = set(rendered_templates)
        self.assertGreaterEqual(len(unique_templates), 7, f"Expected >= 7 distinct templates, got {unique_templates}")


class TestG17ProductionE2ERender(unittest.TestCase):
    """Real Remotion video render tests executing the complete production pipeline."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g17_prod_render_")
        self.project = _create_minimal_project()
        self.director = DataVisualizationDirector()

    def tearDown(self) -> None:
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_e2e_production_pie_donut_render(self) -> None:
        """Case A: Production narration -> fallback_visual -> normalize_motion_spec -> render_scene_motion -> MP4."""
        cue = TimelineCue(
            id="PROD_PIE",
            order=1,
            start=0.0,
            end=3.0,
            narration="40% chose Premium, 35% Standard, and 25% Basic.",
        )
        vis_cue = fallback_visual(self.project, cue, director=self.director)
        spec = normalize_motion_spec(vis_cue, self.project, director=self.director)

        self.assertIn(spec.rendered_template, ("pie", "donut"))
        asset = render_scene_motion(spec, Path(self.temp_dir))

        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

        # Validate clip properties
        duration = validate_rendered_motion_clip(
            asset.output_file,
            expected_duration_frames=spec.duration_frames,
            expected_width=spec.width,
            expected_height=spec.height,
            expected_fps=spec.fps,
        )
        self.assertAlmostEqual(duration, spec.duration_frames / float(spec.fps), delta=0.2)

    def test_e2e_production_gauge_render(self) -> None:
        """Case D: Production narration -> fallback_visual -> normalize_motion_spec -> render_scene_motion -> MP4."""
        cue = TimelineCue(
            id="PROD_GAUGE",
            order=1,
            start=0.0,
            end=3.0,
            narration="75% of the process is complete.",
        )
        vis_cue = fallback_visual(self.project, cue, director=self.director)
        spec = normalize_motion_spec(vis_cue, self.project, director=self.director)

        self.assertEqual(spec.rendered_template, "gauge")
        asset = render_scene_motion(spec, Path(self.temp_dir))

        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

        duration = validate_rendered_motion_clip(
            asset.output_file,
            expected_duration_frames=spec.duration_frames,
            expected_width=spec.width,
            expected_height=spec.height,
            expected_fps=spec.fps,
        )
        self.assertAlmostEqual(duration, spec.duration_frames / float(spec.fps), delta=0.2)

    def test_e2e_production_waterfall_render(self) -> None:
        """Case E: Production narration -> fallback_visual -> normalize_motion_spec -> render_scene_motion -> MP4."""
        cue = TimelineCue(
            id="PROD_WATERFALL",
            order=1,
            start=0.0,
            end=3.0,
            narration="Started at $100, added a $30 fee, received a $20 discount, and finished at $110.",
        )
        vis_cue = fallback_visual(self.project, cue, director=self.director)
        spec = normalize_motion_spec(vis_cue, self.project, director=self.director)

        self.assertEqual(spec.rendered_template, "waterfall")
        asset = render_scene_motion(spec, Path(self.temp_dir))

        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 10000)

        duration = validate_rendered_motion_clip(
            asset.output_file,
            expected_duration_frames=spec.duration_frames,
            expected_width=spec.width,
            expected_height=spec.height,
            expected_fps=spec.fps,
        )
        self.assertAlmostEqual(duration, spec.duration_frames / float(spec.fps), delta=0.2)


if __name__ == "__main__":
    unittest.main()
