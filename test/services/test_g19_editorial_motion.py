from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

from app.models.project import ProjectSpec, VisualCue, VisualPurpose, VisualType
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_scene_motion
from test.services.test_g18_real_remotion_render import _extract_frame_at_timestamp


class TestG19EditorialMotion(unittest.TestCase):
    """Real Remotion rendering tests for G19 editorial templates and motion primitives."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="g19_editorial_test_")
        self.project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "Editorial Motion Test", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "editorial", "script": "Editorial motion tests"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir") and Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_metric_punch_scene_render(self) -> None:
        """Section 49: Real Remotion render of MetricPunchTemplate."""
        cue = VisualCue(
            id="C_PUNCH_01",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="Annual revenue scaled to twelve million dollars.",
            payload={
                "template": "number",
                "headline": "ANNUAL REVENUE",
                "data": {
                    "value": "$12,000,000",
                    "numeric_value": 12000000.0,
                    "label": "ARR 2026",
                },
            },
        )
        scene_spec = normalize_motion_spec(cue, project=self.project, timing_source="user_srt")
        task_dir = Path(self.temp_dir)
        asset = render_scene_motion(scene_spec, task_dir)

        mp4_path = Path(asset.output_file)
        self.assertTrue(mp4_path.exists())
        self.assertGreater(mp4_path.stat().st_size, 10000)

        # Extract frames at early entrance (0.5s) and final hold (2.5s)
        f_early = _extract_frame_at_timestamp(str(mp4_path), 0.5, str(task_dir / "punch_early.png"))
        f_late = _extract_frame_at_timestamp(str(mp4_path), 2.5, str(task_dir / "punch_late.png"))
        diff = np.sum(np.abs(f_early.astype(int) - f_late.astype(int)))
        self.assertGreater(diff, 50000)

    def test_diagram_flow_scene_render(self) -> None:
        """Section 23 & 49: Real Remotion render of DiagramTemplate."""
        cue = VisualCue(
            id="C_DIAG_01",
            order=2,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=4.0,
            narration="Incoming requests hit the API gateway, check redis cache, and query postgres database.",
            payload={
                "template": "diagram",
                "headline": "REQUEST PIPELINE",
                "data": {
                    "nodes": [
                        {"id": "n1", "label": "GATEWAY", "sublabel": "Reverse Proxy"},
                        {"id": "n2", "label": "CACHE", "sublabel": "Redis Tier"},
                        {"id": "n3", "label": "DATABASE", "sublabel": "PostgreSQL"},
                    ]
                },
            },
        )
        scene_spec = normalize_motion_spec(cue, project=self.project, timing_source="user_srt")
        task_dir = Path(self.temp_dir)
        asset = render_scene_motion(scene_spec, task_dir)

        mp4_path = Path(asset.output_file)
        self.assertTrue(mp4_path.exists())
        self.assertGreater(mp4_path.stat().st_size, 10000)

    def test_data_grid_scene_render(self) -> None:
        """Section 24 & 49: Real Remotion render of DataGridTemplate."""
        cue = VisualCue(
            id="C_GRID_01",
            order=3,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.5,
            narration="Infrastructure telemetry shows four core production metrics.",
            payload={
                "template": "data_grid",
                "headline": "INFRASTRUCTURE TELEMETRY",
                "data": {
                    "items": [
                        {"label": "UPTIME", "value": "99.99%", "numeric_value": 99.99, "highlight": True},
                        {"label": "P99 LATENCY", "value": "42ms", "numeric_value": 42.0},
                        {"label": "DAILY REQUESTS", "value": "1.2M", "numeric_value": 1.2, "unit": "M"},
                        {"label": "ERROR RATE", "value": "0.04%", "numeric_value": 0.04},
                    ]
                },
            },
        )
        scene_spec = normalize_motion_spec(cue, project=self.project, timing_source="user_srt")
        task_dir = Path(self.temp_dir)
        asset = render_scene_motion(scene_spec, task_dir)

        mp4_path = Path(asset.output_file)
        self.assertTrue(mp4_path.exists())
        self.assertGreater(mp4_path.stat().st_size, 10000)

    def test_hybrid_broll_scene_render(self) -> None:
        """Section 27 & 54: Real Remotion render of HybridBrollTemplate."""
        cue = VisualCue(
            id="C_HYBRID_01",
            order=4,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=3.0,
            narration="High throughput server operations maintain sub-second response times.",
            payload={
                "template": "hybrid_broll",
                "headline": "SERVER OPERATIONS",
                "data": {
                    "value": "1.2M req/sec",
                    "label": "Peak Load",
                    "broll_confidence": 0.88,
                    "broll_path": "",
                },
            },
        )
        scene_spec = normalize_motion_spec(cue, project=self.project, timing_source="user_srt")
        task_dir = Path(self.temp_dir)
        asset = render_scene_motion(scene_spec, task_dir)

        mp4_path = Path(asset.output_file)
        self.assertTrue(mp4_path.exists())
        self.assertGreater(mp4_path.stat().st_size, 10000)


if __name__ == "__main__":
    unittest.main()
