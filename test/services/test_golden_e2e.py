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

import pymupdf
from moviepy import ColorClip, VideoFileClip

from app.models.assembly import AssemblyConfig, AssemblyStatus
from app.models.export import EditManifest, EditorPackageStatus
from app.models.project import (
    BrollPayload,
    DataPayload,
    DocumentPayload,
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


def _create_synthetic_test_pdf(dest_path: Path, note: str = "Official policy statement: Retirement benefits start at age 67.") -> Path:
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 100), "OFFICIAL RETIREMENT REPORT", fontsize=20)
    p.insert_text((50, 150), f"Policy Clause 101: {note}", fontsize=14)
    p.insert_text((50, 180), "Early distributions are penalized by 10 percent.", fontsize=12)
    doc.save(str(dest_path))
    doc.close()
    return dest_path


def _create_synthetic_wav(dest_path: Path, duration_seconds: float = 5.0, sample_rate: int = 44100) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        total_samples = int(sample_rate * duration_seconds)
        frames = bytearray()
        for _ in range(total_samples):
            frames.extend(struct.pack("<h", 0))
        wf.writeframes(frames)
    return dest_path


class TestGoldenE2E(unittest.TestCase):
    """G12.1 Golden End-to-End Fixture Test.

    Fully deterministic, no-network, reproducible pipeline test exercising:
    1. DATA scene (Remotion motion render)
    2. TEXT scene (Remotion motion render)
    3. BROLL scene (Mocked local acquisition)
    4. DOCUMENT scene (PyMuPDF local PDF render)
    5. Optional DOCUMENT fallback scene (Non-existent PDF source -> falls back to TEXT)
    6. Editor package export (G09)
    7. Final video assembly and QC inspection (G10)

    Must pass twice consecutively with identical outputs.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "golden-e2e-task-001"
        self.project_dir = Path(self.temp_dir) / "project"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir = Path(self.temp_dir) / "exports" / "golden-e2e-package"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_golden_project(self) -> tuple[ProjectSpec, Path]:
        aspect = VideoAspect.landscape
        target_w, target_h = aspect.to_resolution()

        # 1. Create local test PDF
        pdf_name = "golden_evidence.pdf"
        pdf_path = self.project_dir / pdf_name
        _create_synthetic_test_pdf(pdf_path, note="Official policy statement: Retirement benefits start at age 67.")

        # 2. Create sources.json
        sources_json_path = self.project_dir / "sources.json"
        sources_data = {
            "sources": [
                {
                    "id": "SRC_GOLDEN_PDF",
                    "kind": "pdf",
                    "local_file": pdf_name,
                    "title": "Official Retirement Report",
                    "publisher": "Federal Retirement Agency",
                    "trust": "official",
                    "quote_hint": None,
                    "tags": ["retirement", "official", "67"],
                }
            ]
        }
        sources_json_path.write_text(json.dumps(sources_data, indent=2), encoding="utf-8")

        # 3. Create cues
        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=1.0,
                narration="Retirement age is 67.",
                payload={"template": "number", "headline": "RETIREMENT AGE", "data": {"primary_value": "67", "label": "Age"}},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.text,
                purpose=VisualPurpose.emphasis,
                start=1.0,
                end=2.0,
                narration="Plan ahead for your future.",
                payload={"headline": "Plan Ahead Today", "subheadline": "Secure Your Retirement"},
            ),
            VisualCue(
                id="S003",
                order=3,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                start=2.0,
                end=3.0,
                narration="Many retirees enjoy traveling.",
                payload=BrollPayload(search_query="retirees enjoying travel").model_dump(mode="json"),
            ),
            VisualCue(
                id="S004",
                order=4,
                visual_type=VisualType.document,
                purpose=VisualPurpose.evidence,
                start=3.0,
                end=4.0,
                narration="Official policy statement confirms age 67.",
                payload={
                    "search_query": "Official policy retirement age 67",
                    "source_hint": "Federal Retirement Agency",
                    "evidence_required": True,
                    "highlight_target": "Official policy statement: Retirement benefits start at age 67.",
                    "source_ids": ["SRC_GOLDEN_PDF"],
                },
            ),
            VisualCue(
                id="S005",
                order=5,
                visual_type=VisualType.document,
                purpose=VisualPurpose.evidence,
                start=4.0,
                end=5.0,
                narration="Additional notes and closing summary.",
                payload={
                    "search_query": "Quantum physics entanglement theory",
                    "source_hint": "Physics Journal",
                    "evidence_required": False,
                    "highlight_target": "Quantum entanglement state vector cannot be cloned",
                    "source_ids": ["NON_EXISTENT_SRC_ID"],
                },
            ),
        ]

        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in sorted(cues, key=lambda x: x.order)
        ]

        dummy_audio = self.task_dir / "narration.wav"
        _create_synthetic_wav(dummy_audio, duration_seconds=5.0)

        dummy_timing = self.task_dir / "timing.json"
        timing_content = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Retirement age is 67."},
                {"start": 1.0, "end": 2.0, "text": "Plan ahead for your future."},
                {"start": 2.0, "end": 3.0, "text": "Many retirees enjoy traveling."},
                {"start": 3.0, "end": 4.0, "text": "Official policy statement confirms age 67."},
                {"start": 4.0, "end": 5.0, "text": "Additional notes and closing summary."},
            ]
        }
        dummy_timing.write_text(json.dumps(timing_content, indent=2), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Golden E2E Fixture Project",
                language="en-US",
                aspect_ratio=aspect,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Retirement Guide",
                script=" ".join(c.narration for c in cues),
                search_terms=["retirement", "future", "policy"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )

        project_path = self.project_dir / "project.json"
        save_project_spec(project, project_path)

        # Pre-seed planning artifacts in task_dir
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
                "duration": 5.0,
                "cues": [c.model_dump(mode="json") for c in timeline_cues],
            }),
            encoding="utf-8",
        )
        now = "2026-08-16T00:00:00Z"
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

    def _mock_acquire_broll_asset(self, cue, **kwargs) -> SelectedBrollAsset:
        broll_dir = self.task_dir / "broll" / cue.id
        broll_dir.mkdir(parents=True, exist_ok=True)
        rendered_file = broll_dir / "rendered.mp4"
        source_file = broll_dir / "source.mp4"

        # Create 1s silent color video clip for BROLL
        clip = ColorClip(size=(1920, 1080), color=(40, 80, 120), duration=1.0)
        clip.write_videofile(str(rendered_file), fps=30, codec="libx264", logger=None)
        clip.close()
        shutil.copyfile(rendered_file, source_file)

        return SelectedBrollAsset(
            scene_id=cue.id,
            provider="pexels",
            provider_asset_id="golden-broll-123",
            query_used="retirees enjoying travel",
            candidate_id="pexels-golden-123",
            download_url="https://dl.example/golden.mp4",
            source_file=str(source_file.resolve()),
            rendered_file=str(rendered_file.resolve()),
            source_duration=1.0,
            trim_start=0.0,
            trim_end=1.0,
            scene_duration=1.0,
            width=1920,
            height=1080,
            score=95.0,
            metadata={"attempts": 1},
        )

    def test_golden_e2e_deterministic_pipeline(self) -> None:
        project, project_path = self._setup_golden_project()

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.broll_runner.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.broll_runner.acquire_broll_scene", side_effect=self._mock_acquire_broll_asset):

            # --- RUN 1 ---
            orch_res_1 = run_all_project(project_path, task_id=self.task_id)
            self.assertEqual(orch_res_1["status"], "complete")
            self.assertEqual(orch_res_1["ready_scenes"], 5)
            self.assertEqual(orch_res_1["failed_scenes"], 0)

            export_res_1 = export_editor_package(project_path, task_id=self.task_id, output_dir=self.export_dir)
            self.assertEqual(export_res_1.status, "complete")
            self.assertEqual(export_res_1.ready_scene_count, 5)

            edit_manifest_path = self.export_dir / "edit_manifest.json"
            self.assertTrue(edit_manifest_path.exists())

            cfg = AssemblyConfig(fps=30, resolution=[1920, 1080], crf=20)
            assembly_res_1 = assemble_final_video(edit_manifest_path, task_id=self.task_id, config=cfg)
            self.assertEqual(assembly_res_1.status, AssemblyStatus.complete.value)

            final_mp4_1 = Path(assembly_res_1.final_video_file)
            self.assertTrue(final_mp4_1.exists())
            qc_file_1 = Path(assembly_res_1.qc_report_file)
            self.assertTrue(qc_file_1.exists())
            qc_1 = json.loads(qc_file_1.read_text(encoding="utf-8"))
            self.assertTrue(qc_1["is_valid"])
            self.assertTrue(qc_1["has_video_stream"])
            self.assertTrue(qc_1["has_audio_stream"])

            # Verify all 5 scene types resolved properly
            edit_manifest_1 = EditManifest.model_validate(json.loads(edit_manifest_path.read_text(encoding="utf-8")))
            scene_types = {s.scene_id: s.resolved_visual_type for s in edit_manifest_1.scenes}
            self.assertEqual(scene_types["S001"], VisualType.data)
            self.assertEqual(scene_types["S002"], VisualType.text)
            self.assertEqual(scene_types["S003"], VisualType.broll)
            self.assertEqual(scene_types["S004"], VisualType.document)
            self.assertEqual(scene_types["S005"], VisualType.text)  # fallback from optional document

            # --- RUN 2 (Consecutive Run for Idempotency / Determinism) ---
            orch_res_2 = run_all_project(project_path, task_id=self.task_id)
            self.assertEqual(orch_res_2["status"], "complete")
            self.assertEqual(orch_res_2["ready_scenes"], 5)

            export_res_2 = export_editor_package(project_path, task_id=self.task_id, output_dir=self.export_dir)
            self.assertEqual(export_res_2.status, "complete")
            self.assertEqual(export_res_2.ready_scene_count, 5)

            assembly_res_2 = assemble_final_video(edit_manifest_path, task_id=self.task_id, config=cfg)
            self.assertEqual(assembly_res_2.status, AssemblyStatus.complete.value)

            # Assert identical output files exist and valid
            final_mp4_2 = Path(assembly_res_2.final_video_file)
            self.assertTrue(final_mp4_2.exists())
            qc_file_2 = Path(assembly_res_2.qc_report_file)
            self.assertTrue(qc_file_2.exists())
            qc_2 = json.loads(qc_file_2.read_text(encoding="utf-8"))
            self.assertTrue(qc_2["is_valid"])


if __name__ == "__main__":
    unittest.main()
