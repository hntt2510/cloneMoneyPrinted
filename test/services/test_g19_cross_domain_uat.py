from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from app.models.assembly import AssemblyConfig
from app.models.motion import MotionGroupSpec, MotionManifest, MotionSceneSpec, RendererFamily
from app.models.project import (
    JobStatus,
    NarrationMode,
    ProjectSpec,
    ProjectStatus,
    RenderJob,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.assembly_runner import assemble_final_video, validate_and_inspect_final_video
from app.services.export_runner import export_editor_package
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_group_motion, render_scene_motion, validate_rendered_motion_clip
from app.services.visual_renderer_director import VisualDiversityMemoryV2, VisualRendererDirector


def _generate_silent_wav(output_path: Path, duration_seconds: float = 64.0, sample_rate: int = 44100) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_seconds * sample_rate)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(bytearray(num_samples * 4)))
    return output_path


def _generate_srt(output_path: Path, cues: list[TimelineCue]) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, c in enumerate(cues, 1):
        def fmt_time(t: float) -> str:
            hrs = int(t // 3600)
            mins = int((t % 3600) // 60)
            secs = int(t % 60)
            millis = int(round((t - int(t)) * 1000))
            return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

        lines.append(str(i))
        lines.append(f"{fmt_time(c.start)} --> {fmt_time(c.end)}")
        lines.append(c.narration)
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


class TestG19CrossDomainUAT(unittest.TestCase):
    """60–90 second SaaS/API Infrastructure production UAT verifying end-to-end G19 pipeline and final assembly."""

    def setUp(self) -> None:
        self.uat_dir = Path("storage/uat/g19_saas")
        self.uat_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir = Path("storage/tasks/g19_saas_uat_task")
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def test_saas_infrastructure_uat_run(self) -> None:
        """Run full 64s SaaS infrastructure pipeline, assert semantic outcomes, and assemble final.mp4 with audio."""
        # 8 Cues representing 64 seconds of SaaS infrastructure narration
        timeline_cues = [
            TimelineCue(id="C01", order=1, start=0.0, end=7.5, narration="The default API rate limit is set to ten thousand requests per second."),
            TimelineCue(id="C02", order=2, start=7.5, end=15.0, narration="When traffic reaches fifteen thousand requests, overflow requests throttle to protect upstream systems."),
            TimelineCue(id="C03", order=3, start=15.0, end=23.5, narration="Telemetry maintains four golden signals: ninety-nine point ninety-nine percent uptime, forty-two millisecond latency, one point two million daily requests, and zero point zero four percent error rate."),
            TimelineCue(id="C04", order=4, start=23.5, end=31.0, narration="Self-hosted infrastructure offers maximum configuration control."),
            TimelineCue(id="C05", order=5, start=31.0, end=38.5, narration="In contrast, managed serverless minimizes operational overhead."),
            TimelineCue(id="C06", order=6, start=38.5, end=47.0, narration="Incoming web traffic flows through edge proxies into redis cache before querying the database."),
            TimelineCue(id="C07", order=7, start=47.0, end=55.5, narration="Between twenty twenty-two beta launch and twenty twenty-six global expansion, cluster footprint expanded worldwide."),
            TimelineCue(id="C08", order=8, start=55.5, end=64.0, narration="Today the enterprise platform delivers twelve million dollars in annual recurring revenue."),
        ]

        visual_cues = [
            VisualCue(
                id="C01", order=1, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=0.0, end=7.5,
                visual_group_id="vg_rate_limit", narration=timeline_cues[0].narration,
                payload={"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000 req/s", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000 req/s"}},
            ),
            VisualCue(
                id="C02", order=2, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=7.5, end=15.0,
                visual_group_id="vg_rate_limit", narration=timeline_cues[1].narration,
                payload={"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000 req/s", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000 req/s"}},
            ),
            VisualCue(
                id="C03", order=3, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=15.0, end=23.5,
                narration=timeline_cues[2].narration,
                payload={"template": "data_grid", "headline": "SYSTEM TELEMETRY", "data": {"items": [
                    {"label": "UPTIME", "value": "99.99%", "highlight": True},
                    {"label": "LATENCY", "value": "42ms"},
                    {"label": "DAILY REQUESTS", "value": "1.2M"},
                    {"label": "ERROR RATE", "value": "0.04%"},
                ], "columns": 2, "eyebrow": "PLATFORM TELEMETRY"}},
            ),
            VisualCue(
                id="C04", order=4, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=23.5, end=31.0,
                visual_group_id="vg_infra_compare", narration=timeline_cues[3].narration,
                payload={"template": "comparison", "headline": "HOSTING ARCHITECTURE", "data": {"items": [
                    {"label": "SELF-HOSTED", "value": "HIGH CONTROL", "highlight": True},
                    {"label": "SERVERLESS", "value": "ZERO OPS", "highlight": False},
                ]}},
            ),
            VisualCue(
                id="C05", order=5, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=31.0, end=38.5,
                visual_group_id="vg_infra_compare", narration=timeline_cues[4].narration,
                payload={"template": "comparison", "headline": "HOSTING ARCHITECTURE", "data": {"items": [
                    {"label": "SELF-HOSTED", "value": "HIGH CONTROL", "highlight": False},
                    {"label": "SERVERLESS", "value": "ZERO OPS", "highlight": True},
                ]}},
            ),
            VisualCue(
                id="C06", order=6, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=38.5, end=47.0,
                narration=timeline_cues[5].narration,
                payload={"template": "diagram", "headline": "DATAFLOW PIPELINE", "data": {
                    "nodes": [
                        {"id": "n1", "label": "EDGE PROXY"},
                        {"id": "n2", "label": "API SERVICE"},
                        {"id": "n3", "label": "REDIS CACHE"},
                        {"id": "n4", "label": "POSTGRES DB"},
                    ],
                    "edges": [
                        {"from_node": "n1", "to_node": "n2", "label": "routes"},
                        {"from_node": "n2", "to_node": "n3", "label": "queries"},
                        {"from_node": "n3", "to_node": "n4", "label": "syncs"},
                    ],
                    "flow_direction": "horizontal",
                }},
            ),
            VisualCue(
                id="C07", order=7, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=47.0, end=55.5,
                visual_group_id="vg_infra_timeline", narration=timeline_cues[6].narration,
                payload={"template": "timeline", "headline": "GLOBAL EXPANSION", "data": {"milestones": [
                    {"time": "2022", "title": "Beta Launch", "highlight": False},
                    {"time": "2026", "title": "Global Scaling", "highlight": True},
                ]}},
            ),
            VisualCue(
                id="C08", order=8, visual_type=VisualType.data, purpose=VisualPurpose.explain, start=55.5, end=64.0,
                narration=timeline_cues[7].narration,
                payload={"template": "number", "headline": "ANNUAL RECURRING REVENUE", "data": {"value": "$12,000,000", "numeric_value": 12000000.0, "label": "FY2026 ARR"}},
            ),
        ]

        # Generate audio and timing artifacts
        audio_file = self.task_dir / "narration.wav"
        timing_file = self.task_dir / "subtitle.srt"
        _generate_silent_wav(audio_file, duration_seconds=64.0)
        _generate_srt(timing_file, timeline_cues)

        project = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "SaaS Infrastructure Architecture", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "saas_architecture", "script": "SaaS and API Infrastructure masterclass"},
            "narration": {"mode": "file", "file": str(audio_file.resolve()), "timing_file": str(timing_file.resolve())},
            "production": {"video_source": "pexels"},
            "timeline_cues": [c.model_dump() for c in timeline_cues],
            "visual_cues": [c.model_dump() for c in visual_cues],
        })

        # Save project and timeline in task_dir
        (self.task_dir / "project.json").write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")
        (self.task_dir / "project.planned.json").write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")
        (self.task_dir / "timeline.json").write_text(json.dumps({
            "schema_version": "1.0",
            "project_title": project.project.title,
            "audio_file": str(audio_file.resolve()),
            "timing_file": str(timing_file.resolve()),
            "duration": 64.0,
            "cues": [c.model_dump() for c in timeline_cues],
        }, indent=2), encoding="utf-8")

        # 1. Normalize with shared VisualRendererDirector
        shared_director = VisualRendererDirector(VisualDiversityMemoryV2())
        scene_specs = [
            normalize_motion_spec(cue, project=project, renderer_director=shared_director, timing_source="user_srt")
            for cue in visual_cues
        ]

        # 2. Assert semantic outcomes & NO false callouts
        self.assertEqual(scene_specs[0].rendered_template, "threshold")
        self.assertEqual(scene_specs[1].rendered_template, "threshold")
        self.assertEqual(scene_specs[2].rendered_template, "data_grid")
        self.assertEqual(scene_specs[3].rendered_template, "comparison")
        self.assertEqual(scene_specs[4].rendered_template, "comparison")
        self.assertEqual(scene_specs[5].rendered_template, "diagram")
        self.assertEqual(scene_specs[6].rendered_template, "timeline")
        self.assertEqual(scene_specs[7].rendered_template, "number")

        for s in scene_specs:
            self.assertNotEqual(s.rendered_template, "callout", f"Scene {s.scene_id} falsely fell back to callout")

        # 3. Form groups and render motion
        grouped_items = form_motion_groups(scene_specs)
        rendered_assets = []

        for item in grouped_items:
            if isinstance(item, MotionGroupSpec):
                assets = render_group_motion(item, self.task_dir)
                rendered_assets.extend(assets)
            elif isinstance(item, MotionSceneSpec):
                asset = render_scene_motion(item, self.task_dir)
                rendered_assets.append(asset)

        self.assertEqual(len(rendered_assets), 8)

        # 4. Save motion manifest and project.motion.json
        render_jobs = []
        for asset in rendered_assets:
            render_jobs.append(RenderJob(
                id=f"R_{asset.scene_id}",
                scene_id=asset.scene_id,
                kind="data",
                status=JobStatus.ready,
                output=asset.output_file,
                duration=round(asset.duration_frames / 30.0, 4),
            ))

        project.render_jobs = render_jobs
        (self.task_dir / "project.motion.json").write_text(json.dumps(project.model_dump(mode="json"), indent=2), encoding="utf-8")

        motion_manifest = MotionManifest(
            project_title=project.project.title,
            task_id="g19_saas_uat_task",
            status=ProjectStatus.complete,
            assets=rendered_assets,
            failed_scenes=[],
        )
        (self.task_dir / "motion" / "motion_manifest.json").write_text(
            json.dumps(motion_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        # 5. Export editor package
        export_res = export_editor_package(project, task_id="g19_saas_uat_task")
        self.assertEqual(export_res.status, "complete")
        export_dir = Path(export_res.export_dir)
        self.assertTrue((export_dir / "edit_manifest.json").exists())

        # 6. Final Assembly
        assembly_res = assemble_final_video(export_dir)
        self.assertEqual(assembly_res.status, "complete")
        assembled_mp4 = Path(assembly_res.final_video_file)
        self.assertTrue(assembled_mp4.exists())

        # 7. Retain in storage/uat/g19_saas/final.mp4
        final_dest = self.uat_dir / "final.mp4"
        if final_dest.exists():
            final_dest.unlink()
        shutil.copy2(str(assembled_mp4), str(final_dest))

        # 8. Validate final video with FFprobe inspection
        qc = validate_and_inspect_final_video(
            final_dest,
            expected_fps=30,
            expected_resolution=[1920, 1080],
            expected_duration=64.0,
            require_audio=True,
            duration_tolerance=1.5,
        )
        self.assertTrue(qc.is_valid, f"QC inspection failed: {qc.errors}")
        self.assertAlmostEqual(qc.duration_seconds, 64.0, delta=1.5)
        self.assertTrue(qc.has_audio_stream, "Final assembled video must contain an audio stream")
        self.assertTrue(qc.has_video_stream, "Final assembled video must contain a video stream")
        self.assertGreater(final_dest.stat().st_size, 100000, "Final video size must be substantial")


if __name__ == "__main__":
    unittest.main()
