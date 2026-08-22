from __future__ import annotations

from pathlib import Path
import unittest

from app.models.motion import MotionGroupSpec
from app.models.project import ProjectSpec, VisualCue, VisualPurpose, VisualType
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_group_motion, render_scene_motion, validate_rendered_motion_clip


class TestG19DemoGallery(unittest.TestCase):
    """Renders all 12 G19 demo gallery clips into storage/demo/g19/ and validates them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.demo_dir = Path("storage/demo/g19")
        cls.demo_dir.mkdir(parents=True, exist_ok=True)

        cls.project_16_9 = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "G19 Gallery 16:9", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "technology", "script": "G19 Gallery"},
            "narration": {"mode": "tts"},
            "production": {"video_source": "pexels"},
        })

    def test_01_metric_punch(self) -> None:
        cue = VisualCue(
            id="g19_demo_01", order=1, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=3.0, narration="Annual recurring revenue reached twelve million dollars.",
            payload={"template": "number", "headline": "ANNUAL RECURRING REVENUE", "data": {"value": "$12,000,000", "numeric_value": 12000000.0, "label": "FY2026 ARR"}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "01_metric_punch_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "01_metric_punch.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=90, expected_width=1920, expected_height=1080)

    def test_02_metric_context(self) -> None:
        cue = VisualCue(
            id="g19_demo_02", order=2, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=3.0, narration="Net revenue retention held steady at one hundred twenty-four percent.",
            payload={"template": "number", "headline": "NET REVENUE RETENTION", "data": {"value": "124%", "numeric_value": 124.0, "eyebrow": "COHORT RETENTION", "subtext": "Exceeding enterprise benchmark of 115%"}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "02_metric_context_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "02_metric_context.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=90, expected_width=1920, expected_height=1080)

    def test_03_breakdown_story(self) -> None:
        cues = [
            VisualCue(
                id="g19_demo_03a", order=3, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=0.0, end=3.0, visual_group_id="vg_cost_breakdown_demo", narration="Monthly infrastructure spend totals ten thousand dollars.",
                payload={"template": "breakdown", "headline": "INFRASTRUCTURE BILL", "data": {"total": {"label": "TOTAL CLOUD", "value": "$10,000", "numeric_value": 10000}, "parts": [{"label": "COMPUTE", "value": "$6,000", "numeric_value": 6000}, {"label": "STORAGE & NETWORK", "value": "$4,000", "numeric_value": 4000}], "value": "$10,000", "numeric_value": 10000}},
            ),
            VisualCue(
                id="g19_demo_03b", order=4, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=3.0, end=6.0, visual_group_id="vg_cost_breakdown_demo", narration="Compute accounts for six thousand dollars.",
                payload={"template": "breakdown", "headline": "INFRASTRUCTURE BILL", "data": {"total": {"label": "TOTAL CLOUD", "value": "$10,000", "numeric_value": 10000}, "parts": [{"label": "COMPUTE", "value": "$6,000", "numeric_value": 6000}, {"label": "STORAGE & NETWORK", "value": "$4,000", "numeric_value": 4000}], "value": "$6,000", "numeric_value": 6000}},
            ),
        ]
        s1 = normalize_motion_spec(cues[0], project=self.project_16_9, timing_source="user_srt")
        s2 = normalize_motion_spec(cues[1], project=self.project_16_9, timing_source="user_srt")
        group = form_motion_groups([s1, s2])[0]
        out_dir = self.demo_dir / "03_breakdown_task"
        render_group_motion(group, out_dir)
        clip = out_dir / "motion" / "groups" / group.group_id / "master.mp4"
        dest = self.demo_dir / "03_breakdown_story.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=180, expected_width=1920, expected_height=1080)

    def test_04_comparison_story(self) -> None:
        cues = [
            VisualCue(
                id="g19_demo_04a", order=5, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=0.0, end=3.0, visual_group_id="vg_compare_demo", narration="Self-hosted infrastructure offers full control.",
                payload={"template": "comparison", "headline": "HOSTING ARCHITECTURE", "data": {"items": [{"label": "SELF-HOSTED", "value": "HIGH CONTROL", "highlight": True}, {"label": "SERVERLESS", "value": "ZERO OPS", "highlight": False}]}},
            ),
            VisualCue(
                id="g19_demo_04b", order=6, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=3.0, end=6.0, visual_group_id="vg_compare_demo", narration="Serverless minimizes ongoing operational maintenance.",
                payload={"template": "comparison", "headline": "HOSTING ARCHITECTURE", "data": {"items": [{"label": "SELF-HOSTED", "value": "HIGH CONTROL", "highlight": False}, {"label": "SERVERLESS", "value": "ZERO OPS", "highlight": True}]}},
            ),
        ]
        s1 = normalize_motion_spec(cues[0], project=self.project_16_9, timing_source="user_srt")
        s2 = normalize_motion_spec(cues[1], project=self.project_16_9, timing_source="user_srt")
        group = form_motion_groups([s1, s2])[0]
        out_dir = self.demo_dir / "04_comparison_task"
        render_group_motion(group, out_dir)
        clip = out_dir / "motion" / "groups" / group.group_id / "master.mp4"
        dest = self.demo_dir / "04_comparison_story.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=180, expected_width=1920, expected_height=1080)

    def test_05_donut_narrative(self) -> None:
        cue = VisualCue(
            id="g19_demo_05", order=7, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=3.5, narration="API traffic divides across web, mobile, and third-party integrations.",
            payload={"template": "donut", "headline": "TRAFFIC DISTRIBUTION", "data": {"items": [{"label": "Web App", "value": 55.0}, {"label": "Mobile SDK", "value": 30.0}, {"label": "Partners", "value": 15.0}]}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "05_donut_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "05_donut_narrative.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=105, expected_width=1920, expected_height=1080)

    def test_06_bar_focus_sequence(self) -> None:
        cue = VisualCue(
            id="g19_demo_06", order=8, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=3.5, narration="Quarterly performance climbed consistently over four quarters.",
            payload={"template": "bar_chart", "headline": "QUARTERLY GROWTH", "data": {"items": [{"label": "Q1", "value": 2.4}, {"label": "Q2", "value": 3.8}, {"label": "Q3", "value": 5.1}, {"label": "Q4", "value": 7.6}]}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "06_bar_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "06_bar_focus_sequence.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=105, expected_width=1920, expected_height=1080)

    def test_07_timeline_story(self) -> None:
        cues = [
            VisualCue(
                id="g19_demo_07a", order=9, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=0.0, end=3.0, visual_group_id="vg_timeline_demo", narration="In 2022, beta launch verified product market fit.",
                payload={"template": "timeline", "headline": "SCALING MILESTONES", "data": {"milestones": [{"time": "2022", "title": "Beta Launch"}, {"time": "2024", "title": "Global Scaling"}]}},
            ),
            VisualCue(
                id="g19_demo_07b", order=10, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=3.0, end=6.0, visual_group_id="vg_timeline_demo", narration="By 2024, global infrastructure served millions of developers.",
                payload={"template": "timeline", "headline": "SCALING MILESTONES", "data": {"milestones": [{"time": "2022", "title": "Beta Launch"}, {"time": "2024", "title": "Global Scaling"}]}},
            ),
        ]
        s1 = normalize_motion_spec(cues[0], project=self.project_16_9, timing_source="user_srt")
        s2 = normalize_motion_spec(cues[1], project=self.project_16_9, timing_source="user_srt")
        group = form_motion_groups([s1, s2])[0]
        out_dir = self.demo_dir / "07_timeline_task"
        render_group_motion(group, out_dir)
        clip = out_dir / "motion" / "groups" / group.group_id / "master.mp4"
        dest = self.demo_dir / "07_timeline_story.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=180, expected_width=1920, expected_height=1080)

    def test_08_threshold_story(self) -> None:
        cues = [
            VisualCue(
                id="g19_demo_08a", order=11, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=0.0, end=3.5, visual_group_id="vg_thresh_demo", narration="If the API rate limit is ten thousand requests.",
                payload={"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000"}},
            ),
            VisualCue(
                id="g19_demo_08b", order=12, visual_type=VisualType.data, purpose=VisualPurpose.explain,
                start=3.5, end=7.0, visual_group_id="vg_thresh_demo", narration="And peak load reaches fifteen thousand requests, extra traffic throttles.",
                payload={"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000"}},
            ),
        ]
        s1 = normalize_motion_spec(cues[0], project=self.project_16_9, timing_source="user_srt")
        s2 = normalize_motion_spec(cues[1], project=self.project_16_9, timing_source="user_srt")
        group = form_motion_groups([s1, s2])[0]
        out_dir = self.demo_dir / "08_threshold_task"
        render_group_motion(group, out_dir)
        clip = out_dir / "motion" / "groups" / group.group_id / "master.mp4"
        dest = self.demo_dir / "08_threshold_story.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=210, expected_width=1920, expected_height=1080)

    def test_09_diagram_reveal(self) -> None:
        cue = VisualCue(
            id="g19_demo_09", order=13, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=4.0, narration="Requests flow from edge routers through the API cluster into cache and storage.",
            payload={"template": "diagram", "headline": "SYSTEM DATAFLOW", "data": {"nodes": [{"id": "n1", "label": "EDGE"}, {"id": "n2", "label": "API"}, {"id": "n3", "label": "CACHE"}, {"id": "n4", "label": "DATABASE"}]}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "09_diagram_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "09_diagram_reveal.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=120, expected_width=1920, expected_height=1080)

    def test_10_data_grid(self) -> None:
        cue = VisualCue(
            id="g19_demo_10", order=14, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=3.5, narration="The platform maintains high availability across key operational indicators.",
            payload={"template": "data_grid", "headline": "PLATFORM TELEMETRY", "data": {"items": [{"label": "AVAILABILITY", "value": "99.99%"}, {"label": "P99 LATENCY", "value": "24ms"}, {"label": "CONCURRENT USERS", "value": "85,000"}, {"label": "GLOBAL REGIONS", "value": "18"}]}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "10_data_grid_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "10_data_grid.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=105, expected_width=1920, expected_height=1080)

    def test_11_hybrid_broll_metric(self) -> None:
        cue = VisualCue(
            id="g19_demo_11", order=15, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=3.0, narration="Datacenter throughput scales up to one hundred gigabits per second.",
            payload={"template": "hybrid_broll", "headline": "NETWORK THROUGHPUT", "data": {"value": "100 Gbps", "label": "Backbone Bandwidth", "broll_confidence": 0.90, "broll_path": ""}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "11_hybrid_metric_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "11_hybrid_broll_metric.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=90, expected_width=1920, expected_height=1080)

    def test_12_hybrid_broll_annotation(self) -> None:
        cue = VisualCue(
            id="g19_demo_12", order=16, visual_type=VisualType.data, purpose=VisualPurpose.explain,
            start=0.0, end=3.0, narration="Edge nodes cache requests locally to minimize server load.",
            payload={"template": "hybrid_broll", "headline": "EDGE ACCELERATION", "data": {"value": "94% Hit Rate", "label": "Edge Cache Efficiency", "broll_confidence": 0.85, "broll_path": ""}},
        )
        spec = normalize_motion_spec(cue, project=self.project_16_9, timing_source="user_srt")
        out_dir = self.demo_dir / "12_hybrid_annotation_task"
        asset = render_scene_motion(spec, out_dir)
        clip = Path(asset.output_file)
        dest = self.demo_dir / "12_hybrid_broll_annotation.mp4"
        if dest.exists():
            dest.unlink()
        clip.rename(dest)
        validate_rendered_motion_clip(dest, expected_duration_frames=90, expected_width=1920, expected_height=1080)


if __name__ == "__main__":
    unittest.main()
