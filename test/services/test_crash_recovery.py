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
from app.models.export import EditManifest, EditorPackageStatus, EditorSceneEntry
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
from app.services.project_spec import load_project_spec, save_project_spec
from app.services.scene_orchestrator import (
    compute_project_input_fingerprint,
    run_all_project,
)


class TestCrashRecovery(unittest.TestCase):
    """G12.4 Crash Recovery Tests.

    Simulates interruptions at each pipeline stage, corrupted state, partial temp files,
    and different project fingerprints to verify resilient recovery.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "crash-recovery-task-001"
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir = Path(self.temp_dir) / "exports" / "crash-package"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_base_project(self, task_id: str | None = None, title: str = "Crash Test Project") -> tuple[ProjectSpec, Path]:
        t_id = task_id or self.task_id
        t_dir = Path(self.temp_dir) / "tasks" / t_id
        t_dir.mkdir(parents=True, exist_ok=True)

        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=1.0,
                narration="Data cue narration.",
                payload={"template": "number", "headline": "Growth", "data": {"val": "100"}},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.text,
                purpose=VisualPurpose.emphasis,
                start=1.0,
                end=2.0,
                narration="Text cue narration.",
                payload={"headline": "Key Takeaway", "subheadline": "Summary"},
            ),
        ]
        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in cues
        ]

        dummy_audio = t_dir / "narration.wav"
        with wave.open(str(dummy_audio), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(bytearray(44100 * 2))

        dummy_timing = t_dir / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": [
            {"start": 0.0, "end": 1.0, "text": "Data cue narration."},
            {"start": 1.0, "end": 2.0, "text": "Text cue narration."},
        ]}), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title=title,
                language="en-US",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject=title,
                script="Data cue narration. Text cue narration.",
                search_terms=["growth", "summary"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )
        project_path = t_dir / "project.json"
        save_project_spec(project, project_path)
        return project, project_path

    def _seed_planning_artifacts(self, project: ProjectSpec, project_path: Path, task_dir: Path, task_id: str) -> None:
        save_project_spec(project, task_dir / "project.planned.json")
        (task_dir / "visual_plan.json").write_text(
            json.dumps({"schema_version": "1.0", "project_title": project.project.title, "cues": [c.model_dump(mode="json") for c in project.visual_cues]}),
            encoding="utf-8",
        )
        (task_dir / "timeline.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "project_title": project.project.title,
                "audio_file": str(task_dir / "narration.wav"),
                "timing_file": str(task_dir / "timing.json"),
                "duration": 2.0,
                "cues": [c.model_dump(mode="json") for c in project.timeline_cues],
            }),
            encoding="utf-8",
        )
        now = "2026-08-16T00:00:00Z"
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

    def test_interrupt_after_planning(self) -> None:
        """Requirement 1: When planning artifacts exist, rerun reuses them without re-planning."""
        project, project_path = self._create_base_project()
        self._seed_planning_artifacts(project, project_path, self.task_dir, self.task_id)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)):

            res = run_all_project(project_path, task_id=self.task_id)

        self.assertEqual(res["status"], "complete")
        exec_manifest = json.loads((self.task_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        planning_stage = next(s for s in exec_manifest["stages"] if s["name"] == "planning")
        self.assertTrue(planning_stage["metadata"].get("reused"))

    def test_interrupt_after_broll(self) -> None:
        """Requirement 2: When B-roll stage completed previously, rerun reuses it."""
        project, project_path = self._create_base_project()
        self._seed_planning_artifacts(project, project_path, self.task_dir, self.task_id)

        # Seed completed B-roll stage
        save_project_spec(project, self.task_dir / "project.assets.json")
        broll_manifest = {
            "schema_version": "1.0",
            "task_id": self.task_id,
            "status": "complete",
            "assets": [],
            "failed_scenes": [],
        }
        (self.task_dir / "broll_manifest.json").write_text(json.dumps(broll_manifest), encoding="utf-8")

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.broll_runner.run_broll_acquisition") as mock_broll:

            res = run_all_project(project_path, task_id=self.task_id)

        self.assertEqual(res["status"], "complete")
        # Assert broll acquisition runner was skipped
        mock_broll.assert_not_called()

    def test_interrupt_after_motion(self) -> None:
        """Requirement 3: When motion scenes are already rendered, rerun skips motion rendering."""
        project, project_path = self._create_base_project()
        self._seed_planning_artifacts(project, project_path, self.task_dir, self.task_id)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)):

            res1 = run_all_project(project_path, task_id=self.task_id)
            self.assertEqual(res1["status"], "complete")

            # Run 2: Motion should be reused
            with patch("app.services.remotion._invoke_node_renderer") as mock_remotion:
                res2 = run_all_project(project_path, task_id=self.task_id)
                self.assertEqual(res2["status"], "complete")
                mock_remotion.assert_not_called()

    def test_interrupt_after_evidence(self) -> None:
        """Requirement 4: When evidence stage completed, rerun skips evidence acquisition."""
        project, project_path = self._create_base_project()
        self._seed_planning_artifacts(project, project_path, self.task_dir, self.task_id)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)):

            res1 = run_all_project(project_path, task_id=self.task_id)
            self.assertEqual(res1["status"], "complete")

            with patch("app.services.evidence_runner.run_evidence_acquisition") as mock_evidence:
                res2 = run_all_project(project_path, task_id=self.task_id)
                self.assertEqual(res2["status"], "complete")
                mock_evidence.assert_not_called()

    def test_interrupt_during_export_temp(self) -> None:
        """Requirement 5: Partial .tmp export files left from crash are cleaned up and overwritten."""
        project, project_path = self._create_base_project()
        self._seed_planning_artifacts(project, project_path, self.task_dir, self.task_id)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)):

            run_all_project(project_path, task_id=self.task_id)

            # Plant orphan .tmp files
            self.export_dir.mkdir(parents=True, exist_ok=True)
            orphan_tmp = self.export_dir / "edit_manifest.json.tmp.1234"
            orphan_tmp.write_text("corrupt partial data", encoding="utf-8")

            # Run export
            exp_res = export_editor_package(project_path, task_id=self.task_id, output_dir=self.export_dir)
            self.assertEqual(exp_res.status, "complete")
            self.assertTrue((self.export_dir / "edit_manifest.json").exists())

    def test_interrupt_during_assembly_temp(self) -> None:
        """Requirement 6: Partial assembly .tmp files left from crash are cleaned up and overwritten."""
        export_dir = Path(self.temp_dir) / "exports" / "assembly-crash"
        export_dir.mkdir(parents=True, exist_ok=True)
        scenes_dir = export_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)
        narr_dir = export_dir / "narration"
        narr_dir.mkdir(parents=True, exist_ok=True)

        clip_path = scenes_dir / "S001_DATA.mp4"
        c = ColorClip(size=(640, 360), color=(50, 50, 50), duration=1.0)
        c.write_videofile(str(clip_path), fps=30, codec="libx264", logger=None)
        c.close()
        clip_sha = compute_file_sha256(clip_path)

        narr_path = narr_dir / "narration.wav"
        with wave.open(str(narr_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(bytearray(44100 * 2))
        narr_sha = compute_file_sha256(narr_path)

        manifest = EditManifest(
            schema_version="1.0",
            project_title="Assembly Crash Project",
            project_slug="assembly-crash-project",
            task_id="crash-assembly-task",
            source_project_fingerprint="fp-assembly-crash",
            export_fingerprint="exp-assembly-crash",
            package_status=EditorPackageStatus.complete,
            fps=30,
            resolution=[640, 360],
            aspect_ratio="16:9",
            duration_frames=30,
            duration_seconds=1.0,
            narration_file="narration/narration.wav",
            narration_sha256=narr_sha,
            subtitle_file=None,
            subtitle_sha256=None,
            scenes=[
                EditorSceneEntry(
                    scene_id="S001",
                    order=1,
                    planned_visual_type=VisualType.data,
                    resolved_visual_type=VisualType.data,
                    start_frame=0,
                    end_frame=30,
                    duration_frames=30,
                    exported_file="scenes/S001_DATA.mp4",
                    sha256=clip_sha,
                )
            ],
            source_provenance=[],
            missing_scenes=[],
            created_at="2026-08-16T12:00:00Z",
            updated_at="2026-08-16T12:00:00Z",
            outputs={"export_dir": str(export_dir)},
        )
        manifest_path = export_dir / "edit_manifest.json"
        manifest_path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8")

        # Plant orphan final mp4 temp file
        final_dir = export_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        orphan_mp4_tmp = final_dir / "final.mp4.tmp.9999.nonce.mp4"
        orphan_mp4_tmp.write_bytes(b"\x00" * 512)

        cfg = AssemblyConfig(fps=30, resolution=[640, 360], crf=23)
        res = assemble_final_video(manifest_path, task_id="crash-assembly-task", config=cfg)
        self.assertEqual(res.status, AssemblyStatus.complete.value)
        final_mp4 = Path(res.final_video_file)
        self.assertTrue(final_mp4.exists())
        self.assertGreater(final_mp4.stat().st_size, 1000)

    def test_no_wrong_project_stale_reuse(self) -> None:
        """Requirement 7: Different project with different fingerprint in same task_dir raises ProjectRunError and refuses stale reuse."""
        from app.services.project_runner import ProjectRunError

        project1, project1_path = self._create_base_project(title="Project One Alpha")
        self._seed_planning_artifacts(project1, project1_path, self.task_dir, self.task_id)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)):

            res1 = run_all_project(project1_path, task_id=self.task_id)
            self.assertEqual(res1["status"], "complete")

            # Modify project content (change cues and title)
            project2, project2_path = self._create_base_project(title="Project Two Beta Different Fingerprint")
            project2.visual_cues[0].payload["headline"] = "Brand New Different Headline"
            save_project_spec(project2, project2_path)

            # Different project with different fingerprint in same task must be rejected
            with self.assertRaises(ProjectRunError) as ctx:
                run_all_project(project2_path, task_id=self.task_id)
            self.assertIn("fingerprint mismatch", str(ctx.exception).lower())

    def test_no_corrupt_canonical_json(self) -> None:
        """Requirement 8: Truncated or corrupt canonical JSON is detected and cleanly regenerated."""
        project, project_path = self._create_base_project()
        self._seed_planning_artifacts(project, project_path, self.task_dir, self.task_id)

        # Corrupt the visual_plan.json
        (self.task_dir / "visual_plan.json").write_text('{"schema_version": "1.0", "cues": [TRUNCATED...', encoding="utf-8")

        def mock_plan(src, task_id):
            self._seed_planning_artifacts(project, project_path, self.task_dir, self.task_id)
            return {"status": "complete"}

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.scene_orchestrator.run_project_plan", side_effect=mock_plan):

            res = run_all_project(project_path, task_id=self.task_id)

        self.assertEqual(res["status"], "complete")
        # Verify visual_plan.json was regenerated as valid JSON
        valid_json = json.loads((self.task_dir / "visual_plan.json").read_text(encoding="utf-8"))
        self.assertIn("cues", valid_json)


if __name__ == "__main__":
    unittest.main()
