from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from app.models.motion import MotionGroupSpec, MotionSceneSpec
from app.models.project import (
    NarrationMode,
    ProjectSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_group_motion, render_scene_motion, validate_rendered_motion_clip
from app.services.visual_planner import _apply_diversity


class TestG19CrossDomainUAT(unittest.TestCase):
    """60–90 second SaaS/API Infrastructure production UAT verifying end-to-end G19 pipeline."""

    def setUp(self) -> None:
        self.uat_dir = tempfile.mkdtemp(prefix="g19_saas_uat_")
        self.project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "API Infrastructure Masterclass", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "api_infrastructure", "script": "SaaS and API Infrastructure breakdown"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

    def tearDown(self) -> None:
        if hasattr(self, "uat_dir") and Path(self.uat_dir).exists():
            shutil.rmtree(self.uat_dir, ignore_errors=True)

    def test_saas_infrastructure_uat_run(self) -> None:
        """Run full 60-90s SaaS infrastructure pipeline through VisualRendererDirector and Remotion."""
        # 8 Cues representing ~65 seconds of SaaS infrastructure narration
        cues = [
            TimelineCue(id="C01", order=1, start=0.0, end=7.5, narration="The default API rate limit is set to ten thousand requests per second."),
            TimelineCue(id="C02", order=2, start=7.5, end=15.0, narration="When traffic reaches fifteen thousand requests, overflow requests throttle to protect upstream systems."),
            TimelineCue(id="C03", order=3, start=15.0, end=23.5, narration="Telemetry maintains four golden signals: ninety-nine point ninety-nine percent uptime, forty-two millisecond latency, one point two million daily requests, and zero point zero four percent error rate."),
            TimelineCue(id="C04", order=4, start=23.5, end=31.0, narration="Self-hosted infrastructure offers maximum configuration control."),
            TimelineCue(id="C05", order=5, start=31.0, end=38.5, narration="In contrast, managed serverless minimizes operational overhead."),
            TimelineCue(id="C06", order=6, start=38.5, end=47.0, narration="Incoming web traffic flows through edge proxies into redis cache before querying the database."),
            TimelineCue(id="C07", order=7, start=47.0, end=55.5, narration="Between twenty twenty-two beta launch and twenty twenty-six global expansion, cluster footprint expanded worldwide."),
            TimelineCue(id="C08", order=8, start=55.5, end=64.0, narration="Today the enterprise platform delivers twelve million dollars in annual recurring revenue."),
        ]

        decisions = [
            VisualCue(
                id="C01", order=1, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=0.0, end=7.5,
                visual_group_id="vg_rate_limit", narration=cues[0].narration,
                payload={"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000 req/s", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000 req/s"}},
            ),
            VisualCue(
                id="C02", order=2, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=7.5, end=15.0,
                visual_group_id="vg_rate_limit", narration=cues[1].narration,
                payload={"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000 req/s", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000 req/s"}},
            ),
            VisualCue(
                id="C03", order=3, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=15.0, end=23.5,
                narration=cues[2].narration,
                payload={"template": "data_grid", "headline": "SYSTEM TELEMETRY", "data": {"items": [
                    {"label": "UPTIME", "value": "99.99%", "highlight": True},
                    {"label": "LATENCY", "value": "42ms"},
                    {"label": "DAILY REQUESTS", "value": "1.2M"},
                    {"label": "ERROR RATE", "value": "0.04%"},
                ]}},
            ),
            VisualCue(
                id="C04", order=4, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=23.5, end=31.0,
                visual_group_id="vg_infra_compare", narration=cues[3].narration,
                payload={"template": "comparison", "headline": "HOSTING ARCHITECTURE", "data": {"items": [
                    {"label": "SELF-HOSTED", "value": "HIGH CONTROL", "highlight": True},
                    {"label": "SERVERLESS", "value": "ZERO OPS", "highlight": False},
                ]}},
            ),
            VisualCue(
                id="C05", order=5, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=31.0, end=38.5,
                visual_group_id="vg_infra_compare", narration=cues[4].narration,
                payload={"template": "comparison", "headline": "HOSTING ARCHITECTURE", "data": {"items": [
                    {"label": "SELF-HOSTED", "value": "HIGH CONTROL", "highlight": False},
                    {"label": "SERVERLESS", "value": "ZERO OPS", "highlight": True},
                ]}},
            ),
            VisualCue(
                id="C06", order=6, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=38.5, end=47.0,
                narration=cues[5].narration,
                payload={"template": "diagram", "headline": "DATAFLOW PIPELINE", "data": {"nodes": [
                    {"id": "n1", "label": "EDGE PROXY"},
                    {"id": "n2", "label": "API SERVICE"},
                    {"id": "n3", "label": "REDIS CACHE"},
                    {"id": "n4", "label": "POSTGRES DB"},
                ]}},
            ),
            VisualCue(
                id="C07", order=7, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=47.0, end=55.5,
                visual_group_id="vg_infra_timeline", narration=cues[6].narration,
                payload={"template": "timeline", "headline": "GLOBAL EXPANSION", "data": {"milestones": [
                    {"time": "2022", "title": "Beta Launch", "highlight": False},
                    {"time": "2026", "title": "Global Scaling", "highlight": True},
                ]}},
            ),
            VisualCue(
                id="C08", order=8, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=55.5, end=64.0,
                narration=cues[7].narration,
                payload={"template": "number", "headline": "ANNUAL RECURRING REVENUE", "data": {"value": "$12,000,000", "numeric_value": 12000000.0, "label": "FY2026 ARR"}},
            ),
        ]

        task_dir = Path(self.uat_dir)
        adapted = _apply_diversity(self.project, cues, decisions)
        norm_specs = [normalize_motion_spec(c, project=self.project, timing_source="user_srt") for c in adapted]
        grouped_items = form_motion_groups(norm_specs)

        rendered_count = 0
        total_duration = 0.0

        for item in grouped_items:
            if isinstance(item, MotionGroupSpec):
                group_assets = render_group_motion(item, task_dir)
                self.assertEqual(len(group_assets), len(item.scenes))
                clip_path = task_dir / "motion" / "groups" / item.group_id / "master.mp4"
                self.assertTrue(clip_path.exists())
                dur = validate_rendered_motion_clip(
                    clip_path,
                    expected_duration_frames=item.duration_frames,
                    expected_width=item.width,
                    expected_height=item.height,
                    expected_fps=item.fps,
                )
                total_duration += dur
                rendered_count += len(item.scenes)
            elif isinstance(item, MotionSceneSpec):
                scene_asset = render_scene_motion(item, task_dir)
                clip_path = Path(scene_asset.output_file)
                self.assertTrue(clip_path.exists())
                dur = validate_rendered_motion_clip(
                    clip_path,
                    expected_duration_frames=item.duration_frames,
                    expected_width=item.width,
                    expected_height=item.height,
                    expected_fps=item.fps,
                )
                total_duration += dur
                rendered_count += 1

        self.assertEqual(rendered_count, 8)
        self.assertAlmostEqual(total_duration, 64.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
