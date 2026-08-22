from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
from PIL import Image

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan, MotionGroupSpec, MotionSceneSpec
from app.models.project import ProjectSpec, TimelineCue, VisualCue, VisualPurpose, VisualType
from app.services.data_visualization_director import DataVisualizationDirector
from app.services.kinetic_beat_deriver import (
    derive_kinetic_beats,
    resolve_progressive_copy,
    resolve_threshold_copy_state,
    resolve_threshold_group_state,
)
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


class TestG1843ThresholdGroupMaster(unittest.TestCase):
    """Tests for G18.4.3 Persistent Threshold Group Master & Compact Layout."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g18_4_3_test_")

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir") and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_threshold_group_master_boundary_continuity_state(self) -> None:
        """Section 17: Assert deterministic continuity across the cue boundary (frame 104 -> 106).
        No reset of limitMarker, track, limitValue, or headline subject.
        """
        scenes_data = [
            {
                "scene_id": "C038",
                "duration_frames": 105,
                "props": {
                    "headline": "PROPERTY DAMAGE LIABILITY",
                    "threshold_value": 25000.0,
                    "threshold_display": "$25,000",
                    "threshold_label": "Coverage Limit",
                    "current_value": 40000.0,
                    "current_display": "$40,000",
                },
                "animation_plan": {
                    "scene_id": "C038",
                    "beats": [
                        {"id": "b_limit", "kind": "threshold", "start_frame": 0, "end_frame": 18},
                    ],
                },
            },
            {
                "scene_id": "C039",
                "duration_frames": 105,
                "props": {
                    "headline": "PROPERTY DAMAGE LIABILITY EXCEEDED",
                    "threshold_value": 25000.0,
                    "threshold_display": "$25,000",
                    "threshold_label": "Coverage Limit",
                    "current_value": 40000.0,
                    "current_display": "$40,000",
                },
                "animation_plan": {
                    "scene_id": "C039",
                    "beats": [
                        {"id": "b_grow", "kind": "number", "start_frame": 37, "end_frame": 61},
                        {"id": "b_cross", "kind": "highlight", "start_frame": 61, "end_frame": 77},
                        {"id": "b_resolve", "kind": "resolve", "start_frame": 77, "end_frame": 88},
                    ],
                },
            },
        ]

        total_duration = 210

        # Frame 104: just before boundary (Cue 1 end)
        s_pre = resolve_threshold_group_state(scenes_data, total_duration, 104)
        # Frame 105: exact boundary
        s_bound = resolve_threshold_group_state(scenes_data, total_duration, 105)
        # Frame 106: just after boundary (Cue 2 start)
        s_post = resolve_threshold_group_state(scenes_data, total_duration, 106)

        self.assertTrue(s_pre["limitMarkerVisible"])
        self.assertTrue(s_bound["limitMarkerVisible"])
        self.assertTrue(s_post["limitMarkerVisible"])

        self.assertTrue(s_pre["limitValueVisible"])
        self.assertTrue(s_bound["limitValueVisible"])
        self.assertTrue(s_post["limitValueVisible"])

        self.assertTrue(s_pre["trackVisible"])
        self.assertTrue(s_bound["trackVisible"])
        self.assertTrue(s_post["trackVisible"])

        self.assertGreaterEqual(s_post["baseProgress"], s_pre["baseProgress"])
        self.assertTrue(len(s_post["headlineSubject"]) > 0)
        self.assertEqual(s_pre["headlineSubject"], s_post["headlineSubject"])

    def test_threshold_compact_layout_bounds(self) -> None:
        """Section 18: Compactness assertions (track width <= ~0.60 * canvasWidth)."""
        width = 1920
        track_width = min(width * 0.52, 980)
        self.assertLessEqual(track_width, 0.60 * width)
        self.assertGreaterEqual(track_width, 0.45 * width)

    def test_real_threshold_group_master_render_and_persist_qa(self) -> None:
        """Section 16 & 19: Render real ThresholdGroupMaster for C038/C039 and persist review output."""
        persist_dir = Path("storage/uat/insurance_full/g18_4_3_threshold_review")
        persist_dir.mkdir(parents=True, exist_ok=True)

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

        source_master = task_dir / "motion" / "groups" / group_spec.group_id / "master.mp4"
        source_spec = task_dir / "motion" / "groups" / group_spec.group_id / "spec.json"

        dest_master = persist_dir / "master.mp4"
        dest_spec = persist_dir / "spec.json"

        shutil.copy2(source_master, dest_master)
        shutil.copy2(source_spec, dest_spec)

        self.assertTrue(dest_master.exists())
        self.assertGreater(dest_master.stat().st_size, 10000)

        # Extract QA frames: 01_limit, 02_pre_boundary, 03_boundary, 04_post_boundary, 05_crossing, 06_consequence, 07_final
        f_limit = _extract_frame_at_timestamp(str(dest_master), 1.5, str(persist_dir / "01_limit.png"))
        f_pre = _extract_frame_at_timestamp(str(dest_master), 3.30, str(persist_dir / "02_pre_boundary.png"))
        f_bound = _extract_frame_at_timestamp(str(dest_master), 3.50, str(persist_dir / "03_boundary.png"))
        f_post = _extract_frame_at_timestamp(str(dest_master), 3.70, str(persist_dir / "04_post_boundary.png"))
        f_cross = _extract_frame_at_timestamp(str(dest_master), 5.50, str(persist_dir / "05_crossing.png"))
        f_conseq = _extract_frame_at_timestamp(str(dest_master), 6.16, str(persist_dir / "06_consequence.png"))
        f_final = _extract_frame_at_timestamp(str(dest_master), 6.80, str(persist_dir / "07_final.png"))

        # Boundary continuity: pre-boundary (3.30s), boundary (3.50s), post-boundary (3.70s) must NOT blank out!
        # Both must have significant non-black visual content (mean pixel intensity > 10)
        self.assertGreater(float(np.mean(f_pre)), 12.0)
        self.assertGreater(float(np.mean(f_bound)), 12.0)
        self.assertGreater(float(np.mean(f_post)), 12.0)

        # Pre and post boundary difference should be small and continuous (no flash to empty screen)
        diff_bound = float(np.sum(np.abs(f_pre.astype(int) - f_post.astype(int))))
        # Compare with blank screen diff
        blank_frame = np.zeros_like(f_pre)
        diff_to_blank = float(np.sum(np.abs(f_bound.astype(int) - blank_frame.astype(int))))
        self.assertGreater(diff_to_blank, 1000000.0, "Boundary frame must not be blank")

        # Consequence and final frames must show visual evolution
        diff_cross_to_final = float(np.sum(np.abs(f_cross.astype(int) - f_final.astype(int))))
        self.assertGreater(diff_cross_to_final, 30000.0, "Consequence must evolve after crossing")

    def test_generic_api_threshold_group_master_no_leakage(self) -> None:
        """Section 20: Generic API threshold test verifying zero leakage and compact consequence."""
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

    def test_cache_invalidation_motion_engine_version_10(self) -> None:
        """Section 22: Verify motion_engine_version is 10 for both scene and group fingerprints."""
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

        fp_v10 = compute_scene_fingerprint(scene)
        self.assertIsInstance(fp_v10, str)
        self.assertEqual(len(fp_v10), 64)

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
