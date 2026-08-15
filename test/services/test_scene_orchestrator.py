from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.execution import (
    ExecutionManifest,
    ExecutionStageStatus,
)
from app.models.project import (
    AssetJob,
    BrollPayload,
    DataPayload,
    DataTemplate,
    DocumentPayload,
    JobStatus,
    NarrationMode,
    ProjectManifest,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    RenderJob,
    ScriptSpec,
    TextPayload,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.project_runner import ProjectRunError
from app.services.project_spec import save_project_spec
from app.services.scene_orchestrator import (
    compute_project_input_fingerprint,
    run_all_project,
    sanitize_error_message,
)


class TestSceneOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_dir = Path(self.temp_dir) / "tasks" / "task-orch-001"
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_mock_project(
        self,
        cues: list[VisualCue] | None = None,
        title: str = "Retirement Rules",
    ) -> ProjectSpec:
        if cues is None:
            cues = [
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    start=0.0,
                    end=3.0,
                    narration="Retirement planning begins early.",
                    payload={"search_query": "retiree senior couple"},
                ),
                VisualCue(
                    id="S002",
                    order=2,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=3.0,
                    end=6.0,
                    narration="Full retirement age is 67.",
                    payload={
                        "template": "number",
                        "headline": "Full Retirement Age",
                        "data": {"primary_value": "67", "label": "Full Retirement Age"},
                    },
                ),
                VisualCue(
                    id="S003",
                    order=3,
                    visual_type=VisualType.document,
                    purpose=VisualPurpose.evidence,
                    start=6.0,
                    end=9.0,
                    narration="Medicare coverage starts at 65.",
                    payload={
                        "search_query": "Medicare coverage age 65",
                        "source_hint": "Medicare rules",
                        "evidence_required": False,
                        "highlight_target": "Medicare age 65",
                    },
                ),
            ]

        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in sorted(cues, key=lambda x: x.order)
        ]

        dummy_audio = Path(self.temp_dir) / "narration.mp3"
        dummy_audio.write_bytes(b"\x00" * 1024)

        dummy_timing = Path(self.temp_dir) / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": []}), encoding="utf-8")

        return ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title=title,
                language="en-US",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Retirement Guide",
                script="Retirement planning begins early. Full retirement age is 67. Medicare coverage starts at 65.",
                search_terms=["retirement", "medicare"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={"file": str(dummy_audio), "timing_file": str(dummy_timing)},
        )

    def _setup_mock_planning_artifacts(self, project: ProjectSpec, task_directory: Path) -> None:
        task_directory.mkdir(parents=True, exist_ok=True)
        save_project_spec(project, task_directory / "project.planned.json")
        (task_directory / "visual_plan.json").write_text(
            json.dumps({"project_title": project.project.title, "cues": []}), encoding="utf-8"
        )
        (task_directory / "timeline.json").write_text(
            json.dumps({"project_title": project.project.title, "cues": []}), encoding="utf-8"
        )
        now = "2026-08-15T00:00:00Z"
        p_manifest = ProjectManifest(
            schema_version=project.schema_version,
            project_title=project.project.title,
            project_file=str(task_directory / "project.json"),
            task_id=task_directory.name,
            status=ProjectStatus.processing,
            fps=30,
            aspect_ratio=VideoAspect.landscape,
            created_at=now,
            updated_at=now,
        )
        (task_directory / "project_manifest.json").write_text(
            json.dumps(p_manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

    def test_project_fingerprint_deterministic(self) -> None:
        proj1 = self._create_mock_project()
        proj2 = self._create_mock_project()
        fp1 = compute_project_input_fingerprint(proj1)
        fp2 = compute_project_input_fingerprint(proj2)
        self.assertEqual(fp1, fp2)

        # Changing script changes fingerprint
        proj3 = proj1.model_copy(update={"script": proj1.script.model_copy(update={"subject": "Different"})})
        fp3 = compute_project_input_fingerprint(proj3)
        self.assertNotEqual(fp1, fp3)

    def test_sanitize_error_message(self) -> None:
        msg = "Error: Bearer secret_token_12345 failed with api_key=xyz9876 and token=tok555"
        sanitized = sanitize_error_message(msg)
        self.assertNotIn("secret_token_12345", sanitized)
        self.assertNotIn("xyz9876", sanitized)
        self.assertNotIn("tok555", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_stage_ordering_and_same_task_id(self) -> None:
        project = self._create_mock_project()
        task_id = "test-order-task-123"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        call_order = []

        def mock_plan(p, task_id=None):
            call_order.append(("planning", task_id))
            return {"status": "complete"}

        def mock_broll(p, task_id=None):
            call_order.append(("broll", task_id))
            return {"status": "complete", "acquired_assets_count": 1}

        def mock_motion(p, task_id=None):
            call_order.append(("motion", task_id))
            return {"status": "complete", "rendered_scenes_count": 1}

        def mock_evidence(p, task_id=None):
            call_order.append(("evidence", task_id))
            return {"status": "complete", "rendered_scenes_count": 1}

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_project_plan", side_effect=mock_plan), \
             patch("app.services.scene_orchestrator.run_broll_acquisition", side_effect=mock_broll), \
             patch("app.services.scene_orchestrator.run_motion_render", side_effect=mock_motion), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", side_effect=mock_evidence), \
             patch("app.services.scene_orchestrator.validate_rendered_clip"), \
             patch("app.services.scene_orchestrator.validate_rendered_motion_clip"), \
             patch("app.services.scene_orchestrator.validate_rendered_evidence_clip"):

            # Create dummy media outputs
            (t_dir / "broll" / "S001").mkdir(parents=True, exist_ok=True)
            dummy_broll_mp4 = t_dir / "broll" / "S001" / "rendered.mp4"
            dummy_broll_mp4.write_bytes(b"\x00" * 512)

            (t_dir / "motion").mkdir(parents=True, exist_ok=True)
            dummy_motion_mp4 = t_dir / "motion" / "S002_DATA.mp4"
            dummy_motion_mp4.write_bytes(b"\x00" * 512)

            (t_dir / "evidence").mkdir(parents=True, exist_ok=True)
            dummy_ev_mp4 = t_dir / "evidence" / "S003_DOC.mp4"
            dummy_ev_mp4.write_bytes(b"\x00" * 512)

            # Update planned project with jobs
            project.asset_jobs = [
                AssetJob(id="J_BROLL", scene_id="S001", kind="broll", status=JobStatus.ready, output=str(dummy_broll_mp4))
            ]
            project.render_jobs = [
                RenderJob(id="J_DATA", scene_id="S002", kind="motion", status=JobStatus.ready, output=str(dummy_motion_mp4)),
                RenderJob(id="J_DOC", scene_id="S003", kind="document", status=JobStatus.ready, output=str(dummy_ev_mp4)),
            ]
            save_project_spec(project, t_dir / "project.planned.json")

            res = run_all_project(project, task_id=task_id)

        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["ready_scenes"], 3)
        self.assertEqual(res["failed_scenes"], 0)

        # Stage order check: broll, motion, evidence all called with same task_id
        stages_called = [c[0] for c in call_order]
        self.assertEqual(stages_called, ["broll", "motion", "evidence"])
        self.assertTrue(all(c[1] == task_id for c in call_order))

    def test_planning_reused_when_artifacts_valid(self) -> None:
        project = self._create_mock_project()
        task_id = "test-reuse-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_project_plan") as mock_plan, \
             patch("app.services.scene_orchestrator.run_broll_acquisition", return_value={"status": "complete"}), \
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete"}), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", return_value={"status": "complete"}):

            run_all_project(project, task_id=task_id)
            mock_plan.assert_not_called()

            # Check execution manifest planning stage metadata
            exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
            planning_stage = next(s for s in exec_manifest_data["stages"] if s["name"] == "planning")
            self.assertTrue(planning_stage["metadata"].get("reused"))

    def test_project_fingerprint_mismatch_fails_early(self) -> None:
        project_a = self._create_mock_project(title="Project A")
        project_b = self._create_mock_project(title="Project B")
        task_id = "test-mismatch-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        t_dir.mkdir(parents=True, exist_ok=True)

        # Write execution manifest for Project A
        fp_a = compute_project_input_fingerprint(project_a)
        exec_manifest_a = ExecutionManifest(
            schema_version="1.0",
            project_title=project_a.project.title,
            task_id=task_id,
            source_project_file="project.json",
            source_project_fingerprint=fp_a,
            status=ExecutionStageStatus.complete,
            progress_percent=100,
            stages=[],
            scenes=[],
            ready_scene_count=3,
            failed_scene_count=0,
            created_at="2026-08-15T00:00:00Z",
            updated_at="2026-08-15T00:00:00Z",
        )
        (t_dir / "execution_manifest.json").write_text(
            json.dumps(exec_manifest_a.model_dump(mode="json")), encoding="utf-8"
        )

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)):
            with self.assertRaises(ProjectRunError) as cm:
                run_all_project(project_b, task_id=task_id)
            self.assertIn("fingerprint mismatch", str(cm.exception))

    def test_downstream_continuation_after_broll_failure(self) -> None:
        project = self._create_mock_project()
        task_id = "test-broll-fail-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        dummy_motion_mp4 = t_dir / "motion" / "S002_DATA.mp4"
        dummy_motion_mp4.parent.mkdir(parents=True, exist_ok=True)
        dummy_motion_mp4.write_bytes(b"\x00" * 512)

        dummy_ev_mp4 = t_dir / "evidence" / "S003_DOC.mp4"
        dummy_ev_mp4.parent.mkdir(parents=True, exist_ok=True)
        dummy_ev_mp4.write_bytes(b"\x00" * 512)

        def mock_broll(p, task_id=None):
            return {"status": "failed", "error": "B-roll provider rate limit", "failed_scenes_count": 1}

        def mock_motion(p, task_id=None):
            project.render_jobs.append(
                RenderJob(id="J_DATA", scene_id="S002", kind="motion", status=JobStatus.ready, output=str(dummy_motion_mp4))
            )
            save_project_spec(project, t_dir / "project.motion.json")
            return {"status": "complete", "rendered_scenes_count": 1}

        def mock_evidence(p, task_id=None):
            project.render_jobs.append(
                RenderJob(id="J_DOC", scene_id="S003", kind="document", status=JobStatus.ready, output=str(dummy_ev_mp4))
            )
            save_project_spec(project, t_dir / "project.evidence.json")
            return {"status": "complete", "rendered_scenes_count": 1}

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_broll_acquisition", side_effect=mock_broll), \
             patch("app.services.scene_orchestrator.run_motion_render", side_effect=mock_motion), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", side_effect=mock_evidence), \
             patch("app.services.scene_orchestrator.validate_rendered_motion_clip"), \
             patch("app.services.scene_orchestrator.validate_rendered_evidence_clip"):

            res = run_all_project(project, task_id=task_id)

        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["ready_scenes"], 2)
        self.assertEqual(res["failed_scenes"], 1)

    def test_optional_document_text_fallback_with_highlight_target(self) -> None:
        doc_cue = VisualCue(
            id="S003",
            order=1,
            visual_type=VisualType.document,
            purpose=VisualPurpose.evidence,
            start=0.0,
            end=3.0,
            narration="Social Security retirement information.",
            payload={
                "search_query": "Social Security retirement rules",
                "source_hint": "SSA rules",
                "evidence_required": False,
                "highlight_target": "Full Retirement Age: 67",
            },
        )
        project = self._create_mock_project(cues=[doc_cue])
        task_id = "test-fallback-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        # Evidence runner returns skipped
        def mock_evidence(p, task_id=None):
            project.render_jobs = [
                RenderJob(
                    id="J_DOC_SKIP",
                    scene_id="S003",
                    kind="document",
                    status=JobStatus.failed,
                    output="skipped",
                    error="Optional evidence not found",
                    metadata={"fallback_recommendation": "text"},
                )
            ]
            save_project_spec(project, t_dir / "project.evidence.json")
            return {"status": "complete", "skipped_scenes_count": 1}

        dummy_text_mp4 = t_dir / "motion" / "S003_TEXT.mp4"
        dummy_text_mp4.parent.mkdir(parents=True, exist_ok=True)
        dummy_text_mp4.write_bytes(b"\x00" * 512)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", side_effect=mock_evidence), \
             patch("app.services.scene_orchestrator.render_scene_motion") as mock_remotion, \
             patch("app.services.scene_orchestrator.validate_rendered_motion_clip"):

            mock_remotion.return_value = MagicMock(
                output_file=str(dummy_text_mp4),
                duration_frames=90,
                fps=30,
                metadata={"spec_fingerprint": "fp123"},
            )

            res = run_all_project(project, task_id=task_id)

        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["ready_scenes"], 1)

        # Check execution manifest
        exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        scene_rec = exec_manifest_data["scenes"][0]
        self.assertEqual(scene_rec["planned_visual_type"], "document")
        self.assertEqual(scene_rec["resolved_visual_type"], "text")
        self.assertEqual(scene_rec["fallback_from"], "document")
        self.assertEqual(scene_rec["status"], "ready")

    def test_required_document_failure_never_falls_back(self) -> None:
        doc_cue = VisualCue(
            id="S003",
            order=1,
            visual_type=VisualType.document,
            purpose=VisualPurpose.evidence,
            start=0.0,
            end=3.0,
            narration="Social Security retirement information.",
            payload={
                "search_query": "Social Security retirement rules",
                "source_hint": "SSA rules",
                "evidence_required": True,
                "highlight_target": "Full Retirement Age: 67",
            },
        )
        project = self._create_mock_project(cues=[doc_cue])
        task_id = "test-req-doc-fail"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        def mock_evidence(p, task_id=None):
            project.render_jobs = [
                RenderJob(
                    id="J_DOC_FAIL",
                    scene_id="S003",
                    kind="document",
                    status=JobStatus.failed,
                    output=None,
                    error="Required evidence acquisition failed",
                )
            ]
            save_project_spec(project, t_dir / "project.evidence.json")
            return {"status": "failed", "failed_scenes_count": 1}

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", side_effect=mock_evidence), \
             patch("app.services.scene_orchestrator.render_scene_motion") as mock_remotion:

            res = run_all_project(project, task_id=task_id)

            mock_remotion.assert_not_called()

        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["failed_scenes"], 1)

        exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        scene_rec = exec_manifest_data["scenes"][0]
        self.assertEqual(scene_rec["planned_visual_type"], "document")
        self.assertEqual(scene_rec["resolved_visual_type"], "document")
        self.assertIsNone(scene_rec["fallback_from"])
        self.assertEqual(scene_rec["status"], "failed")

    def test_scene_ordering_canonical(self) -> None:
        cues_out_of_order = [
            VisualCue(id="S003", order=3, visual_type=VisualType.text, purpose=VisualPurpose.emphasis, start=6.0, end=9.0, narration="Three", payload={"headline": "Three"}),
            VisualCue(id="S001", order=1, visual_type=VisualType.text, purpose=VisualPurpose.emphasis, start=0.0, end=3.0, narration="One", payload={"headline": "One"}),
            VisualCue(id="S002", order=2, visual_type=VisualType.text, purpose=VisualPurpose.emphasis, start=3.0, end=6.0, narration="Two", payload={"headline": "Two"}),
        ]
        project = self._create_mock_project(cues=cues_out_of_order)
        task_id = "test-order-canonical"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        (t_dir / "motion").mkdir(parents=True, exist_ok=True)
        for cid in ("S001", "S002", "S003"):
            f = t_dir / "motion" / f"{cid}_TEXT.mp4"
            f.write_bytes(b"\x00" * 512)
            project.render_jobs.append(
                RenderJob(id=f"J_{cid}", scene_id=cid, kind="motion", status=JobStatus.ready, output=str(f))
            )
        save_project_spec(project, t_dir / "project.motion.json")

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete"}), \
             patch("app.services.scene_orchestrator.validate_rendered_motion_clip"):

            res = run_all_project(project, task_id=task_id)

        self.assertEqual(res["status"], "complete")
        exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        scene_ids = [s["scene_id"] for s in exec_manifest_data["scenes"]]
        self.assertEqual(scene_ids, ["S001", "S002", "S003"])

    def test_missing_output_cannot_be_ready(self) -> None:
        cues = [
            VisualCue(id="S001", order=1, visual_type=VisualType.text, purpose=VisualPurpose.emphasis, start=0.0, end=3.0, narration="One", payload={"headline": "One"}),
        ]
        project = self._create_mock_project(cues=cues)
        task_id = "test-missing-output"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        # Job claims ready but file does not exist
        project.render_jobs = [
            RenderJob(id="J_S001", scene_id="S001", kind="motion", status=JobStatus.ready, output=str(t_dir / "motion" / "non_existent.mp4"))
        ]
        save_project_spec(project, t_dir / "project.motion.json")

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete"}):

            res = run_all_project(project, task_id=task_id)

        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["failed_scenes"], 1)
        exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(exec_manifest_data["scenes"][0]["status"], "failed")

    def test_zero_type_cues_handled_cleanly(self) -> None:
        # Project with only DATA cues (zero BROLL, zero DOCUMENT)
        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=3.0,
                narration="One",
                payload={"template": "number", "headline": "One", "data": {"primary_value": "100"}},
            ),
        ]
        project = self._create_mock_project(cues=cues)
        task_id = "test-zero-types"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        dummy_mp4 = t_dir / "motion" / "S001_DATA.mp4"
        dummy_mp4.parent.mkdir(parents=True, exist_ok=True)
        dummy_mp4.write_bytes(b"\x00" * 512)

        def mock_motion(p, task_id=None):
            project.render_jobs = [
                RenderJob(id="J_S001", scene_id="S001", kind="motion", status=JobStatus.ready, output=str(dummy_mp4))
            ]
            save_project_spec(project, t_dir / "project.motion.json")
            return {"status": "complete", "rendered_scenes_count": 1}

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_broll_acquisition") as mock_broll, \
             patch("app.services.scene_orchestrator.run_motion_render", side_effect=mock_motion), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition") as mock_evidence, \
             patch("app.services.scene_orchestrator.validate_rendered_motion_clip"):

            res = run_all_project(project, task_id=task_id)

            mock_broll.assert_not_called()
            mock_evidence.assert_not_called()

        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["ready_scenes"], 1)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_broll_acquisition") as mock_broll, \
             patch("app.services.scene_orchestrator.run_motion_render", side_effect=mock_motion), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition") as mock_evidence, \
             patch("app.services.scene_orchestrator.validate_rendered_motion_clip"):

            res = run_all_project(project, task_id=task_id)

            mock_broll.assert_not_called()
            mock_evidence.assert_not_called()

        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["ready_scenes"], 1)


if __name__ == "__main__":
    unittest.main()
