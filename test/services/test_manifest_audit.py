from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
import wave
import struct
from pathlib import Path
from unittest.mock import patch

from moviepy import ColorClip

from app.models.assembly import AssemblyConfig, AssemblyStatus
from app.models.export import EditManifest, EditorPackageStatus
from app.models.project import (
    DataPayload,
    JobStatus,
    NarrationMode,
    ProjectManifest,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    ScriptSpec,
    SelectedBrollAsset,
    TextPayload,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.assembly_runner import assemble_final_video
from app.services.evidence_sources import compute_file_sha256
from app.services.export_runner import export_editor_package
from app.services.project_spec import save_project_spec
from app.services.scene_orchestrator import (
    compute_project_input_fingerprint,
    run_all_project,
)


class TestManifestAudit(unittest.TestCase):
    """G12.5 Manifest Audit Tests.

    Validates consistency, referential integrity, and absence of dangling paths
    across all pipeline manifests: project, execution, broll, motion, evidence, edit,
    assembly, and QC report.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.mkdtemp()
        cls.task_id = "manifest-audit-task-001"
        cls.task_dir = Path(cls.temp_dir) / "tasks" / cls.task_id
        cls.task_dir.mkdir(parents=True, exist_ok=True)
        cls.export_dir = Path(cls.temp_dir) / "exports" / "audit-package"

        # Create project with 3 scenes: DATA, TEXT, and optional DOCUMENT fallback
        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=1.0,
                narration="First data scene.",
                payload={"template": "number", "headline": "DATA CUE", "data": {"val": "100"}},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.text,
                purpose=VisualPurpose.emphasis,
                start=1.0,
                end=2.0,
                narration="Second text scene.",
                payload={"headline": "TEXT CUE", "subheadline": "Subtitle"},
            ),
            VisualCue(
                id="S003",
                order=3,
                visual_type=VisualType.document,
                purpose=VisualPurpose.evidence,
                start=2.0,
                end=3.0,
                narration="Third document fallback scene.",
                payload={
                    "search_query": "Missing source query",
                    "source_hint": "Nonexistent",
                    "evidence_required": False,
                    "highlight_target": "Missing document target",
                    "source_ids": ["NON_EXISTENT_ID"],
                },
            ),
        ]
        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in cues
        ]

        dummy_audio = cls.task_dir / "narration.wav"
        with wave.open(str(dummy_audio), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(bytearray(44100 * 3))

        dummy_timing = cls.task_dir / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": [
            {"start": 0.0, "end": 1.0, "text": "First data scene."},
            {"start": 1.0, "end": 2.0, "text": "Second text scene."},
            {"start": 2.0, "end": 3.0, "text": "Third document fallback scene."},
        ]}), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Manifest Audit Project",
                language="en-US",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Manifest Audit",
                script="First data scene. Second text scene. Third document fallback scene.",
                search_terms=["audit", "manifest"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )

        project_path = cls.task_dir / "project.json"
        save_project_spec(project, project_path)

        # Seed planning artifacts
        save_project_spec(project, cls.task_dir / "project.planned.json")
        (cls.task_dir / "visual_plan.json").write_text(
            json.dumps({"schema_version": "1.0", "project_title": project.project.title, "cues": [c.model_dump(mode="json") for c in cues]}),
            encoding="utf-8",
        )
        (cls.task_dir / "timeline.json").write_text(
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
        now = "2026-08-16T00:00:00Z"
        p_manifest = ProjectManifest(
            schema_version=project.schema_version,
            project_title=project.project.title,
            project_file=str(project_path),
            task_id=cls.task_id,
            status=ProjectStatus.processing,
            fps=30,
            aspect_ratio=VideoAspect.landscape,
            created_at=now,
            updated_at=now,
        )
        (cls.task_dir / "project_manifest.json").write_text(
            json.dumps(p_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        fp = compute_project_input_fingerprint(project)
        (cls.task_dir / "orchestrator_state.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "task_id": cls.task_id,
                "source_project_fingerprint": fp,
                "source_project_file": str(project_path),
                "created_at": now,
                "updated_at": now,
            }, indent=2),
            encoding="utf-8",
        )

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(cls.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(cls.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(cls.task_dir)), \
             patch("app.services.export_runner.utils.task_dir", return_value=str(cls.task_dir)):

            cls.orch_res = run_all_project(project_path, task_id=cls.task_id)
            cls.export_res = export_editor_package(project_path, task_id=cls.task_id, output_dir=cls.export_dir)
            edit_manifest_path = cls.export_dir / "edit_manifest.json"
            cfg = AssemblyConfig(fps=30, resolution=[1920, 1080], crf=20)
            cls.assembly_res = assemble_final_video(edit_manifest_path, task_id=cls.task_id, config=cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _get_motion_manifest(self) -> dict:
        m_path = self.task_dir / "motion" / "motion_manifest.json"
        if not m_path.exists():
            m_path = self.task_dir / "motion_manifest.json"
        if m_path.exists():
            return json.loads(m_path.read_text(encoding="utf-8"))
        return {}

    def test_project_manifest_to_motion_manifest(self) -> None:
        """Requirement 1: All motion scene IDs in project visual cues appear in motion manifest."""
        visual_plan = json.loads((self.task_dir / "visual_plan.json").read_text(encoding="utf-8"))
        motion_manifest = self._get_motion_manifest()

        planned_motion_ids = {
            c["id"] for c in visual_plan["cues"]
            if c.get("visual_type") in ("data", "text")
        }
        motion_manifest_ids = {
            a["scene_id"] for a in motion_manifest.get("assets", [])
        }

        for s_id in planned_motion_ids:
            self.assertIn(
                s_id,
                motion_manifest_ids,
                f"Planned motion scene {s_id} missing from motion_manifest.json",
            )

    def test_motion_manifest_to_edit_manifest(self) -> None:
        """Requirement 2: All scenes in motion manifest appear in edit manifest."""
        motion_manifest = self._get_motion_manifest()
        edit_manifest = json.loads((self.export_dir / "edit_manifest.json").read_text(encoding="utf-8"))

        edit_scene_ids = {s["scene_id"] for s in edit_manifest.get("scenes", [])}
        for asset in motion_manifest.get("assets", []):
            s_id = asset["scene_id"]
            self.assertIn(
                s_id,
                edit_scene_ids,
                f"Motion scene {s_id} missing from edit_manifest.json",
            )

    def test_edit_manifest_files_exist_on_disk(self) -> None:
        """Requirement 3: All files listed in edit_manifest.json exist on disk with positive size."""
        edit_manifest_path = self.export_dir / "edit_manifest.json"
        self.assertTrue(edit_manifest_path.exists())
        data = json.loads(edit_manifest_path.read_text(encoding="utf-8"))

        # Narration audio file
        narr_rel = data.get("narration_file")
        if narr_rel:
            narr_path = self.export_dir / narr_rel
            self.assertTrue(narr_path.exists(), f"Narration file missing: {narr_path}")
            self.assertGreater(narr_path.stat().st_size, 0)

        # Subtitle file if declared
        sub_rel = data.get("subtitle_file")
        if sub_rel:
            sub_path = self.export_dir / sub_rel
            self.assertTrue(sub_path.exists(), f"Subtitle file missing: {sub_path}")

        # Scene video files
        for scene in data.get("scenes", []):
            sc_rel = scene.get("exported_file")
            self.assertIsNotNone(sc_rel, f"Scene {scene.get('scene_id')} has no exported_file")
            sc_path = self.export_dir / sc_rel
            self.assertTrue(sc_path.exists(), f"Exported scene file missing: {sc_path}")
            self.assertGreater(sc_path.stat().st_size, 0)

    def test_assembly_manifest_files_exist_on_disk(self) -> None:
        """Requirement 4: All files listed in assembly output/manifest exist on disk with positive size."""
        final_mp4 = Path(self.assembly_res.final_video_file)
        self.assertTrue(final_mp4.exists(), f"Final video missing: {final_mp4}")
        self.assertGreater(final_mp4.stat().st_size, 1000)

        qc_report = Path(self.assembly_res.qc_report_file)
        self.assertTrue(qc_report.exists(), f"QC report missing: {qc_report}")
        self.assertGreater(qc_report.stat().st_size, 0)

    def test_qc_report_validity_and_final_mp4(self) -> None:
        """Requirement 5: QC report validity=True corresponds to a valid, playable final.mp4 with size > 0."""
        qc_file = Path(self.assembly_res.qc_report_file)
        qc_data = json.loads(qc_file.read_text(encoding="utf-8"))
        self.assertTrue(qc_data.get("is_valid"), "QC report is_valid must be True")
        self.assertTrue(qc_data.get("has_video_stream"))
        self.assertTrue(qc_data.get("has_audio_stream"))
        self.assertEqual(qc_data.get("resolution"), [1920, 1080])

        final_mp4 = Path(self.assembly_res.final_video_file)
        self.assertTrue(final_mp4.exists())
        self.assertGreater(final_mp4.stat().st_size, 1000)

    def test_no_dangling_ready_records(self) -> None:
        """Requirement 6: No manifest record with status READY / complete points to a missing file."""
        # 1. Execution manifest
        exec_manifest_path = self.task_dir / "execution_manifest.json"
        if exec_manifest_path.exists():
            exec_data = json.loads(exec_manifest_path.read_text(encoding="utf-8"))
            for scene in exec_data.get("scenes", []):
                if scene.get("status") == "ready":
                    out_file = scene.get("output_file")
                    self.assertIsNotNone(out_file, f"Scene {scene.get('scene_id')} ready but no output_file")
                    self.assertTrue(Path(out_file).exists(), f"Dangling output_file in execution_manifest: {out_file}")

        # 2. Motion manifest
        motion_manifest_path = self.task_dir / "motion_manifest.json"
        if motion_manifest_path.exists():
            m_data = json.loads(motion_manifest_path.read_text(encoding="utf-8"))
            for asset in m_data.get("assets", []):
                rendered = asset.get("rendered_file")
                if rendered:
                    self.assertTrue(Path(rendered).exists(), f"Dangling rendered_file in motion_manifest: {rendered}")

        # 3. Edit manifest
        edit_manifest_path = self.export_dir / "edit_manifest.json"
        if edit_manifest_path.exists():
            e_data = json.loads(edit_manifest_path.read_text(encoding="utf-8"))
            for scene in e_data.get("scenes", []):
                exp_file = self.export_dir / scene["exported_file"]
                self.assertTrue(exp_file.exists(), f"Dangling scene file in edit_manifest: {exp_file}")


if __name__ == "__main__":
    unittest.main()
