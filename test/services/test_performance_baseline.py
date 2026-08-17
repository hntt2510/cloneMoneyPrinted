from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
import wave
import struct
from pathlib import Path
from unittest.mock import patch

from moviepy import ColorClip

from app.models.assembly import AssemblyConfig
from app.models.export import EditManifest, EditorPackageStatus, EditorSceneEntry
from app.models.project import (
    DataPayload,
    ProjectManifest,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    ScriptSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.assembly_runner import compute_assembly_fingerprint
from app.services.evidence_sources import compute_file_sha256
from app.services.export_runner import export_editor_package
from app.services.project_spec import load_project_spec, save_project_spec
from app.services.scene_orchestrator import (
    _is_planning_reusable,
    compute_project_input_fingerprint,
)


class TestPerformanceBaseline(unittest.TestCase):
    """G12.8 Performance Baseline Tests.

    Records local timing baselines for key operations to guard against severe regressions.
    Uses generous upper bounds so tests pass reliably across different CPU environments.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "perf-baseline-task-001"
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir = Path(self.temp_dir) / "exports" / "perf-package"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_mock_project(self) -> tuple[ProjectSpec, Path]:
        cues = [
            VisualCue(
                id=f"S{i:03d}",
                order=i,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=float(i - 1),
                end=float(i),
                narration=f"Scene {i} narration.",
                payload={"template": "number", "headline": f"SCENE {i}", "data": {"val": str(i * 10)}},
            )
            for i in range(1, 4)
        ]
        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in cues
        ]

        dummy_audio = self.task_dir / "narration.wav"
        with wave.open(str(dummy_audio), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(bytearray(44100 * 3))

        dummy_timing = self.task_dir / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": []}), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Perf Test Project",
                language="en-US",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Performance Baseline",
                script="Scene narration.",
                search_terms=["perf"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )

        project_path = self.task_dir / "project.json"
        save_project_spec(project, project_path)

        # Seed planning artifacts
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
        now = "2026-08-16T00:00:00Z"
        p_manifest = ProjectManifest(
            schema_version=project.schema_version,
            project_title=project.project.title,
            project_file=str(project_path),
            task_id=self.task_id,
            status=ProjectStatus.processing,
            fps=30,
            aspect_ratio=VideoAspect.landscape,
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

    def test_planning_reuse_startup(self) -> None:
        """Requirement 1: Planning reuse verification and startup takes < 2.0s."""
        project, project_path = self._setup_mock_project()
        fp = compute_project_input_fingerprint(project)

        start = time.perf_counter()
        reusable, reason = _is_planning_reusable(self.task_dir, fp, project, has_prior_ownership=True)
        elapsed = time.perf_counter() - start

        self.assertTrue(reusable)
        self.assertLess(elapsed, 2.0, f"Planning reuse check took {elapsed:.4f}s (> 2.0s)")

    def test_export_package_creation(self) -> None:
        """Requirement 2: Packaging an already-executed 3-scene project takes < 5.0s."""
        from app.models.execution import ExecutionManifest, ExecutionStageStatus, SceneExecutionRecord

        project, project_path = self._setup_mock_project()
        fp = compute_project_input_fingerprint(project)

        # Seed mock rendered scene files and execution manifest
        motion_dir = self.task_dir / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        scenes = []
        for i in range(1, 4):
            sc_file = motion_dir / f"S{i:03d}_DATA.mp4"
            sc_file.write_bytes(b"\x00" * 1024)
            scenes.append(
                SceneExecutionRecord(
                    scene_id=f"S{i:03d}",
                    order=i,
                    planned_visual_type=VisualType.data,
                    resolved_visual_type=VisualType.data,
                    status="ready",
                    start=float(i - 1),
                    end=float(i),
                    start_frame=(i - 1) * 30,
                    end_frame=i * 30,
                    duration_frames=30,
                    output_file=str(sc_file),
                )
            )

        exec_manifest = ExecutionManifest(
            schema_version="1.0",
            project_title=project.project.title,
            task_id=self.task_id,
            source_project_file=str(project_path.resolve()),
            source_project_fingerprint=fp,
            status=ExecutionStageStatus.complete,
            scenes=scenes,
            stages=[],
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
        )
        (self.task_dir / "execution_manifest.json").write_text(
            json.dumps(exec_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        from app.models.project import RenderJob, JobStatus

        project.render_jobs = [
            RenderJob(
                id=f"job-{i}",
                scene_id=f"S{i:03d}",
                kind="motion",
                status=JobStatus.ready,
                output=f"motion/S{i:03d}_DATA.mp4",
            )
            for i in range(1, 4)
        ]
        save_project_spec(project, self.task_dir / "project.executed.json")

        with patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)), patch(
            "app.services.export_runner.probe_media_frames", return_value=30
        ):
            start = time.perf_counter()
            res = export_editor_package(project_path, task_id=self.task_id, output_dir=self.export_dir)
            elapsed = time.perf_counter() - start

        self.assertEqual(res.status, "complete")
        self.assertLess(elapsed, 5.0, f"Editor package export took {elapsed:.4f}s (> 5.0s)")

    def test_assembly_fingerprint_compute(self) -> None:
        """Requirement 3: Assembly fingerprint compute takes < 0.5s."""
        cfg = AssemblyConfig(fps=30, resolution=[1920, 1080], crf=20)
        scene_shas = ["sha1", "sha2", "sha3"]

        start = time.perf_counter()
        fp = compute_assembly_fingerprint(
            export_fingerprint="fp-exp",
            scene_shas=scene_shas,
            narration_sha="narr-sha",
            subtitle_sha=None,
            config=cfg,
        )
        elapsed = time.perf_counter() - start

        self.assertTrue(len(fp) > 0)
        self.assertLess(elapsed, 0.5, f"Assembly fingerprint compute took {elapsed:.4f}s (> 0.5s)")

    def test_artifact_size_reasonable(self) -> None:
        """Requirement 4: Pipeline manifest JSON files are concise (< 1MB each)."""
        project, project_path = self._setup_mock_project()
        manifest_files = [
            self.task_dir / "project.json",
            self.task_dir / "project.planned.json",
            self.task_dir / "visual_plan.json",
            self.task_dir / "timeline.json",
            self.task_dir / "project_manifest.json",
            self.task_dir / "orchestrator_state.json",
        ]
        for f in manifest_files:
            if f.exists():
                size_bytes = f.stat().st_size
                self.assertLess(
                    size_bytes,
                    1_000_000,
                    f"Artifact {f.name} size ({size_bytes} bytes) exceeds 1MB threshold",
                )


if __name__ == "__main__":
    unittest.main()
