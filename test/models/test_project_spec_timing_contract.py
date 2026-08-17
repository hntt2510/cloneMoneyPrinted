import json
import tempfile
import unittest
from pathlib import Path

from app.models.project import (
    DataPayload,
    DataTemplate,
    BrollPayload,
    JobStatus,
    ProjectMetadata,
    ProjectSpec,
    NarrationSpec,
    ProductionConfig,
    ScriptSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.project_spec import load_project_spec, save_project_spec
from app.services.visual_planner import normalize_visual_cue_boundaries


class TestProjectSpecTimingContract(unittest.TestCase):
    """Test suite for ProjectSpec timing coverage contract and backward compatibility."""

    def _create_base_spec(self, timeline_cues, visual_cues=None, fps=30):
        meta = ProjectMetadata(
            title="Electric Cars Speed",
            aspect_ratio=VideoAspect.landscape,
            fps=fps,
        )
        script = ScriptSpec(subject="EVs", script="Sample script text")
        narration = NarrationSpec(voice_name="en-US-JennyNeural")
        production = ProductionConfig()
        return ProjectSpec(
            schema_version="1.0",
            project=meta,
            script=script,
            narration=narration,
            production=production,
            timeline_cues=timeline_cues,
            visual_cues=visual_cues or [],
        )

    def test_backward_compatibility_exact_timings_accepted(self):
        """Old ProjectSpecs where visual.start == timeline.start and visual.end == timeline.end remain 100% valid."""
        t_cues = [
            TimelineCue(id="S001", order=1, start=0.10, end=3.90, narration="Speech 1"),
            TimelineCue(id="S002", order=2, start=4.08, end=6.80, narration="Speech 2"),
        ]
        v_cues = [
            VisualCue(
                id="S001",
                order=1,
                start=0.10,
                end=3.90,
                narration="Speech 1",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="electric car").model_dump(mode="json"),
            ),
            VisualCue(
                id="S002",
                order=2,
                start=4.08,
                end=6.80,
                narration="Speech 2",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="fast motor").model_dump(mode="json"),
            ),
        ]
        spec = self._create_base_spec(t_cues, v_cues)
        self.assertEqual(len(spec.visual_cues), 2)
        self.assertEqual(spec.visual_cues[0].start, 0.10)
        self.assertEqual(spec.visual_cues[0].end, 3.90)

    def test_normalized_coverage_timings_accepted(self):
        """Normalized visual cues covering speech pauses continuously are accepted."""
        t_cues = [
            TimelineCue(id="S001", order=1, start=0.10, end=3.90, narration="Speech 1"),
            TimelineCue(id="S002", order=2, start=4.08, end=6.80, narration="Speech 2"),
        ]
        v_cues = [
            VisualCue(
                id="S001",
                order=1,
                start=0.00,  # Starts before narration
                end=4.08,    # Covers pause between S001 and S002
                narration="Speech 1",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="electric car").model_dump(mode="json"),
            ),
            VisualCue(
                id="S002",
                order=2,
                start=4.08,
                end=7.00,    # Covers through speech end and audio trailing silence
                narration="Speech 2",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="fast motor").model_dump(mode="json"),
            ),
        ]
        spec = self._create_base_spec(t_cues, v_cues)
        self.assertEqual(len(spec.visual_cues), 2)
        self.assertEqual(spec.visual_cues[0].start, 0.00)
        self.assertEqual(spec.visual_cues[0].end, 4.08)

    def test_reject_visual_starts_after_narration(self):
        """Reject when visual starts after narration has already started."""
        t_cues = [
            TimelineCue(id="S001", order=1, start=0.10, end=3.90, narration="Speech 1"),
        ]
        v_cues = [
            VisualCue(
                id="S001",
                order=1,
                start=0.50,  # 15 frames > 3 frames (starts late!)
                end=3.90,
                narration="Speech 1",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="electric car").model_dump(mode="json"),
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            self._create_base_spec(t_cues, v_cues)
        self.assertIn("starts at frame 15 after narration starts at frame 3", str(ctx.exception))

    def test_reject_visual_ends_before_narration(self):
        """Reject when visual ends before narration ends."""
        t_cues = [
            TimelineCue(id="S001", order=1, start=0.10, end=3.90, narration="Speech 1"),
        ]
        v_cues = [
            VisualCue(
                id="S001",
                order=1,
                start=0.00,
                end=3.50,  # 105 frames < 117 frames (ends early!)
                narration="Speech 1",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="electric car").model_dump(mode="json"),
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            self._create_base_spec(t_cues, v_cues)
        self.assertIn("ends at frame 105 before narration ends at frame 117", str(ctx.exception))

    def test_reject_mismatched_id_or_narration_or_order(self):
        """Strict invariants remain: same cue IDs, orders, and narration association."""
        t_cues = [
            TimelineCue(id="S001", order=1, start=0.00, end=3.00, narration="Exact Speech Text"),
        ]
        # Mismatched narration
        v_cues_bad_text = [
            VisualCue(
                id="S001",
                order=1,
                start=0.00,
                end=3.00,
                narration="Different Speech Text",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="query").model_dump(mode="json"),
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            self._create_base_spec(t_cues, v_cues_bad_text)
        self.assertIn("narration must match timeline cue narration", str(ctx.exception))

        # Mismatched order
        v_cues_bad_order = [
            VisualCue(
                id="S001",
                order=2,
                start=0.00,
                end=3.00,
                narration="Exact Speech Text",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="query").model_dump(mode="json"),
            ),
        ]
        with self.assertRaises(ValueError) as ctx:
            self._create_base_spec(t_cues, v_cues_bad_order)
        self.assertIn("visual cue order must match timeline cue order", str(ctx.exception))

    def test_uat_shape_4_cues_pause_gaps_normalization_roundtrip(self):
        """Real UAT shape (4 cues with speech pauses) normalizes, validates, and saves/loads cleanly."""
        t_cues = [
            TimelineCue(id="S001", order=1, start=0.10, end=3.90, narration="Electric vehicles deliver peak torque instantly."),
            TimelineCue(id="S002", order=2, start=4.08, end=6.80, narration="Creating an immediate sensation of effortless acceleration."),
            TimelineCue(id="S003", order=3, start=7.66, end=11.20, narration="Unlike internal combustion engines with mechanical delay."),
            TimelineCue(id="S004", order=4, start=11.45, end=15.60, narration="Direct-drive electric motors achieve maximum efficiency."),
        ]
        raw_v_cues = [
            VisualCue(
                id="S001",
                order=1,
                start=0.10,
                end=3.90,
                narration="Electric vehicles deliver peak torque instantly.",
                visual_type=VisualType.data,
                purpose=VisualPurpose.evidence,
                payload=DataPayload(template=DataTemplate.number, headline="0-60 in 2.3s").model_dump(mode="json"),
            ),
            VisualCue(
                id="S002",
                order=2,
                start=4.08,
                end=6.80,
                narration="Creating an immediate sensation of effortless acceleration.",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="electric car acceleration").model_dump(mode="json"),
            ),
            VisualCue(
                id="S003",
                order=3,
                start=7.66,
                end=11.20,
                narration="Unlike internal combustion engines with mechanical delay.",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="combustion engine").model_dump(mode="json"),
            ),
            VisualCue(
                id="S004",
                order=4,
                start=11.45,
                end=15.60,
                narration="Direct-drive electric motors achieve maximum efficiency.",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(search_query="electric motor").model_dump(mode="json"),
            ),
        ]

        canonical_duration = 16.4667  # Narration audio total duration
        normalized_visuals = normalize_visual_cue_boundaries(
            raw_v_cues,
            fps=30,
            total_duration_seconds=canonical_duration,
        )

        spec = self._create_base_spec(t_cues, normalized_visuals, fps=30)
        # Verify first starts at 0.0 and last ends at canonical duration
        self.assertEqual(spec.visual_cues[0].start, 0.0)
        self.assertAlmostEqual(spec.visual_cues[-1].end, 16.4667, places=2)

        # Test model dump & validation
        dumped = spec.model_dump(mode="json")
        reloaded = ProjectSpec.model_validate(dumped)
        self.assertEqual(len(reloaded.visual_cues), 4)

        # Test save & load roundtrip
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "project.planned.json"
            save_project_spec(reloaded, fpath)
            loaded = load_project_spec(fpath)
            self.assertEqual(len(loaded.visual_cues), 4)
            self.assertEqual(loaded.visual_cues[0].start, 0.0)


if __name__ == "__main__":
    unittest.main()
