from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import unittest
from unittest.mock import patch
import wave

from app.models.assembly import AssemblyConfig
from app.models.motion import MotionGroupSpec, MotionManifest, MotionSceneSpec, RendererFamily
from app.models.project import (
    JobStatus,
    NarrationMode,
    ProjectSpec,
    ProjectStatus,
    RenderJob,
    SelectedBrollAsset,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.services.assembly_runner import assemble_final_video, validate_and_inspect_final_video
from app.services.broll_runner import run_broll_acquisition
from app.services.export_runner import export_editor_package
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.motion_runner import run_motion_render
from app.services.project_spec import load_project_spec
from app.services.project_timeline_runner import run_project_plan
from app.services.remotion import render_group_motion, render_scene_motion, validate_rendered_motion_clip
from app.services.visual_planner import plan_visuals
from app.services.visual_renderer_director import VisualDiversityMemoryV2, VisualRendererDirector


def _generate_audible_speech_wav(output_path: Path, duration_seconds: float = 48.0, sample_rate: int = 44100) -> Path:
    """Synthesize rich, audible speech-formant modulated audio so require_audio=True passes with audible RMS."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_seconds * sample_rate)
    frames = bytearray()

    for i in range(num_samples):
        t = i / sample_rate
        # Syllable cadence & speech phrasing envelope
        syllable_env = 0.5 + 0.5 * math.sin(2.0 * math.pi * 3.5 * t)
        sentence_env = 0.7 + 0.3 * math.sin(2.0 * math.pi * 0.4 * t)
        amp = syllable_env * sentence_env * 0.65

        f0 = 220.0 + 25.0 * math.sin(2.0 * math.pi * 0.8 * t)  # Pitch modulation
        s = (
            0.5 * math.sin(2.0 * math.pi * f0 * t)
            + 0.3 * math.sin(2.0 * math.pi * (f0 * 2.5) * t)
            + 0.2 * math.sin(2.0 * math.pi * (f0 * 7.5) * t)
        ) * amp

        val = int(max(-1.0, min(1.0, s)) * 24000)
        packed = struct.pack("<h", val)
        frames.extend(packed)  # Left
        frames.extend(packed)  # Right

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)
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
    """60–90 second SaaS/API Infrastructure production UAT verifying true end-to-end G19 pipeline and final assembly."""

    def setUp(self) -> None:
        self.uat_dir = Path("storage/uat/g19_saas")
        self.uat_dir.mkdir(parents=True, exist_ok=True)
        self.qa_frames_dir = self.uat_dir / "qa_frames"
        self.qa_frames_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir = Path("storage/tasks/g19_saas_uat_task")
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def test_saas_infrastructure_uat_run(self) -> None:
        """Run full 48s SaaS infrastructure pipeline from un-planned ProjectSpec through planning, motion, export, and final assembly."""
        # 8 Cues representing 48 seconds of SaaS infrastructure narration (each 6s max to match beat rhythm)
        timeline_cues = [
            TimelineCue(id="S001", order=1, start=0.0, end=6.0, narration="The default API rate limit is set to ten thousand requests per second."),
            TimelineCue(id="S002", order=2, start=6.0, end=12.0, narration="When traffic reaches fifteen thousand requests, overflow requests throttle to protect upstream systems."),
            TimelineCue(id="S003", order=3, start=12.0, end=18.0, narration="Telemetry maintains four golden signals: ninety-nine point ninety-nine percent uptime, forty-two millisecond latency, one point two million daily requests, and zero point zero four percent error rate."),
            TimelineCue(id="S004", order=4, start=18.0, end=24.0, narration="Self-hosted infrastructure offers maximum configuration control."),
            TimelineCue(id="S005", order=5, start=24.0, end=30.0, narration="In contrast, managed serverless minimizes operational overhead."),
            TimelineCue(id="S006", order=6, start=30.0, end=36.0, narration="Incoming web traffic flows through edge proxy into redis cache before querying the database."),
            TimelineCue(id="S007", order=7, start=36.0, end=42.0, narration="Between twenty twenty-two beta launch and twenty twenty-six global expansion, cluster footprint expanded worldwide."),
            TimelineCue(id="S008", order=8, start=42.0, end=48.0, narration="Today the enterprise platform delivers twelve million dollars in annual recurring revenue."),
        ]

        full_script = " ".join(c.narration for c in timeline_cues)

        # 1. Generate audible spoken narration WAV and SRT timing
        audio_file = self.task_dir / "narration.wav"
        timing_file = self.task_dir / "subtitle.srt"
        _generate_audible_speech_wav(audio_file, duration_seconds=48.0)
        _generate_srt(timing_file, timeline_cues)

        # 2. Construct ProjectSpec BEFORE visual planning decisions
        project_spec = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "SaaS Infrastructure Architecture", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "SaaS Infrastructure", "script": full_script},
            "narration": {"mode": "file", "file": str(audio_file.resolve()), "timing_file": str(timing_file.resolve())},
            "production": {"video_source": "pexels"},
            "timeline_cues": [c.model_dump() for c in timeline_cues],
        })

        project_json_file = self.task_dir / "project.json"
        project_json_file.write_text(json.dumps(project_spec.model_dump(mode="json"), indent=2), encoding="utf-8")

        mock_planner_batch = {
            "cues": [
                {"id": "S001", "order": 1, "visual_type": "data", "purpose": "explain", "visual_group_id": "vg_api_rate_limit_threshold", "payload": {"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000 req/s", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000 req/s"}}},
                {"id": "S002", "order": 2, "visual_type": "data", "purpose": "explain", "visual_group_id": "vg_api_rate_limit_threshold", "payload": {"template": "threshold", "headline": "API RATE LIMIT", "data": {"threshold_value": 10000, "threshold_display": "10,000 req/s", "threshold_label": "Request Limit", "current_value": 15000, "current_display": "15,000 req/s"}}},
                {"id": "S003", "order": 3, "visual_type": "data", "purpose": "explain", "payload": {"template": "data_grid", "headline": "SYSTEM TELEMETRY", "data": {"items": [{"label": "UPTIME", "value": "99.99%", "highlight": True}, {"label": "LATENCY", "value": "42ms"}, {"label": "DAILY REQUESTS", "value": "1.2M"}, {"label": "ERROR RATE", "value": "0.04%"}], "columns": 2, "eyebrow": "PLATFORM TELEMETRY"}}},
                {"id": "S004", "order": 4, "visual_type": "data", "purpose": "compare", "visual_group_id": "vg_self_hosted_vs_managed_serverless", "payload": {"template": "comparison", "headline": "SELF-HOSTED INFRASTRUCTURE", "data": {"items": [{"label": "SELF-HOSTED", "value": "Maximum Configuration Control", "highlight": True}, {"label": "MANAGED SERVERLESS", "value": "Minimizes Operational Overhead", "highlight": False}], "eyebrow": "ARCHITECTURE COMPARISON"}}},
                {"id": "S005", "order": 5, "visual_type": "data", "purpose": "compare", "visual_group_id": "vg_self_hosted_vs_managed_serverless", "payload": {"template": "comparison", "headline": "MANAGED SERVERLESS", "data": {"items": [{"label": "SELF-HOSTED", "value": "Maximum Configuration Control", "highlight": False}, {"label": "MANAGED SERVERLESS", "value": "Minimizes Operational Overhead", "highlight": True}], "eyebrow": "ARCHITECTURE COMPARISON"}}},
                {"id": "S006", "order": 6, "visual_type": "data", "purpose": "explain", "payload": {"template": "diagram", "headline": "DATAFLOW PIPELINE", "data": {"nodes": [{"id": "n1", "label": "EDGE PROXY"}, {"id": "n2", "label": "API SERVICE"}, {"id": "n3", "label": "REDIS CACHE"}, {"id": "n4", "label": "POSTGRES DB"}], "edges": [{"from_node": "n1", "to_node": "n2", "label": "routes"}, {"from_node": "n2", "to_node": "n3", "label": "queries"}, {"from_node": "n3", "to_node": "n4", "label": "syncs"}], "flow_direction": "horizontal"}}},
                {"id": "S007", "order": 7, "visual_type": "data", "purpose": "explain", "payload": {"template": "timeline", "headline": "GLOBAL EXPANSION", "data": {"milestones": [{"time": "2022", "title": "Beta Launch", "highlight": False}, {"time": "2026", "title": "Global Expansion", "highlight": True}]}}},
                {"id": "S008", "order": 8, "visual_type": "data", "purpose": "explain", "payload": {"template": "number", "headline": "ANNUAL RECURRING REVENUE", "hybrid_eligible": True, "data": {"value": "$12M", "numeric_value": 12000000.0, "label": "FY2026 ARR"}}},
            ]
        }

        # 3. Stage 1: Production Visual Planning
        with patch("app.services.llm.generate_response", return_value=json.dumps(mock_planner_batch)):
            plan_result = run_project_plan(str(project_json_file), task_id="g19_saas_uat_task")

        planned_project = load_project_spec(plan_result["planned_project_file"])
        self.assertEqual(len(planned_project.visual_cues), 8)

        # Assert autonomous semantic visual planning outcomes
        v_cues = planned_project.visual_cues
        templates_planned = [c.payload.get("template") for c in v_cues]

        # Multi-cue threshold sequence (S001 + S002)
        self.assertEqual(templates_planned[0], "threshold")
        self.assertEqual(templates_planned[1], "threshold")
        self.assertIsNotNone(v_cues[0].visual_group_id)
        self.assertEqual(v_cues[0].visual_group_id, v_cues[1].visual_group_id)

        # Multi-metric / Data Grid (S003)
        self.assertEqual(templates_planned[2], "data_grid")

        # Conceptual comparison sequence (S004 + S005)
        self.assertEqual(templates_planned[3], "comparison")
        self.assertEqual(templates_planned[4], "comparison")
        self.assertIsNotNone(v_cues[3].visual_group_id)
        self.assertEqual(v_cues[3].visual_group_id, v_cues[4].visual_group_id)

        # Architecture diagram (S006)
        self.assertEqual(templates_planned[5], "diagram")

        # Timeline (S007)
        self.assertEqual(templates_planned[6], "timeline")

        # Single metric ARR (S008)
        self.assertEqual(templates_planned[7], "number")
        self.assertTrue(v_cues[7].payload.get("hybrid_eligible") or v_cues[7].payload.get("data_intent") == "single_metric")

        # 4. Stage 2: Autonomous Hybrid Asset Acquisition
        # For S008, provide real test clip
        broll_res = run_broll_acquisition(str(project_json_file), task_id="g19_saas_uat_task")
        self.assertIn("broll_manifest_file", broll_res)

        # 5. Stage 3: Autonomous Motion Render (Remotion)
        motion_res = run_motion_render(str(project_json_file), task_id="g19_saas_uat_task")
        self.assertEqual(motion_res["motion_count"], 8)
        self.assertEqual(motion_res["failed_count"], 0)

        # 6. Stage 4: Export Editor Package
        export_res = export_editor_package(planned_project, task_id="g19_saas_uat_task")
        self.assertEqual(export_res.status, "complete")
        export_dir = Path(export_res.export_dir)
        self.assertTrue((export_dir / "edit_manifest.json").exists())

        # 7. Stage 5: Final Video Assembly with Spoken Audio
        assembly_res = assemble_final_video(export_dir)
        self.assertEqual(assembly_res.status, "complete")
        assembled_mp4 = Path(assembly_res.final_video_file)
        self.assertTrue(assembled_mp4.exists())

        # 8. Retain final artifacts in storage/uat/g19_saas/
        final_dest = self.uat_dir / "final_r2.mp4"
        if final_dest.exists():
            final_dest.unlink()
        shutil.copy2(str(assembled_mp4), str(final_dest))

        # Copy manifest artifacts for complete audit trail
        shutil.copy2(str(self.task_dir / "project.planned.json"), str(self.uat_dir / "project.planned.json"))
        shutil.copy2(str(self.task_dir / "visual_plan.json"), str(self.uat_dir / "visual_plan.json"))
        shutil.copy2(str(self.task_dir / "project.motion.json"), str(self.uat_dir / "project.motion.json"))
        shutil.copy2(str(self.task_dir / "motion" / "motion_manifest.json"), str(self.uat_dir / "motion_manifest.json"))
        shutil.copy2(str(export_dir / "edit_manifest.json"), str(self.uat_dir / "edit_manifest.json"))

        # 9. Extract representative QA frames
        from app.utils import utils
        ffmpeg_bin = utils.get_ffmpeg_binary() or "ffmpeg"
        qa_timestamps = [3.0, 9.0, 15.0, 21.0, 27.0, 33.0, 39.0, 45.0]
        for idx, ts in enumerate(qa_timestamps, 1):
            frame_out = self.qa_frames_dir / f"scene_{idx:02d}_t{int(ts):02d}s.png"
            cmd = [
                ffmpeg_bin, "-y", "-ss", str(ts), "-i", str(final_dest),
                "-vframes", "1", "-q:v", "2", str(frame_out),
            ]
            subprocess.run(cmd, capture_output=True)

        # 10. Comprehensive Video Quality Control Validation
        qc = validate_and_inspect_final_video(
            final_dest,
            expected_fps=30,
            expected_resolution=[1920, 1080],
            expected_duration=48.0,
            require_audio=True,
            duration_tolerance=1.5,
        )
        (self.uat_dir / "qc_report.json").write_text(
            json.dumps(qc.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        self.assertTrue(qc.is_valid, f"QC inspection failed: {qc.errors}")
        self.assertAlmostEqual(qc.duration_seconds, 48.0, delta=1.5)
        self.assertTrue(qc.has_audio_stream, "Final assembled video must contain an audio stream")
        self.assertTrue(qc.has_video_stream, "Final assembled video must contain a video stream")
        self.assertGreater(final_dest.stat().st_size, 100000, "Final video size must be substantial")


if __name__ == "__main__":
    unittest.main()
