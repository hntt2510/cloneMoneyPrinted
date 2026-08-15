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
from app.services.project_spec import load_project_spec, save_project_spec
from app.services.scene_orchestrator import (
    compute_project_input_fingerprint,
    resolve_final_render_job,
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
        narration_mode: NarrationMode = NarrationMode.file,
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

        if narration_mode == NarrationMode.tts:
            narration_dict = {
                "mode": "tts",
                "voice_name": "en-US-JennyNeural",
                "file": None,
                "timing_file": None,
            }
        else:
            narration_dict = {
                "mode": "file",
                "file": str(dummy_audio),
                "timing_file": str(dummy_timing),
            }

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
            narration=narration_dict,
        )

    def _setup_mock_planning_artifacts(
        self,
        project: ProjectSpec,
        task_directory: Path,
        set_ownership: bool = True,
    ) -> None:
        task_directory.mkdir(parents=True, exist_ok=True)
        save_project_spec(project, task_directory / "project.planned.json")

        v_cues = [c.model_dump(mode="json") for c in project.visual_cues]
        (task_directory / "visual_plan.json").write_text(
            json.dumps({"schema_version": "1.0", "project_title": project.project.title, "cues": v_cues}),
            encoding="utf-8",
        )

        t_cues = [c.model_dump(mode="json") for c in project.timeline_cues]
        dummy_audio = task_directory / "narration_runtime.mp3"
        dummy_audio.write_bytes(b"\x00" * 1024)
        dummy_timing = task_directory / "timing_runtime.json"
        dummy_timing.write_text(json.dumps({"segments": []}), encoding="utf-8")

        (task_directory / "timeline.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "project_title": project.project.title,
                "audio_file": str(dummy_audio.resolve()),
                "timing_file": str(dummy_timing.resolve()),
                "duration": 9.0,
                "cues": t_cues,
            }),
            encoding="utf-8",
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

        if set_ownership:
            fp = compute_project_input_fingerprint(project)
            state_data = {
                "schema_version": "1.0",
                "task_id": task_directory.name,
                "source_project_fingerprint": fp,
                "source_project_file": str(task_directory / "project.json"),
                "created_at": now,
                "updated_at": now,
            }
            (task_directory / "orchestrator_state.json").write_text(
                json.dumps(state_data, indent=2), encoding="utf-8"
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
            return {"status": "complete", "ready_count": 1, "failed_count": 0}

        def mock_motion(p, task_id=None):
            call_order.append(("motion", task_id))
            return {"status": "complete", "motion_count": 1, "failed_count": 0}

        def mock_evidence(p, task_id=None):
            call_order.append(("evidence", task_id))
            return {"status": "complete", "evidence_count": 1, "failed_count": 0, "skipped_count": 0}

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
             patch("app.services.scene_orchestrator.run_broll_acquisition", return_value={"status": "complete", "ready_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete", "motion_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", return_value={"status": "complete", "evidence_count": 0, "failed_count": 0, "skipped_count": 0}):

            run_all_project(project, task_id=task_id)
            mock_plan.assert_not_called()

            # Check execution manifest planning stage metadata
            exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
            planning_stage = next(s for s in exec_manifest_data["stages"] if s["name"] == "planning")
            self.assertTrue(planning_stage["metadata"].get("reused"))

    def test_planning_reused_tts_mode(self) -> None:
        """Requirement 5: TTS mode project with valid timeline.json and runtime audio reuses planning."""
        project = self._create_mock_project(narration_mode=NarrationMode.tts)
        self.assertIsNone(project.narration.file)

        task_id = "test-tts-reuse-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir, set_ownership=True)

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_project_plan") as mock_plan, \
             patch("app.services.scene_orchestrator.run_broll_acquisition", return_value={"status": "complete", "ready_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete", "motion_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", return_value={"status": "complete", "evidence_count": 0, "failed_count": 0, "skipped_count": 0}):

            run_all_project(project, task_id=task_id)
            mock_plan.assert_not_called()

            exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
            planning_stage = next(s for s in exec_manifest_data["stages"] if s["name"] == "planning")
            self.assertTrue(planning_stage["metadata"].get("reused"))

    def test_stale_unowned_plan_not_reused(self) -> None:
        """Requirement 6 & 7: Stale planning artifacts without ownership metadata are not reused; planning runs."""
        project = self._create_mock_project()
        task_id = "test-unowned-stale-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        # Setup artifacts WITHOUT ownership metadata
        self._setup_mock_planning_artifacts(project, t_dir, set_ownership=False)

        plan_called = []
        def mock_plan(p, task_id=None):
            plan_called.append(task_id)
            return {"status": "complete"}

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_project_plan", side_effect=mock_plan), \
             patch("app.services.scene_orchestrator.run_broll_acquisition", return_value={"status": "complete", "ready_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete", "motion_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", return_value={"status": "complete", "evidence_count": 0, "failed_count": 0, "skipped_count": 0}):

            run_all_project(project, task_id=task_id)
            self.assertEqual(len(plan_called), 1)

    def test_interrupted_g08_resume_and_mismatch(self) -> None:
        """Requirement 8: Interrupted run with ownership record reuses planning on same project, fails on different."""
        project_a = self._create_mock_project(title="Project A")
        project_b = self._create_mock_project(title="Project B")
        task_id = "test-interrupted-resume"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project_a, t_dir, set_ownership=True)

        # Same project A rerun reuses planning
        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_project_plan") as mock_plan, \
             patch("app.services.scene_orchestrator.run_broll_acquisition", return_value={"status": "complete", "ready_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete", "motion_count": 0, "failed_count": 0}), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", return_value={"status": "complete", "evidence_count": 0, "failed_count": 0, "skipped_count": 0}):

            run_all_project(project_a, task_id=task_id)
            mock_plan.assert_not_called()

        # Different project B rerun on same task fails with fingerprint mismatch
        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)):
            with self.assertRaises(ProjectRunError) as cm:
                run_all_project(project_b, task_id=task_id)
            self.assertIn("fingerprint mismatch", str(cm.exception))

    def test_real_runner_contract_recordings(self) -> None:
        """Requirement 9 & 10: Verify exact runner return dictionaries are recorded in StageExecutionRecord."""
        project = self._create_mock_project()
        task_id = "test-contract-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        def mock_broll(p, task_id=None):
            return {
                "status": "complete",
                "ready_count": 2,
                "failed_count": 1,
                "broll_manifest_file": str(t_dir / "broll_manifest.json"),
                "assets_project_file": str(t_dir / "project.assets.json"),
            }

        def mock_motion(p, task_id=None):
            return {
                "status": "complete",
                "motion_count": 3,
                "failed_count": 1,
                "manifest": str(t_dir / "motion" / "motion_manifest.json"),
                "project_motion": str(t_dir / "project.motion.json"),
            }

        def mock_evidence(p, task_id=None):
            return {
                "status": "complete",
                "evidence_count": 4,
                "failed_count": 1,
                "skipped_count": 2,
                "manifest": str(t_dir / "evidence" / "evidence_manifest.json"),
                "project_evidence": str(t_dir / "project.evidence.json"),
            }

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_broll_acquisition", side_effect=mock_broll), \
             patch("app.services.scene_orchestrator.run_motion_render", side_effect=mock_motion), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", side_effect=mock_evidence):

            run_all_project(project, task_id=task_id)

        manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        stage_map = {s["name"]: s for s in manifest_data["stages"]}

        self.assertEqual(stage_map["broll"]["ready_count"], 2)
        self.assertEqual(stage_map["broll"]["failed_count"], 1)

        self.assertEqual(stage_map["motion"]["ready_count"], 3)
        self.assertEqual(stage_map["motion"]["failed_count"], 1)

        self.assertEqual(stage_map["evidence"]["ready_count"], 4)
        self.assertEqual(stage_map["evidence"]["failed_count"], 1)
        self.assertEqual(stage_map["evidence"]["skipped_count"], 2)

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
            return {"status": "failed", "error": "B-roll provider rate limit", "ready_count": 0, "failed_count": 1}

        def mock_motion(p, task_id=None):
            project.render_jobs.append(
                RenderJob(id="J_DATA", scene_id="S002", kind="motion", status=JobStatus.ready, output=str(dummy_motion_mp4))
            )
            save_project_spec(project, t_dir / "project.motion.json")
            return {"status": "complete", "motion_count": 1, "failed_count": 0}

        def mock_evidence(p, task_id=None):
            project.render_jobs.append(
                RenderJob(id="J_DOC", scene_id="S003", kind="document", status=JobStatus.ready, output=str(dummy_ev_mp4))
            )
            save_project_spec(project, t_dir / "project.evidence.json")
            return {"status": "complete", "evidence_count": 1, "failed_count": 0, "skipped_count": 0}

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

    def test_optional_document_text_fallback_preserves_provenance(self) -> None:
        """Requirement 11, 12, 13, 14: Fallback preserves original DOCUMENT RenderJob and appends RF003."""
        doc_cue = VisualCue(
            id="S003",
            order=3,
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
        task_id = "test-fallback-preservation-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        # Evidence runner returns skipped and sets original DOCUMENT job R003
        def mock_evidence(p, task_id=None):
            project.render_jobs = [
                RenderJob(
                    id="R003",
                    scene_id="S003",
                    kind="document",
                    status=JobStatus.failed,
                    output="skipped",
                    error="Optional evidence not found in registry",
                    metadata={"fallback_recommendation": "text"},
                )
            ]
            save_project_spec(project, t_dir / "project.evidence.json")
            return {"status": "complete", "evidence_count": 0, "failed_count": 0, "skipped_count": 1}

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

        # 1. Verify project.executed.json contains BOTH R003 and RF003
        executed_project = load_project_spec(t_dir / "project.executed.json")
        job_ids = [j.id for j in executed_project.render_jobs if j.scene_id == "S003"]
        self.assertIn("R003", job_ids)
        self.assertIn("RF003", job_ids)

        # 2. Verify RF003 has fallback metadata referencing R003
        rf_job = next(j for j in executed_project.render_jobs if j.id == "RF003")
        self.assertEqual(rf_job.metadata.get("fallback_from"), "document")
        self.assertEqual(rf_job.metadata.get("original_document_render_job_id"), "R003")
        self.assertEqual(rf_job.metadata.get("original_document_render_job_status"), "failed")
        self.assertEqual(rf_job.metadata.get("original_document_error"), "Optional evidence not found in registry")

        # 3. Check execution manifest
        exec_manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        scene_rec = exec_manifest_data["scenes"][0]
        self.assertEqual(scene_rec["planned_visual_type"], "document")
        self.assertEqual(scene_rec["resolved_visual_type"], "text")
        self.assertEqual(scene_rec["render_job_id"], "RF003")
        self.assertEqual(scene_rec["fallback_from"], "document")
        self.assertEqual(scene_rec["status"], "ready")

        # 4. Check project_manifest.json is complete with cleared stage_errors
        p_manifest_data = json.loads((t_dir / "project_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(p_manifest_data["status"], "complete")
        self.assertIsNone(p_manifest_data.get("error"))
        self.assertEqual(p_manifest_data["outputs"]["stage_errors"], {})

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
            return {"status": "failed", "evidence_count": 0, "failed_count": 1, "skipped_count": 0}

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

    def test_progress_persistence_and_interrupted_snapshot(self) -> None:
        """Requirement 15, 16, 17: Manifest snapshots persisted after each stage and observable on interruption."""
        project = self._create_mock_project()
        task_id = "test-progress-snapshot-task"
        t_dir = Path(self.temp_dir) / "tasks" / task_id
        self._setup_mock_planning_artifacts(project, t_dir)

        def mock_broll(p, task_id=None):
            # Check manifest snapshot exists on disk with progress >= 45
            manifest_data = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
            self.assertGreaterEqual(manifest_data["progress_percent"], 25)
            return {"status": "complete", "ready_count": 1, "failed_count": 0}

        def mock_motion_fail(p, task_id=None):
            # Simulate hard exception during motion
            raise RuntimeError("Out of GPU memory during motion render")

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(t_dir)), \
             patch("app.services.scene_orchestrator.run_broll_acquisition", side_effect=mock_broll), \
             patch("app.services.scene_orchestrator.run_motion_render", side_effect=mock_motion_fail), \
             patch("app.services.scene_orchestrator.run_evidence_acquisition", return_value={"status": "complete", "evidence_count": 0, "failed_count": 0, "skipped_count": 0}):

            res = run_all_project(project, task_id=task_id)

        manifest_on_disk = json.loads((t_dir / "execution_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("preflight", [s["name"] for s in manifest_on_disk["stages"]])
        self.assertIn("planning", [s["name"] for s in manifest_on_disk["stages"]])
        self.assertIn("broll", [s["name"] for s in manifest_on_disk["stages"]])
        self.assertIn("motion", [s["name"] for s in manifest_on_disk["stages"]])
        self.assertGreaterEqual(manifest_on_disk["progress_percent"], 65)

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
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete", "motion_count": 3, "failed_count": 0}), \
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
             patch("app.services.scene_orchestrator.run_motion_render", return_value={"status": "complete", "motion_count": 1, "failed_count": 0}):

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
            return {"status": "complete", "motion_count": 1, "failed_count": 0}

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
