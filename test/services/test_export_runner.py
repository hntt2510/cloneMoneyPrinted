from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.models.evidence import (
    EvidenceBBox,
    EvidenceSource,
    EvidenceSourceKind,
    EvidenceSourceRegistry,
    EvidenceSourceTrust,
)
from app.models.execution import ExecutionManifest, ExecutionStageStatus
from app.models.export import EditManifest, EditorPackageStatus
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
    TimelinePlan,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.evidence_sources import compute_file_sha256
from app.services.export_runner import (
    convert_timing_to_srt,
    copy_file_verified,
    export_editor_package,
    format_seconds_to_srt_time,
    generate_readme_edit,
    slugify_project_title,
)
from app.services.project_spec import save_project_spec
from app.services.scene_orchestrator import compute_project_input_fingerprint


class TestExportRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.task_id = "test-export-task-001"
        self.task_dir = Path(self.temp_dir) / "tasks" / self.task_id
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = Path(self.temp_dir) / "exports" / "custom-export"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _setup_workspace_fixture(
        self,
        title: str = "Retirement Guide: 2026 Edition!",
        include_narration: bool = True,
        include_subtitles: bool = True,
        fallback_scene: bool = True,
        missing_scenes: bool = False,
    ) -> tuple[ProjectSpec, Path]:
        cues = [
            VisualCue(
                id="S001",
                order=1,
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                start=0.0,
                end=3.0,
                narration="Planning for retirement requires diligence.",
                payload={"search_query": "senior couple financial planning"},
            ),
            VisualCue(
                id="S002",
                order=2,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=3.0,
                end=6.0,
                narration="Full retirement age is sixty-seven.",
                payload={"template": "number", "headline": "Retirement Age", "data": {"primary_value": "67", "label": "Age"}},
            ),
            VisualCue(
                id="S003",
                order=3,
                visual_type=VisualType.document,
                purpose=VisualPurpose.evidence,
                start=6.0,
                end=9.0,
                narration="Section 402 establishes retirement rules.",
                payload={
                    "search_query": "Section 402 retirement",
                    "source_hint": "Federal Board",
                    "evidence_required": False,
                    "highlight_target": "Section 402: Normal retirement age is 67.",
                    "source_ids": ["SRC_DOC_001"],
                },
            ),
        ]

        timeline_cues = [
            TimelineCue(id=c.id, order=c.order, start=c.start, end=c.end, narration=c.narration)
            for c in cues
        ]

        dummy_audio = self.task_dir / "narration.mp3"
        if include_narration:
            dummy_audio.write_bytes(b"\x00" * 2048)

        dummy_timing = self.task_dir / "timing.json"
        if include_subtitles:
            timing_data = {
                "segments": [
                    {"start": 0.0, "end": 3.0, "text": "Planning for retirement requires diligence."},
                    {"start": 3.0, "end": 6.0, "text": "Full retirement age is sixty-seven."},
                    {"start": 6.0, "end": 9.0, "text": "Section 402 establishes retirement rules."},
                ]
            }
            dummy_timing.write_text(json.dumps(timing_data, indent=2), encoding="utf-8")

        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(
                title=title,
                language="en-US",
                aspect_ratio=VideoAspect.landscape,
                fps=30,
            ),
            script=ScriptSpec(
                subject="Retirement Guide",
                script="Planning for retirement requires diligence. Full retirement age is sixty-seven. Section 402 establishes retirement rules.",
                search_terms=["retirement", "planning"],
            ),
            timeline_cues=timeline_cues,
            visual_cues=cues,
            narration={
                "file": str(dummy_audio) if include_narration else None,
                "timing_file": str(dummy_timing) if include_subtitles else None,
            },
        )

        project_path = self.task_dir / "project.json"
        save_project_spec(project, project_path)

        # Create dummy media files
        broll_dir = self.task_dir / "broll" / "S001"
        broll_dir.mkdir(parents=True, exist_ok=True)
        s001_mp4 = broll_dir / "rendered.mp4"
        s001_mp4.write_bytes(b"\x01\x02\x03\x04" * 256)

        motion_dir = self.task_dir / "motion"
        motion_dir.mkdir(parents=True, exist_ok=True)
        s002_mp4 = motion_dir / "S002_DATA.mp4"
        s002_mp4.write_bytes(b"\x05\x06\x07\x08" * 256)

        if fallback_scene:
            s003_mp4 = motion_dir / "S003_TEXT.mp4"
            if not missing_scenes:
                s003_mp4.write_bytes(b"\x09\x0A\x0B\x0C" * 256)
        else:
            ev_dir = self.task_dir / "evidence"
            ev_dir.mkdir(parents=True, exist_ok=True)
            s003_mp4 = ev_dir / "S003_DOCUMENT.mp4"
            if not missing_scenes:
                s003_mp4.write_bytes(b"\x0D\x0E\x0F\x10" * 256)

        # Asset and Render Jobs
        project.asset_jobs = [
            AssetJob(
                id="J_BROLL_01",
                scene_id="S001",
                kind="broll",
                status=JobStatus.ready,
                output=str(s001_mp4),
                metadata={
                    "query": "senior couple financial planning",
                    "provider": "pexels",
                    "asset_url": "https://example.com/video.mp4?token=secret123&api_key=priv456",
                },
            )
        ]

        if fallback_scene:
            project.render_jobs = [
                RenderJob(id="J_DATA_02", scene_id="S002", kind="motion", status=JobStatus.ready, output=str(s002_mp4)),
                RenderJob(id="R003", scene_id="S003", kind="document", status=JobStatus.failed, output="skipped", error="Document evidence not found"),
                RenderJob(
                    id="RF003",
                    scene_id="S003",
                    kind="text_fallback",
                    status=JobStatus.ready if not missing_scenes else JobStatus.failed,
                    output=str(s003_mp4) if not missing_scenes else None,
                    metadata={
                        "fallback_from": "document",
                        "fallback_reason": "optional evidence unavailable",
                        "original_document_render_job_id": "R003",
                    },
                ),
            ]
        else:
            project.render_jobs = [
                RenderJob(id="J_DATA_02", scene_id="S002", kind="motion", status=JobStatus.ready, output=str(s002_mp4)),
                RenderJob(
                    id="R003",
                    scene_id="S003",
                    kind="document",
                    status=JobStatus.ready if not missing_scenes else JobStatus.failed,
                    output=str(s003_mp4) if not missing_scenes else None,
                    metadata={"selected_source_id": "SRC_DOC_001", "source_title": "Federal Board Report", "page_number": 1},
                ),
            ]

        save_project_spec(project, self.task_dir / "project.executed.json")

        # Sources.json
        sources_reg = EvidenceSourceRegistry(
            sources=[
                EvidenceSource(
                    id="SRC_DOC_001",
                    kind=EvidenceSourceKind.pdf,
                    title="Federal Board Report",
                    publisher="Federal Retirement Board",
                    trust=EvidenceSourceTrust.official,
                    url="https://gov.example.com/report.pdf?sig=secret789",
                )
            ]
        )
        (self.task_dir / "sources.json").write_text(
            json.dumps(sources_reg.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        # Timeline plan
        t_plan = TimelinePlan(
            schema_version="1.0",
            project_title=title,
            audio_file=str(dummy_audio.resolve()) if include_narration else "",
            timing_file=str(dummy_timing.resolve()) if include_subtitles else "",
            duration=9.0,
            cues=timeline_cues,
        )
        (self.task_dir / "timeline.json").write_text(
            json.dumps(t_plan.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        return project, project_path

    def test_slugify_project_title(self) -> None:
        self.assertEqual(slugify_project_title("Retirement Guide: 2026 Edition!"), "retirement-guide-2026-edition")
        self.assertEqual(slugify_project_title("  --Special *** Title??--  "), "special-title")
        self.assertEqual(slugify_project_title(""), "untitled-project")

    def test_format_seconds_to_srt_time(self) -> None:
        self.assertEqual(format_seconds_to_srt_time(0.0), "00:00:00,000")
        self.assertEqual(format_seconds_to_srt_time(65.432), "00:01:05,432")
        self.assertEqual(format_seconds_to_srt_time(3661.05), "01:01:01,050")

    def test_convert_timing_to_srt(self) -> None:
        timing_file = self.task_dir / "sample_timing.json"
        timing_file.write_text(
            json.dumps([
                {"start": 0.0, "end": 2.5, "text": "First subtitle segment."},
                {"start": 2.5, "end": 5.0, "text": "Second subtitle segment."},
            ]),
            encoding="utf-8",
        )
        dest_srt = self.task_dir / "output.srt"
        success = convert_timing_to_srt(timing_file, dest_srt)
        self.assertTrue(success)
        self.assertTrue(dest_srt.exists())
        srt_content = dest_srt.read_text(encoding="utf-8")
        self.assertIn("1\n00:00:00,000 --> 00:00:02,500\nFirst subtitle segment.", srt_content)
        self.assertIn("2\n00:00:02,500 --> 00:00:05,000\nSecond subtitle segment.", srt_content)

    def test_complete_editor_package_export(self) -> None:
        project, project_path = self._setup_workspace_fixture(title="Complete Project Guide")

        with patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)), patch(
            "app.services.export_runner.probe_media_frames", return_value=90
        ):
            result = export_editor_package(project_path, task_id=self.task_id, output_dir=self.output_dir)

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.ready_scene_count, 3)
        self.assertEqual(result.missing_scene_count, 0)
        self.assertIsNone(result.error)

        # 1. Check directory structure
        export_root = Path(result.export_dir)
        self.assertTrue((export_root / "project.json").exists())
        self.assertTrue((export_root / "project.executed.json").exists())
        self.assertTrue((export_root / "edit_manifest.json").exists())
        self.assertTrue((export_root / "README_EDIT.md").exists())
        self.assertTrue((export_root / "narration" / "narration.mp3").exists())
        self.assertTrue((export_root / "narration" / "subtitle.srt").exists())
        self.assertTrue((export_root / "scenes" / "S001_BROLL.mp4").exists())
        self.assertTrue((export_root / "scenes" / "S002_DATA.mp4").exists())
        self.assertTrue((export_root / "scenes" / "S003_TEXT.mp4").exists())
        self.assertTrue((export_root / "sources" / "source_manifest.json").exists())

        # Assert no final.mp4 created
        self.assertFalse((export_root / "final.mp4").exists())

        # 2. Check edit_manifest.json
        manifest_data = json.loads((export_root / "edit_manifest.json").read_text(encoding="utf-8"))
        edit_manifest = EditManifest.model_validate(manifest_data)
        self.assertEqual(edit_manifest.package_status, EditorPackageStatus.complete)
        self.assertEqual(len(edit_manifest.scenes), 3)
        self.assertEqual(edit_manifest.fps, 30)
        self.assertEqual(edit_manifest.resolution, [1920, 1080])
        self.assertIsNotNone(edit_manifest.narration_sha256)
        self.assertIsNotNone(edit_manifest.subtitle_sha256)

        # 3. Check fallback provenance in manifest
        s003_entry = next(s for s in edit_manifest.scenes if s.scene_id == "S003")
        self.assertEqual(s003_entry.planned_visual_type, VisualType.document)
        self.assertEqual(s003_entry.resolved_visual_type, VisualType.text)
        self.assertEqual(s003_entry.fallback_from, VisualType.document)
        self.assertEqual(s003_entry.source_stage, "fallback")
        self.assertIn("S003_TEXT.mp4", s003_entry.exported_file or "")

        # 4. Check sanitized secrets in source manifest
        src_manifest_text = (export_root / "sources" / "source_manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("secret123", src_manifest_text)
        self.assertNotIn("priv456", src_manifest_text)
        self.assertNotIn("secret789", src_manifest_text)

        # 5. Check no symlinks by default
        for f in (
            export_root / "narration" / "narration.mp3",
            export_root / "scenes" / "S001_BROLL.mp4",
            export_root / "scenes" / "S002_DATA.mp4",
            export_root / "scenes" / "S003_TEXT.mp4",
        ):
            self.assertTrue(f.is_file())
            self.assertFalse(f.is_symlink())

    def test_partial_package_export(self) -> None:
        project, project_path = self._setup_workspace_fixture(
            title="Partial Project Guide",
            missing_scenes=True,
        )

        with patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)):
            result = export_editor_package(project_path, task_id=self.task_id, output_dir=self.output_dir)

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.ready_scene_count, 2)
        self.assertEqual(result.missing_scene_count, 1)

        manifest_data = json.loads((Path(result.export_dir) / "edit_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest_data["package_status"], "partial")
        self.assertEqual(manifest_data["missing_scenes"], ["S003"])

    def test_missing_subtitle_honest_handling(self) -> None:
        project, project_path = self._setup_workspace_fixture(
            title="No Subtitle Project",
            include_subtitles=False,
        )

        with patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)):
            result = export_editor_package(project_path, task_id=self.task_id, output_dir=self.output_dir)

        manifest_data = json.loads((Path(result.export_dir) / "edit_manifest.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest_data["subtitle_file"])
        self.assertIsNone(manifest_data["subtitle_sha256"])
        self.assertIsNotNone(manifest_data["missing_subtitle_reason"])
        self.assertIn("No subtitle", manifest_data["missing_subtitle_reason"])

    def test_repeat_export_reuse_and_invalidation(self) -> None:
        project, project_path = self._setup_workspace_fixture(title="Reused Export Project")

        with patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)), patch(
            "app.services.export_runner.probe_media_frames", return_value=90
        ):
            res1 = export_editor_package(project_path, task_id=self.task_id, output_dir=self.output_dir)

        manifest_file = Path(res1.edit_manifest_file)
        mtime1 = manifest_file.stat().st_mtime_ns

        # Second export with unchanged assets
        with patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)), patch(
            "app.services.export_runner.probe_media_frames", return_value=90
        ):
            res2 = export_editor_package(project_path, task_id=self.task_id, output_dir=self.output_dir)

        self.assertEqual(res1.status, res2.status)

        # Modify one scene asset in workspace
        s002_mp4 = self.task_dir / "motion" / "S002_DATA.mp4"
        s002_mp4.write_bytes(b"\xFF\xEE\xDD\xCC" * 512)

        # Third export invalidates and updates only changed scene
        with patch("app.services.export_runner.utils.task_dir", return_value=str(self.task_dir)), patch(
            "app.services.export_runner.probe_media_frames", return_value=90
        ):
            res3 = export_editor_package(project_path, task_id=self.task_id, output_dir=self.output_dir)

        self.assertEqual(res3.status, "complete")
        dest_s002 = Path(res3.export_dir) / "scenes" / "S002_DATA.mp4"
        self.assertEqual(compute_file_sha256(dest_s002), compute_file_sha256(s002_mp4))


if __name__ == "__main__":
    unittest.main()
