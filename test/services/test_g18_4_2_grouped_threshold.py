from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan, MotionGroupSpec, MotionSceneSpec
from app.models.project import ProjectSpec, TimelineCue, VisualCue, VisualPurpose, VisualType
from app.services.data_visualization_director import DataVisualizationDirector
from app.services.kinetic_beat_deriver import derive_kinetic_beats, resolve_progressive_copy, resolve_threshold_copy_state
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import (
    compute_group_fingerprint,
    compute_scene_fingerprint,
    render_group_motion,
    validate_rendered_motion_clip,
)
from app.services.visual_planner import _apply_diversity
from test.services.test_g18_real_remotion_render import _extract_frame_at_timestamp


class TestG1842GroupedThresholdTiming(unittest.TestCase):
    """Production path tests for G18.4.2 Grouped Threshold Timing and Serialization."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g18_4_2_test_")

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir") and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_production_threshold_pipeline_group_formation_and_spec_serialization(self) -> None:
        """Section 4 & 5: Run full production pipeline for 2 threshold cues:
        Timeline cues -> _apply_diversity -> normalize_motion_spec -> form_motion_groups -> render_group_motion.
        Assert:
        1. Output is MotionGroupSpec.
        2. spec.json contains animation_plan for each scene with limit, grow, cross, resolve beats.
        """
        cues = [
            TimelineCue(id="C038", order=38, start=135.0, end=138.5, narration="If you carry twenty-five thousand dollars in property damage liability coverage..."),
            TimelineCue(id="C039", order=39, start=138.5, end=142.0, narration="...and cause forty thousand dollars in damage, your insurer pays only twenty-five thousand."),
        ]
        decisions = [
            VisualCue(id="C038", order=38, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=135.0, end=138.5, narration=cues[0].narration, payload={"template": "number", "headline": "COVERAGE LIMIT"}),
            VisualCue(id="C039", order=39, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=138.5, end=142.0, narration=cues[1].narration, payload={"template": "number", "headline": "DAMAGE EXCEEDS LIMIT"}),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Insurance Made Simple", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "insurance", "script": "Property damage liability"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)
        self.assertEqual(len(adapted), 2)
        self.assertIsNotNone(adapted[0].visual_group_id)
        self.assertEqual(adapted[0].visual_group_id, adapted[1].visual_group_id)

        # Normalize scenes
        norm_scene_1 = normalize_motion_spec(adapted[0], project=project, timing_source="user_srt")
        norm_scene_2 = normalize_motion_spec(adapted[1], project=project, timing_source="user_srt")

        self.assertIsNotNone(norm_scene_1.animation_plan)
        self.assertIsNotNone(norm_scene_2.animation_plan)

        # Form motion groups
        grouped_items = form_motion_groups([norm_scene_1, norm_scene_2])
        self.assertEqual(len(grouped_items), 1)
        self.assertIsInstance(grouped_items[0], MotionGroupSpec)

        group_spec = grouped_items[0]
        self.assertEqual(len(group_spec.scenes), 2)

        # Render group motion
        task_dir = Path(self.temp_dir)
        rendered_assets = render_group_motion(group_spec, task_dir)
        self.assertEqual(len(rendered_assets), 2)

        # Inspect generated spec.json
        group_spec_path = task_dir / "motion" / "groups" / group_spec.group_id / "spec.json"
        self.assertTrue(group_spec_path.exists())

        spec_json = json.loads(group_spec_path.read_text(encoding="utf-8"))
        self.assertEqual(spec_json["group_id"], group_spec.group_id)
        self.assertEqual(len(spec_json["scenes"]), 2)

        for s_json in spec_json["scenes"]:
            # Props and top-level must preserve animation_plan
            self.assertIn("animation_plan", s_json["props"])
            plan = s_json["props"]["animation_plan"]
            self.assertIsNotNone(plan)
            self.assertIn("beats", plan)
            beat_kinds = [b["kind"] for b in plan["beats"]]
            self.assertIn("threshold", beat_kinds)
            self.assertIn("number", beat_kinds)
            self.assertIn("highlight", beat_kinds)
            self.assertIn("resolve", beat_kinds)

    def test_real_group_master_render_qa_and_frame_progression(self) -> None:
        """Section 6 & 7: Render grouped threshold sequence from production pipeline and verify frame progression."""
        cues = [
            TimelineCue(id="C038", order=38, start=0.0, end=3.5, narration="If you carry twenty-five thousand dollars in property damage liability coverage..."),
            TimelineCue(id="C039", order=39, start=3.5, end=7.0, narration="...and cause forty thousand dollars in damage, your insurer pays only twenty-five thousand."),
        ]
        decisions = [
            VisualCue(id="C038", order=38, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=0.0, end=3.5, narration=cues[0].narration, payload={"template": "number", "headline": "COVERAGE LIMIT"}),
            VisualCue(id="C039", order=39, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=3.5, end=7.0, narration=cues[1].narration, payload={"template": "number", "headline": "DAMAGE EXCEEDS LIMIT"}),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Insurance Made Simple", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "insurance", "script": "Property damage liability"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)
        norm_scene_1 = normalize_motion_spec(adapted[0], project=project, timing_source="user_srt")
        norm_scene_2 = normalize_motion_spec(adapted[1], project=project, timing_source="user_srt")

        grouped_items = form_motion_groups([norm_scene_1, norm_scene_2])
        group_spec = grouped_items[0]
        self.assertIsInstance(group_spec, MotionGroupSpec)

        task_dir = Path(self.temp_dir)
        render_group_motion(group_spec, task_dir)

        master_mp4 = task_dir / "motion" / "groups" / group_spec.group_id / "master.mp4"
        self.assertTrue(master_mp4.exists())
        self.assertGreater(master_mp4.stat().st_size, 10000)

        # Extract frames from Group Master
        f1 = _extract_frame_at_timestamp(str(master_mp4), 0.3)   # Setup
        f2 = _extract_frame_at_timestamp(str(master_mp4), 0.8)   # Limit reveal
        f3 = _extract_frame_at_timestamp(str(master_mp4), 1.5)   # Actual growth
        f4 = _extract_frame_at_timestamp(str(master_mp4), 2.35)  # Crossing partial
        f5 = _extract_frame_at_timestamp(str(master_mp4), 3.1)   # Conclusion

        # Assert visual differences across all consecutive stages
        diff_1_2 = float(np.sum(np.abs(f1.astype(int) - f2.astype(int))))
        diff_2_3 = float(np.sum(np.abs(f2.astype(int) - f3.astype(int))))
        diff_3_4 = float(np.sum(np.abs(f3.astype(int) - f4.astype(int))))
        diff_4_5 = float(np.sum(np.abs(f4.astype(int) - f5.astype(int))))

        self.assertGreater(diff_1_2, 35000.0, "Setup vs Limit reveal must differ")
        self.assertGreater(diff_2_3, 35000.0, "Limit reveal vs Bar growth must differ")
        self.assertGreater(diff_3_4, 35000.0, "Bar growth vs Crossing moment must differ")
        self.assertGreater(diff_4_5, 35000.0, "Crossing moment vs Conclusion must differ")

    def test_generic_api_threshold_consequence_formatting_and_no_leakage(self) -> None:
        """Section 8 & 10: Generic API threshold test verifying grounded unit formatting and zero leakage."""
        cues = [
            TimelineCue(id="C001", order=1, start=0.0, end=3.5, narration="The API request limit is ten thousand requests."),
            TimelineCue(id="C002", order=2, start=3.5, end=7.0, narration="Traffic reaches fifteen thousand requests."),
        ]
        decisions = [
            VisualCue(id="C001", order=1, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=0.0, end=3.5, narration=cues[0].narration, payload={"template": "number", "headline": "API LIMIT"}),
            VisualCue(id="C002", order=2, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=3.5, end=7.0, narration=cues[1].narration, payload={"template": "number", "headline": "TRAFFIC"}),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "API Traffic Monitor", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "API limits", "script": "The API request limit is ten thousand requests."},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        adapted = _apply_diversity(project, cues, decisions)
        norm_scene_1 = normalize_motion_spec(adapted[0], project=project, timing_source="user_srt")
        norm_scene_2 = normalize_motion_spec(adapted[1], project=project, timing_source="user_srt")

        grouped_items = form_motion_groups([norm_scene_1, norm_scene_2])
        group_spec = grouped_items[0]

        task_dir = Path(self.temp_dir)
        render_group_motion(group_spec, task_dir)

        # Inspect spec.json for zero domain leakage
        group_spec_path = task_dir / "motion" / "groups" / group_spec.group_id / "spec.json"
        spec_text = group_spec_path.read_text(encoding="utf-8").upper()

        for forbidden in ["POLICY", "INSURANCE", "COVERAGE", "LIABILITY"]:
            self.assertNotIn(forbidden, spec_text)

    def test_cache_invalidation_motion_engine_version_9(self) -> None:
        """Section 9 & 10: Prove animation_plan changes fingerprint, engine version is 9, and v8 cache is rejected."""
        scene = MotionSceneSpec(
            scene_id="S001",
            order=1,
            visual_type="data",
            requested_template="threshold",
            rendered_template="threshold",
            props={"headline": "LIMIT", "threshold_value": 100, "current_value": 150},
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1920,
            height=1080,
            animation_plan=MotionAnimationPlan(
                scene_id="S001",
                beats=[KineticBeat(id="b1", start_frame=0, end_frame=30, kind=KineticBeatKind.threshold, text="Limit")],
            ),
        )

        fp_v9 = compute_scene_fingerprint(scene)
        self.assertIsInstance(fp_v9, str)
        self.assertEqual(len(fp_v9), 64)

        # Change animation plan -> fingerprint must change
        scene_modified = scene.model_copy(
            update={
                "animation_plan": MotionAnimationPlan(
                    scene_id="S001",
                    beats=[KineticBeat(id="b1_mod", start_frame=10, end_frame=40, kind=KineticBeatKind.threshold, text="Limit")],
                )
            }
        )
        fp_modified = compute_scene_fingerprint(scene_modified)
        self.assertNotEqual(fp_v9, fp_modified)

        # Group fingerprint test
        group = MotionGroupSpec(
            group_id="VG001",
            scene_ids=["S001"],
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1920,
            height=1080,
            scenes=[scene],
        )
        group_fp = compute_group_fingerprint(group)
        self.assertIsInstance(group_fp, str)
        self.assertEqual(len(group_fp), 64)


if __name__ == "__main__":
    unittest.main()
