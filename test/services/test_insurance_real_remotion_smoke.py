import json
import tempfile
import unittest
from pathlib import Path

from app.models.project import (
    DataPayload,
    DataTemplate,
    NarrationSpec,
    ProjectMetadata,
    ProjectSpec,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_scene_motion
from app.services.visual_planner import fallback_visual


class TestInsuranceRealRemotionSmoke(unittest.TestCase):
    def test_real_remotion_render_insurance_narratives(self):
        """Render real MP4 clips for insurance spoken-number scenes with Remotion."""
        project = ProjectSpec(
            schema_version="1.0",
            project=ProjectMetadata(title="Insurance Render Test", aspect_ratio=VideoAspect.landscape, fps=30),
            script={"subject": "Insurance Claims", "script": "Insurance Claims Breakdown"},
            narration=NarrationSpec(mode="tts"),
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)

            # 1. Number Scene ($6,000 repair cost)
            cue1 = VisualCue(
                id="S013",
                order=13,
                visual_type=VisualType.data,
                purpose=VisualPurpose.explain,
                start=0.0,
                end=3.0,
                narration="Suppose repairing your car costs six thousand dollars.",
                payload=DataPayload(
                    template=DataTemplate.number,
                    headline="Repair Cost",
                    data={"value": "$6,000", "numeric_value": 6000, "label": "Repair Cost", "prefix": "$"},
                ).model_dump(mode="json"),
            )
            spec1 = normalize_motion_spec(cue1, project)
            self.assertEqual(spec1.rendered_template, "number")
            asset1 = render_scene_motion(spec1, task_directory=task_dir)
            out1 = Path(asset1.output_file)
            self.assertTrue(out1.exists())
            self.assertGreater(out1.stat().st_size, 1000)
            self.assertEqual(asset1.duration_frames, 90)

            # 2. Comparison Scene (Premium vs Deductible)
            cue2 = VisualCue(
                id="S018",
                order=18,
                visual_type=VisualType.data,
                purpose=VisualPurpose.compare,
                start=3.0,
                end=7.0,
                narration="Your premium is what you pay to keep the policy active versus your deductible.",
                payload=DataPayload(
                    template=DataTemplate.comparison,
                    headline="Insurance Premium vs. Deductible",
                    data={
                        "items": [
                            {"label": "Premium", "value": "Recurring Cost", "highlight": False},
                            {"label": "Deductible", "value": "Out-of-Pocket on Claim", "highlight": True},
                        ]
                    },
                ).model_dump(mode="json"),
            )
            spec2 = normalize_motion_spec(cue2, project)
            self.assertEqual(spec2.rendered_template, "comparison")
            asset2 = render_scene_motion(spec2, task_directory=task_dir)
            out2 = Path(asset2.output_file)
            self.assertTrue(out2.exists())
            self.assertGreater(out2.stat().st_size, 1000)
            self.assertEqual(asset2.duration_frames, 120)

            # 3. Threshold Scene ($25K limit vs $40K damage)
            cue3 = VisualCue(
                id="S030",
                order=30,
                visual_type=VisualType.data,
                purpose=VisualPurpose.compare,
                start=7.0,
                end=11.0,
                narration="Imagine you have twenty-five thousand dollars limit, but you cause forty thousand dollars in damage.",
                payload=DataPayload(
                    template=DataTemplate.threshold,
                    headline="Coverage Limit Exceeded",
                    data={
                        "current_value": 40000.0,
                        "current_display": "$40,000",
                        "threshold_value": 25000.0,
                        "threshold_display": "$25,000",
                        "threshold_label": "Coverage Limit",
                        "subtext": "Above Policy Limit",
                    },
                ).model_dump(mode="json"),
            )
            spec3 = normalize_motion_spec(cue3, project)
            self.assertEqual(spec3.rendered_template, "threshold")
            asset3 = render_scene_motion(spec3, task_directory=task_dir)
            out3 = Path(asset3.output_file)
            self.assertTrue(out3.exists())
            self.assertGreater(out3.stat().st_size, 1000)
            self.assertEqual(asset3.duration_frames, 120)


if __name__ == "__main__":
    unittest.main()
