from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from app.models.motion import MotionGroupSpec
from app.models.project import ProjectSpec, VisualCue, VisualPurpose, VisualType
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_group_motion
from test.services.test_g18_real_remotion_render import _extract_frame_at_timestamp


class TestG19GroupMasters(unittest.TestCase):
    """Tests for persistent group masters in G19 (Breakdown, Threshold, Comparison, Timeline)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g19_groups_test_")

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir") and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_comparison_group_master_continuity(self) -> None:
        """Section 47 & 53: Render multi-cue ComparisonGroupMaster and assert boundary continuity."""
        decisions = [
            VisualCue(
                id="C010",
                order=10,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=3.5,
                visual_group_id="vg_comparison_1",
                narration="The premium is your ongoing cost to maintain insurance.",
                payload={
                    "template": "comparison",
                    "headline": "PREMIUM VS DEDUCTIBLE",
                    "data": {
                        "items": [
                            {"label": "PREMIUM", "value": "$150/mo", "highlight": True},
                            {"label": "DEDUCTIBLE", "value": "$1,000", "highlight": False},
                        ]
                    },
                },
            ),
            VisualCue(
                id="C011",
                order=11,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=3.5,
                end=7.0,
                visual_group_id="vg_comparison_1",
                narration="The deductible is your out-of-pocket share when making a claim.",
                payload={
                    "template": "comparison",
                    "headline": "PREMIUM VS DEDUCTIBLE",
                    "data": {
                        "items": [
                            {"label": "PREMIUM", "value": "$150/mo", "highlight": False},
                            {"label": "DEDUCTIBLE", "value": "$1,000", "highlight": True},
                        ]
                    },
                },
            ),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Comparison Continuity Test", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "insurance", "script": "Premium vs Deductible"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        norm_s1 = normalize_motion_spec(decisions[0], project=project, timing_source="user_srt")
        norm_s2 = normalize_motion_spec(decisions[1], project=project, timing_source="user_srt")

        grouped_items = form_motion_groups([norm_s1, norm_s2])
        group_spec = grouped_items[0]
        self.assertIsInstance(group_spec, MotionGroupSpec)

        task_dir = Path(self.temp_dir)
        render_group_motion(group_spec, task_dir)

        master_mp4 = task_dir / "motion" / "groups" / group_spec.group_id / "master.mp4"
        self.assertTrue(master_mp4.exists())
        self.assertGreater(master_mp4.stat().st_size, 10000)

        # Boundary checks: 3.30s (Cue 1 end) and 3.70s (Cue 2 start)
        f_pre = _extract_frame_at_timestamp(str(master_mp4), 3.30, str(task_dir / "comp_pre.png"))
        f_bound = _extract_frame_at_timestamp(str(master_mp4), 3.50, str(task_dir / "comp_bound.png"))
        f_post = _extract_frame_at_timestamp(str(master_mp4), 3.70, str(task_dir / "comp_post.png"))

        self.assertGreater(float(np.mean(f_pre)), 10.0)
        self.assertGreater(float(np.mean(f_bound)), 10.0)
        self.assertGreater(float(np.mean(f_post)), 10.0)

    def test_timeline_group_master_continuity(self) -> None:
        """Section 48 & 53: Render multi-cue TimelineGroupMaster and assert persistent timeline track."""
        decisions = [
            VisualCue(
                id="C020",
                order=20,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=3.5,
                visual_group_id="vg_timeline_1",
                narration="In 2020, the initial service deployed with single-node architecture.",
                payload={
                    "template": "timeline",
                    "headline": "ARCHITECTURE ROADMAP",
                    "data": {
                        "milestones": [
                            {"time": "2020", "title": "Single Node", "highlight": True},
                            {"time": "2024", "title": "Multi Region", "highlight": False},
                        ]
                    },
                },
            ),
            VisualCue(
                id="C021",
                order=21,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=3.5,
                end=7.0,
                visual_group_id="vg_timeline_1",
                narration="By 2024, cluster expansion scaled across multiple geographic regions.",
                payload={
                    "template": "timeline",
                    "headline": "ARCHITECTURE ROADMAP",
                    "data": {
                        "milestones": [
                            {"time": "2020", "title": "Single Node", "highlight": False},
                            {"time": "2024", "title": "Multi Region", "highlight": True},
                        ]
                    },
                },
            ),
        ]
        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Timeline Continuity Test", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "technology", "script": "Evolution of architecture"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

        norm_s1 = normalize_motion_spec(decisions[0], project=project, timing_source="user_srt")
        norm_s2 = normalize_motion_spec(decisions[1], project=project, timing_source="user_srt")

        grouped_items = form_motion_groups([norm_s1, norm_s2])
        group_spec = grouped_items[0]
        self.assertIsInstance(group_spec, MotionGroupSpec)

        task_dir = Path(self.temp_dir)
        render_group_motion(group_spec, task_dir)

        master_mp4 = task_dir / "motion" / "groups" / group_spec.group_id / "master.mp4"
        self.assertTrue(master_mp4.exists())
        self.assertGreater(master_mp4.stat().st_size, 10000)

        # Boundary checks
        f_pre = _extract_frame_at_timestamp(str(master_mp4), 3.30, str(task_dir / "time_pre.png"))
        f_bound = _extract_frame_at_timestamp(str(master_mp4), 3.50, str(task_dir / "time_bound.png"))
        f_post = _extract_frame_at_timestamp(str(master_mp4), 3.70, str(task_dir / "time_post.png"))

        self.assertGreater(float(np.mean(f_pre)), 10.0)
        self.assertGreater(float(np.mean(f_bound)), 10.0)
        self.assertGreater(float(np.mean(f_post)), 10.0)


if __name__ == "__main__":
    unittest.main()
