import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.project import (
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
from app.services.production_workflow import run_production_workflow
from app.services.project_builder import build_project_spec_from_ui
from app.services.visual_planner import fallback_visual, plan_visuals


class TestG14FullE2ESmoke(unittest.TestCase):
    def test_e2e_planning_with_insurance_uat_narratives(self):
        """Verify full planning on real insurance narrative produces rich structured visuals."""
        script_text = (
            "Your car is parked outside during a storm, and a tree branch falls on it. "
            "The total repair cost is $6,000. "
            "You pay a $1,000 deductible, and the insurer covers the remaining $5,000. "
            "If your coverage limit is $25,000 and damages hit $40,000, you exceed policy limits."
        )
        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Insurance Claim Breakdown", aspect_ratio=VideoAspect.landscape, fps=30),
            script={
                "subject": "Comprehensive Auto Insurance Claims",
                "script": script_text,
                "search_terms": ["car insurance", "tree branch storm damage", "deductible coverage limit"],
            },
            narration=NarrationSpec(mode="tts"),
            timeline_cues=[
                TimelineCue(id="S001", order=1, start=0.0, end=4.0, narration="Your car is parked outside during a storm, and a tree branch falls on it."),
                TimelineCue(id="S002", order=2, start=4.0, end=7.5, narration="The total repair cost is $6,000."),
                TimelineCue(id="S003", order=3, start=7.5, end=11.5, narration="You pay a $1,000 deductible, and the insurer covers the remaining $5,000."),
                TimelineCue(id="S004", order=4, start=11.5, end=16.0, narration="If your coverage limit is $25,000 and damages hit $40,000, you exceed policy limits."),
            ],
        )

        planned_cues = plan_visuals(
            project=project,
            timeline_cues=project.timeline_cues,
            total_duration_seconds=16.0,
        )

        self.assertEqual(len(planned_cues), 4)

        # S001: B-roll with action-aware semantic intent
        s1 = planned_cues[0]
        self.assertEqual(s1.visual_type, VisualType.broll)
        intent = s1.payload.get("semantic_intent", {})
        self.assertIn("car", intent.get("must_show_concepts", []))
        self.assertIn("tree branch", intent.get("must_show_concepts", []))
        self.assertIn("damage", intent.get("must_show_concepts", []))
        self.assertIn("tier1", s1.payload.get("query_tiers", {}))

        # S002: Number template for $6,000 repair cost
        s2 = planned_cues[1]
        self.assertEqual(s2.visual_type, VisualType.data)
        self.assertEqual(s2.payload.get("template"), "number")
        self.assertEqual(s2.payload.get("data", {}).get("value"), "$6,000")

        # S003: Comparison template for $1,000 vs $5,000
        s3 = planned_cues[2]
        self.assertEqual(s3.visual_type, VisualType.data)
        self.assertEqual(s3.payload.get("template"), "comparison")
        items_s3 = s3.payload.get("data", {}).get("items", [])
        self.assertGreaterEqual(len(items_s3), 2)

        # S004: Threshold template for $25,000 limit vs $40,000 damage
        s4 = planned_cues[3]
        self.assertEqual(s4.visual_type, VisualType.data)
        self.assertEqual(s4.payload.get("template"), "threshold")
        self.assertEqual(s4.payload.get("data", {}).get("current_value"), 40000.0)
        self.assertEqual(s4.payload.get("data", {}).get("threshold_value"), 25000.0)

        # Verify all motion cues normalize to non-callout rendered templates
        for cue in planned_cues[1:]:
            spec = normalize_motion_spec(cue, project)
            self.assertNotEqual(spec.rendered_template, "callout", f"Scene {cue.id} unexpectedly fell back to callout")
            self.assertIsNone(spec.fallback_reason)

    def test_project_builder_with_global_search_terms(self):
        """Verify build_project_spec_from_ui integrates search_terms cleanly."""
        spec = build_project_spec_from_ui(
            title="Storm Damage Claims",
            subject="Auto Claims",
            aspect_ratio="16:9",
            script="A fallen tree branch damages your vehicle.",
            search_terms="car storm damage, tree branch falls on car, auto claim",
        )
        self.assertEqual(len(spec.script.search_terms), 3)
        self.assertIn("car storm damage", spec.script.search_terms)
        self.assertIn("tree branch falls on car", spec.script.search_terms)


if __name__ == "__main__":
    unittest.main()
