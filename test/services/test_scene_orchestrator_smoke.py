from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pymupdf
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.models.project import (
    DataPayload,
    DataTemplate,
    DocumentPayload,
    JobStatus,
    NarrationMode,
    ProjectManifest,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    ScriptSpec,
    TextPayload,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.evidence_sources import compute_file_sha256
from app.services.project_spec import save_project_spec
from app.services.scene_orchestrator import (
    compute_project_input_fingerprint,
    run_all_project,
)


def _create_synthetic_test_pdf(dest_path: Path, note: str = "Normal retirement age is officially established at 67.") -> Path:
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 100), "FEDERAL RETIREMENT BOARD", fontsize=20)
    p.insert_text((50, 150), f"Section 402(b): {note}", fontsize=14)
    p.insert_text((50, 180), "Early distributions before age 59.5 are subject to a 10% penalty.", fontsize=12)
    doc.save(str(dest_path))
    doc.close()
    return dest_path


class TestSceneOrchestratorSmoke(unittest.TestCase):
    """End-to-end local smoke render integration tests for G08 Scene Orchestrator.

    Executes actual Remotion and PyMuPDF rendering (local, 0 network requests) and validates
    final scene outputs and manifests.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "smoke-g08-task-001"
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_mock_local_project(self, aspect: VideoAspect = VideoAspect.landscape) -> tuple[ProjectSpec, Path]:
        width, height = aspect.to_resolution()

        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=1.0,
                narration="Full retirement age is sixty-seven.",
                payload={"template": "number", "headline": "Retirement Age", "data": {"primary_value": "67", "label": "Retirement Age"}},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.text,
                purpose=VisualPurpose.emphasis,
                start=1.0,
                end=2.0,
                narration="Early benefits begin at sixty-two.",
                payload={"headline": "Early Benefits: Age 62", "subheadline": None},
            ),
            VisualCue(
                id="S003",
                order=3,
                visual_type=VisualType.document,
                purpose=VisualPurpose.evidence,
                start=2.0,
                end=3.0,
                narration="Medicare coverage eligibility begins at sixty-five.",
                payload={
                    "search_query": "Medicare eligibility age 65",
                    "source_hint": "Medicare rules",
                    "evidence_required": False,
                    "highlight_target": "Medicare: Age 65",
                    "source_ids": ["NON_EXISTENT_SRC"],
                },
            ),
        ]

        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in sorted(cues, key=lambda x: x.order)
        ]

        dummy_audio = self.task_dir / "narration.mp3"
        dummy_audio.write_bytes(b"\x00" * 1024)

        dummy_timing = self.task_dir / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": []}), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Social Security Smoke",
                language="en-US",
                aspect_ratio=aspect,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Social Security Overview",
                script="Full retirement age is sixty-seven. Early benefits begin at sixty-two. Medicare coverage eligibility begins at sixty-five.",
                search_terms=["retirement", "medicare"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )

        project_path = self.task_dir / "project.json"
        save_project_spec(project, project_path)

        # Pre-seed planning artifacts to avoid external LLM/TTS
        save_project_spec(project, self.task_dir / "project.planned.json")
        (self.task_dir / "visual_plan.json").write_text(
            json.dumps({"schema_version": "1.0", "project_title": project.project.title, "cues": [c.model_dump(mode="json") for c in cues]}),
            encoding="utf-8",
        )
        (self.task_dir / "timeline.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "project_title": project.project.title,
                "audio_file": str(dummy_audio.resolve()),
                "timing_file": str(dummy_timing.resolve()),
                "duration": 3.0,
                "cues": [c.model_dump(mode="json") for c in timeline_cues],
            }),
            encoding="utf-8",
        )
        now = "2026-08-15T00:00:00Z"
        p_manifest = ProjectManifest(
            schema_version=project.schema_version,
            project_title=project.project.title,
            project_file=str(project_path),
            task_id=self.task_id,
            status=ProjectStatus.processing,
            fps=30,
            aspect_ratio=aspect,
            created_at=now,
            updated_at=now,
        )
        (self.task_dir / "project_manifest.json").write_text(
            json.dumps(p_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        # Set ownership fingerprint
        fp = compute_project_input_fingerprint(project)
        (self.task_dir / "orchestrator_state.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "task_id": self.task_id,
                "source_project_fingerprint": fp,
                "source_project_file": str(project_path),
                "created_at": now,
                "updated_at": now,
            }, indent=2),
            encoding="utf-8",
        )

        return project, project_path

    def test_local_smoke_run_all_and_validate_media(self) -> None:
        project, project_path = self._setup_mock_local_project(aspect=VideoAspect.landscape)

        # Run orchestrator
        from unittest.mock import patch
        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)):

            res = run_all_project(project_path, task_id=self.task_id)

        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["ready_scenes"], 3)
        self.assertEqual(res["failed_scenes"], 0)

        # Validate manifests exist and parse
        exec_manifest_path = Path(res["execution_manifest"])
        self.assertTrue(exec_manifest_path.exists())
        exec_data = json.loads(exec_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(exec_data["status"], "complete")
        self.assertEqual(len(exec_data["scenes"]), 3)

        # Inspect and validate each actual rendered MP4 file
        target_w, target_h = (1920, 1080)
        fps = 30

        for scene in exec_data["scenes"]:
            self.assertEqual(scene["status"], "ready")
            output_file = Path(scene["output_file"])
            self.assertTrue(output_file.exists(), f"Output file does not exist: {output_file}")
            self.assertGreater(output_file.stat().st_size, 0)

            clip = VideoFileClip(str(output_file))
            try:
                self.assertEqual(clip.size, [target_w, target_h])
                self.assertAlmostEqual(clip.fps, fps, delta=1.0)
                self.assertAlmostEqual(clip.duration, 1.0, delta=0.1)
                self.assertIsNone(clip.audio, f"Scene {scene['scene_id']} output must not contain audio")
            finally:
                clip.close()

        # Check S003 fallback record
        s003 = next(s for s in exec_data["scenes"] if s["scene_id"] == "S003")
        self.assertEqual(s003["planned_visual_type"], "document")
        self.assertEqual(s003["resolved_visual_type"], "text")
        self.assertEqual(s003["fallback_from"], "document")

    def test_sources_registry_integration_and_resume(self) -> None:
        """Requirements 2, 3, 22: Test original project directory sources.json with relative local PDF."""
        project_dir = Path(self.temp_dir) / "original_project"
        project_dir.mkdir(parents=True, exist_ok=True)

        task_id = "smoke-g08-sources-task-002"
        task_dir = Path(self.temp_dir) / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create relative local PDF inside project_dir
        pdf_rel_name = "evidence_report.pdf"
        pdf_path = project_dir / pdf_rel_name
        _create_synthetic_test_pdf(pdf_path, note="Normal retirement age is officially established at 67.")

        # 2. Create sources.json in project_dir referencing relative local_file
        sources_json_path = project_dir / "sources.json"
        sources_data = {
            "sources": [
                {
                    "id": "SRC_RET_PDF",
                    "kind": "pdf",
                    "local_file": pdf_rel_name,
                    "title": "Federal Retirement Board Report",
                    "publisher": "Federal Retirement Board",
                    "trust": "official",
                    "quote_hint": "Section 402(b): Normal retirement age is officially established at 67.",
                    "tags": ["retirement", "age", "67"],
                }
            ]
        }
        sources_json_path.write_text(json.dumps(sources_data, indent=2), encoding="utf-8")
        expected_registry_sha = compute_file_sha256(sources_json_path)

        # 3. Create project.json in project_dir
        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.document,
                purpose=VisualPurpose.evidence,
                start=0.0,
                end=1.0,
                narration="Normal retirement age is officially established at 67.",
                payload={
                    "search_query": "Normal retirement age 67",
                    "source_hint": "Federal Retirement Board",
                    "evidence_required": True,
                    "highlight_target": "Normal retirement age is officially established at 67.",
                    "source_ids": ["SRC_RET_PDF"],
                },
            ),
        ]
        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in cues
        ]

        dummy_audio = task_dir / "narration.mp3"
        dummy_audio.write_bytes(b"\x00" * 1024)
        dummy_timing = task_dir / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": []}), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Evidence Integration Project",
                language="en-US",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Retirement Age Evidence",
                script="Normal retirement age is officially established at 67.",
                search_terms=["retirement", "67"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )
        project_path = project_dir / "project.json"
        save_project_spec(project, project_path)

        # Pre-seed planning artifacts in task_dir
        save_project_spec(project, task_dir / "project.planned.json")
        (task_dir / "visual_plan.json").write_text(
            json.dumps({"schema_version": "1.0", "project_title": project.project.title, "cues": [c.model_dump(mode="json") for c in cues]}),
            encoding="utf-8",
        )
        (task_dir / "timeline.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "project_title": project.project.title,
                "audio_file": str(dummy_audio.resolve()),
                "timing_file": str(dummy_timing.resolve()),
                "duration": 1.0,
                "cues": [c.model_dump(mode="json") for c in timeline_cues],
            }),
            encoding="utf-8",
        )
        now = "2026-08-15T00:00:00Z"
        p_manifest = ProjectManifest(
            schema_version=project.schema_version,
            project_title=project.project.title,
            project_file=str(project_path),
            task_id=task_id,
            status=ProjectStatus.processing,
            fps=30,
            aspect_ratio=VideoAspect.landscape,
            created_at=now,
            updated_at=now,
        )
        (task_dir / "project_manifest.json").write_text(
            json.dumps(p_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        fp = compute_project_input_fingerprint(project)
        (task_dir / "orchestrator_state.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "task_id": task_id,
                "source_project_fingerprint": fp,
                "source_project_file": str(project_path),
                "created_at": now,
                "updated_at": now,
            }, indent=2),
            encoding="utf-8",
        )

        from unittest.mock import patch
        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(task_dir)):

            res1 = run_all_project(project_path, task_id=task_id)

        self.assertEqual(res1["status"], "complete")
        self.assertEqual(res1["ready_scenes"], 1)

        exec_manifest_data = json.loads((task_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(exec_manifest_data["source_registry_sha256"], expected_registry_sha)
        s001_rec = exec_manifest_data["scenes"][0]
        self.assertEqual(s001_rec["resolved_visual_type"], "document")
        self.assertEqual(s001_rec["status"], "ready")
        self.assertTrue(Path(s001_rec["output_file"]).exists())

        # 4. Modify PDF content and re-run on same task
        _create_synthetic_test_pdf(pdf_path, note="Normal retirement age is officially established at 67 (updated).")
        new_registry_sha = compute_file_sha256(sources_json_path)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(task_dir)):

            res2 = run_all_project(project_path, task_id=task_id)

        self.assertEqual(res2["status"], "complete")
        self.assertEqual(res2["ready_scenes"], 1)
        exec_manifest_data2 = json.loads((task_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        planning_stage2 = next(s for s in exec_manifest_data2["stages"] if s["name"] == "planning")
        self.assertTrue(planning_stage2["metadata"].get("reused"))
        self.assertEqual(exec_manifest_data2["scenes"][0]["status"], "ready")


if __name__ == "__main__":
    unittest.main()
