from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import unittest
import wave
import struct
from pathlib import Path
from unittest.mock import patch

from loguru import logger

from app.models.project import (
    DataPayload,
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
from app.services.project_spec import save_project_spec
from app.services.scene_orchestrator import (
    compute_project_input_fingerprint,
    run_all_project,
)


class TestLoggingAudit(unittest.TestCase):
    """G12.9 Logging Audit Tests.

    Validates that structured logs contain required traceability metadata (task_id,
    stage name, scene_id, timing/duration) and do NOT leak credential or secret patterns.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "logging-audit-task-001"
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)

        self.log_stream = io.StringIO()
        self.sink_id = logger.add(self.log_stream, level="DEBUG", format="{message}")

    def tearDown(self) -> None:
        logger.remove(self.sink_id)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_mock_project(self) -> Path:
        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=1.0,
                narration="Data cue scene.",
                payload={"template": "number", "headline": "LOGGING", "data": {"val": "100"}},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.text,
                purpose=VisualPurpose.emphasis,
                start=1.0,
                end=2.0,
                narration="Text cue scene.",
                payload={"headline": "LOGGING TEST", "subheadline": "Audit"},
            ),
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
            wf.writeframes(bytearray(44100 * 2))

        dummy_timing = self.task_dir / "timing.json"
        dummy_timing.write_text(json.dumps({"segments": []}), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title="Logging Audit Project",
                language="en-US",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Logging Audit",
                script="Data cue scene. Text cue scene.",
                search_terms=["audit"],
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
                "duration": 2.0,
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

        return project_path

    def _run_mock_pipeline(self) -> str:
        project_path = self._setup_mock_project()

        with patch("app.services.scene_orchestrator.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.motion_runner_loader.utils.task_dir", return_value=str(self.task_dir)), \
             patch("app.services.evidence_runner.utils.task_dir", return_value=str(self.task_dir)):

            res = run_all_project(project_path, task_id=self.task_id)
            self.assertEqual(res["status"], "complete")

        return self.log_stream.getvalue()

    def test_logs_include_task_id(self) -> None:
        """Requirement 1: Log output for scene_orchestrator run includes task_id."""
        logs = self._run_mock_pipeline()
        self.assertIn(
            self.task_id,
            logs,
            f"Expected task_id '{self.task_id}' in log output",
        )

    def test_logs_include_stage(self) -> None:
        """Requirement 2: Log output includes stage names (planning, motion, evidence)."""
        logs = self._run_mock_pipeline()
        self.assertIn("planning", logs.lower())
        self.assertIn("motion", logs.lower())

    def test_logs_include_scene_id(self) -> None:
        """Requirement 3: Per-scene logs include scene IDs (e.g., S001, S002)."""
        logs = self._run_mock_pipeline()
        self.assertTrue(
            "S001" in logs or "S002" in logs,
            "Expected scene ID (S001 / S002) in log output",
        )

    def test_logs_include_duration(self) -> None:
        """Requirement 4: Execution manifest records stage timing with started_at and completed_at."""
        self._run_mock_pipeline()
        exec_manifest_path = self.task_dir / "execution_manifest.json"
        self.assertTrue(exec_manifest_path.exists())
        exec_data = json.loads(exec_manifest_path.read_text(encoding="utf-8"))

        for stage in exec_data.get("stages", []):
            self.assertIsNotNone(stage.get("started_at"), f"Stage {stage.get('name')} missing started_at")
            self.assertIsNotNone(stage.get("completed_at"), f"Stage {stage.get('name')} missing completed_at")

    def test_logs_no_secrets(self) -> None:
        """Requirement 5: Combined log text from run does not match credential/secret patterns."""
        logs = self._run_mock_pipeline()
        secret_patterns = [
            r"ghp_[A-Za-z0-9_]{20,}",
            r"github_pat_[A-Za-z0-9_]{30,}",
            r"Bearer\s+[A-Za-z0-9_\-\.]{25,}",
            r"(?:api_key|apikey|secret|password)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
        ]
        for pat in secret_patterns:
            matches = re.findall(pat, logs, flags=re.IGNORECASE)
            self.assertEqual(
                matches,
                [],
                f"Found unredacted secret pattern '{pat}' in logs: {matches}",
            )


if __name__ == "__main__":
    unittest.main()
