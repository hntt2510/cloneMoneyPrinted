from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pymupdf

from app.models.evidence import (
    EvidenceSource,
    EvidenceSourceKind,
    EvidenceSourceRegistry,
    EvidenceSourceTrust,
)
from app.models.project import (
    AssetJob,
    DocumentPayload,
    JobStatus,
    NarrationMode,
    NarrationSpec,
    ProductionConfig,
    ProjectManifest,
    ProjectMetadata,
    ProjectSpec,
    ProjectStatus,
    RenderJob,
    ScriptSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.evidence_runner import run_evidence_acquisition
from app.utils import utils


def _create_synthetic_test_pdf(dest_path: Path) -> Path:
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 100), "OFFICIAL EVIDENCE DOCUMENT", fontsize=18)
    p.insert_text((50, 150), "Medicare coverage begins at age 65.", fontsize=14)
    doc.save(str(dest_path))
    doc.close()
    return dest_path


class TestEvidenceRunner(unittest.TestCase):
    def setUp(self):
        self.task_id = utils.get_uuid()
        self.task_dir = Path(utils.task_dir(self.task_id)).resolve()
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_path = self.task_dir / "sample_policy.pdf"
        _create_synthetic_test_pdf(self.pdf_path)

        self.audio_file = self.task_dir / "audio.mp3"
        self.audio_file.write_bytes(b"\x00" * 100)

    def tearDown(self):
        shutil.rmtree(self.task_dir, ignore_errors=True)

    def test_zero_document_cues_succeeds(self):
        project_spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Zero Document Video", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Zero Doc", script="Broll hook."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(self.audio_file)),
            production=ProductionConfig(),
            timeline_cues=[
                TimelineCue(id="S001", order=1, start=0.0, end=2.0, narration="city skyline"),
            ],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    start=0.0,
                    end=2.0,
                    narration="city skyline",
                    payload={"search_query": "city skyline"},
                )
            ],
            asset_jobs=[
                AssetJob(id="A001", scene_id="S001", kind="broll", status=JobStatus.ready, output="broll/S001.mp4")
            ],
            render_jobs=[],
        )
        plan_path = self.task_dir / "project.planned.json"
        plan_path.write_text(json.dumps(project_spec.model_dump(mode="json"), indent=2), encoding="utf-8")
        (self.task_dir / "visual_plan.json").write_text("{}", encoding="utf-8")

        result = run_evidence_acquisition(plan_path, task_id=self.task_id)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["evidence_count"], 0)
        self.assertTrue((self.task_dir / "evidence" / "evidence_manifest.json").exists())

    def test_mixed_project_preserves_existing_jobs_and_renders_document(self):
        sources = [
            EvidenceSource(
                id="SRC_MEDICARE",
                kind=EvidenceSourceKind.pdf,
                local_file="sample_policy.pdf",
                title="Official Medicare Age Rules",
                publisher="SSA",
                trust=EvidenceSourceTrust.official,
                tags=["medicare", "age 65"],
            )
        ]
        registry = EvidenceSourceRegistry(sources=sources)
        (self.task_dir / "sources.json").write_text(json.dumps(registry.model_dump(mode="json"), indent=2), encoding="utf-8")

        project_spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Mixed Evidence Video", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Mixed Evidence", script="Broll. Medicare. Coverage."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(self.audio_file)),
            production=ProductionConfig(),
            timeline_cues=[
                TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Broll scene"),
                TimelineCue(id="S002", order=2, start=1.0, end=2.0, narration="Medicare coverage begins at age 65."),
                TimelineCue(id="S003", order=3, start=2.0, end=3.0, narration="Data scene"),
            ],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.broll,
                    purpose=VisualPurpose.context,
                    start=0.0,
                    end=1.0,
                    narration="Broll scene",
                    payload={"search_query": "city skyline"},
                ),
                VisualCue(
                    id="S002",
                    order=2,
                    visual_type=VisualType.document,
                    purpose=VisualPurpose.evidence,
                    start=1.0,
                    end=2.0,
                    narration="Medicare coverage begins at age 65.",
                    payload={
                        "search_query": "Medicare age 65",
                        "source_hint": "SSA",
                        "highlight_target": "age 65",
                        "source_ids": ["SRC_MEDICARE"],
                    },
                ),
                VisualCue(
                    id="S003",
                    order=3,
                    visual_type=VisualType.data,
                    purpose=VisualPurpose.explain,
                    start=2.0,
                    end=3.0,
                    narration="Data scene",
                    payload={"template": "number", "headline": "Coverage", "data": {"value": 65}},
                ),
            ],
            asset_jobs=[
                AssetJob(id="A001", scene_id="S001", kind="broll", status=JobStatus.ready, output="broll/S001.mp4")
            ],
            render_jobs=[
                RenderJob(id="R003", scene_id="S003", kind="motion", status=JobStatus.ready, output="motion/S003.mp4")
            ],
        )

        motion_path = self.task_dir / "project.motion.json"
        motion_path.write_text(json.dumps(project_spec.model_dump(mode="json"), indent=2), encoding="utf-8")

        result = run_evidence_acquisition(motion_path, task_id=self.task_id)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["evidence_count"], 1)

        # Verify project.evidence.json
        evidence_proj_path = self.task_dir / "project.evidence.json"
        self.assertTrue(evidence_proj_path.exists())
        final_proj = ProjectSpec.model_validate_json(evidence_proj_path.read_text(encoding="utf-8"))

        # Check existing jobs preserved
        asset_map = {j.scene_id: j for j in final_proj.asset_jobs}
        render_map = {j.scene_id: j for j in final_proj.render_jobs}

        self.assertIn("S001", asset_map)
        self.assertEqual(asset_map["S001"].output, "broll/S001.mp4")
        self.assertIn("S003", render_map)
        self.assertEqual(render_map["S003"].output, "motion/S003.mp4")

        # Check new DOCUMENT jobs
        self.assertIn("S002", asset_map)
        self.assertEqual(asset_map["S002"].status, JobStatus.ready)
        self.assertIn("S002", render_map)
        self.assertEqual(render_map["S002"].status, JobStatus.ready)
        self.assertTrue(Path(render_map["S002"].output).exists())

    def test_partial_failure_preserves_success_and_fails_stage(self):
        sources = [
            EvidenceSource(
                id="SRC_VALID",
                kind=EvidenceSourceKind.pdf,
                local_file="sample_policy.pdf",
                title="Official Medicare Age Rules",
                trust=EvidenceSourceTrust.official,
            )
        ]
        registry = EvidenceSourceRegistry(sources=sources)
        (self.task_dir / "sources.json").write_text(json.dumps(registry.model_dump(mode="json"), indent=2), encoding="utf-8")

        project_spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Partial Video", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Partial", script="Part 1. Part 2."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(self.audio_file)),
            production=ProductionConfig(),
            timeline_cues=[
                TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Medicare"),
                TimelineCue(id="S002", order=2, start=1.0, end=2.0, narration="Alien Artifact"),
            ],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.document,
                    purpose=VisualPurpose.evidence,
                    start=0.0,
                    end=1.0,
                    narration="Medicare",
                    payload={"search_query": "Medicare", "source_hint": "SSA", "source_ids": ["SRC_VALID"]},
                ),
                VisualCue(
                    id="S002",
                    order=2,
                    visual_type=VisualType.document,
                    purpose=VisualPurpose.evidence,
                    start=1.0,
                    end=2.0,
                    narration="Alien Artifact",
                    payload={"search_query": "Alien Artifact 999", "source_hint": "Mars", "evidence_required": True, "source_ids": ["SRC_NONEXISTENT"]},
                ),
            ],
        )
        plan_path = self.task_dir / "project.planned.json"
        plan_path.write_text(json.dumps(project_spec.model_dump(mode="json"), indent=2), encoding="utf-8")
        (self.task_dir / "visual_plan.json").write_text("{}", encoding="utf-8")

        result = run_evidence_acquisition(plan_path, task_id=self.task_id)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["evidence_count"], 1)
        self.assertEqual(result["failed_count"], 1)

        # Verify S001 output still exists
        self.assertTrue((self.task_dir / "evidence" / "S001" / "S001_DOCUMENT.mp4").exists())

    def test_allowed_for_evidence_false_never_used_and_diagnostics_recorded(self):
        sources = [
            EvidenceSource(
                id="SRC_DISALLOWED",
                kind=EvidenceSourceKind.pdf,
                local_file="sample_policy.pdf",
                title="Disallowed Evidence Document",
                trust=EvidenceSourceTrust.official,
                allowed_for_evidence=False,
            )
        ]
        registry = EvidenceSourceRegistry(sources=sources)
        (self.task_dir / "sources.json").write_text(json.dumps(registry.model_dump(mode="json"), indent=2), encoding="utf-8")

        project_spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Disallowed Source Video", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Test", script="Doc."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(self.audio_file)),
            production=ProductionConfig(),
            timeline_cues=[TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Medicare")],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.document,
                    purpose=VisualPurpose.evidence,
                    start=0.0,
                    end=1.0,
                    narration="Medicare",
                    payload={"search_query": "Medicare", "source_hint": "SSA", "source_ids": ["SRC_DISALLOWED", "SRC_UNKNOWN"], "evidence_required": True},
                )
            ],
        )
        plan_path = self.task_dir / "project.planned.json"
        plan_path.write_text(json.dumps(project_spec.model_dump(mode="json"), indent=2), encoding="utf-8")
        (self.task_dir / "visual_plan.json").write_text("{}", encoding="utf-8")

        result = run_evidence_acquisition(plan_path, task_id=self.task_id)
        self.assertEqual(result["status"], "failed")

        # Verify diagnostics recorded
        manifest_data = json.loads((self.task_dir / "evidence" / "evidence_manifest.json").read_text(encoding="utf-8"))
        failed_entry = manifest_data["failed_scenes"][0]
        diags = failed_entry.get("diagnostics", [])
        self.assertTrue(any("is not allowed for evidence" in d for d in diags))
        self.assertTrue(any("not found in registry" in d for d in diags))

    def test_registry_candidate_prevents_wikimedia_calls(self):
        from unittest.mock import patch

        sources = [
            EvidenceSource(
                id="SRC_VALID",
                kind=EvidenceSourceKind.pdf,
                local_file="sample_policy.pdf",
                title="Official Medicare Rules",
                trust=EvidenceSourceTrust.official,
            )
        ]
        registry = EvidenceSourceRegistry(sources=sources)
        (self.task_dir / "sources.json").write_text(json.dumps(registry.model_dump(mode="json"), indent=2), encoding="utf-8")

        project_spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Registry First Video", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Test", script="Doc."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(self.audio_file)),
            production=ProductionConfig(),
            timeline_cues=[TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Medicare")],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.document,
                    purpose=VisualPurpose.evidence,
                    start=0.0,
                    end=1.0,
                    narration="Medicare",
                    payload={"search_query": "Medicare eligibility age 65", "source_hint": "SSA", "evidence_required": True},
                )
            ],
        )
        plan_path = self.task_dir / "project.planned.json"
        plan_path.write_text(json.dumps(project_spec.model_dump(mode="json"), indent=2), encoding="utf-8")
        (self.task_dir / "visual_plan.json").write_text("{}", encoding="utf-8")

        with patch("app.services.evidence_runner.search_wikimedia_evidence") as mock_wiki:
            result = run_evidence_acquisition(plan_path, task_id=self.task_id)
            self.assertEqual(result["status"], "complete")
            # Proves Wikimedia was NOT called because registry candidate was valid and accepted
            mock_wiki.assert_not_called()

    def test_local_source_modification_refreshes_cache_and_rerenders(self):
        # Run 1: initial render
        sources = [
            EvidenceSource(
                id="SRC_MUTABLE",
                kind=EvidenceSourceKind.pdf,
                local_file="sample_policy.pdf",
                title="Mutable Rules",
                trust=EvidenceSourceTrust.official,
            )
        ]
        registry = EvidenceSourceRegistry(sources=sources)
        (self.task_dir / "sources.json").write_text(json.dumps(registry.model_dump(mode="json"), indent=2), encoding="utf-8")

        project_spec = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Mutable Video", aspect_ratio=VideoAspect.landscape, fps=30),
            script=ScriptSpec(subject="Test", script="Doc."),
            narration=NarrationSpec(mode=NarrationMode.file, file=str(self.audio_file)),
            production=ProductionConfig(),
            timeline_cues=[TimelineCue(id="S001", order=1, start=0.0, end=1.0, narration="Medicare")],
            visual_cues=[
                VisualCue(
                    id="S001",
                    order=1,
                    visual_type=VisualType.document,
                    purpose=VisualPurpose.evidence,
                    start=0.0,
                    end=1.0,
                    narration="Medicare",
                    payload={"search_query": "Medicare", "source_hint": "SSA", "source_ids": ["SRC_MUTABLE"]},
                )
            ],
        )
        plan_path = self.task_dir / "project.planned.json"
        plan_path.write_text(json.dumps(project_spec.model_dump(mode="json"), indent=2), encoding="utf-8")
        (self.task_dir / "visual_plan.json").write_text("{}", encoding="utf-8")

        res1 = run_evidence_acquisition(plan_path, task_id=self.task_id)
        self.assertEqual(res1["status"], "complete")
        meta1 = json.loads((self.task_dir / "evidence" / "S001" / "metadata.json").read_text(encoding="utf-8"))
        fp1 = meta1["spec_fingerprint"]
        sha1 = meta1["source_sha256"]

        # Modify original PDF bytes
        doc = pymupdf.open()
        p = doc.new_page(width=612, height=792)
        p.insert_text((50, 100), "MODIFIED RULES VERSION 2", fontsize=18)
        p.insert_text((50, 150), "Medicare coverage begins at age 70 in new policy.", fontsize=14)
        doc.save(str(self.pdf_path))
        doc.close()

        # Run 2: cache must refresh, SHA change, fingerprint change, rerender
        res2 = run_evidence_acquisition(plan_path, task_id=self.task_id)
        self.assertEqual(res2["status"], "complete")
        meta2 = json.loads((self.task_dir / "evidence" / "S001" / "metadata.json").read_text(encoding="utf-8"))
        fp2 = meta2["spec_fingerprint"]
        sha2 = meta2["source_sha256"]

        self.assertNotEqual(sha1, sha2)
        self.assertNotEqual(fp1, fp2)


if __name__ == "__main__":
    unittest.main()
