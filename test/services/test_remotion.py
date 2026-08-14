from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.models.motion import (
    AgeMarkerItem,
    AgeMarkerProps,
    MotionGroupSpec,
    MotionSceneSpec,
    NumberProps,
)
from app.services.remotion import (
    MotionRenderValidationError,
    render_group_motion,
    render_scene_motion,
    validate_rendered_motion_clip,
)


class TestRemotionEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="remotion_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_smoke_render_single_scene(self):
        props = NumberProps(headline="RETIREMENT GOAL", value="$1,000,000", label="TARGET")
        scene_spec = MotionSceneSpec(
            scene_id="S001",
            order=1,
            visual_type="data",
            requested_template="number",
            rendered_template="number",
            props=props.model_dump(mode="json"),
            start_time=0.0,
            end_time=1.5,
            start_frame=0,
            end_frame=45,
            duration_frames=45,
            fps=30,
            width=640,
            height=360,
        )

        asset = render_scene_motion(scene_spec, self.temp_dir)
        self.assertEqual(asset.scene_id, "S001")
        self.assertTrue(Path(asset.output_file).exists())
        self.assertGreater(Path(asset.output_file).stat().st_size, 0)

        # Validate clip attributes
        actual_duration = validate_rendered_motion_clip(
            rendered_path=asset.output_file,
            expected_duration_frames=45,
            expected_width=640,
            expected_height=360,
            expected_fps=30,
        )
        self.assertAlmostEqual(actual_duration, 1.5, delta=0.1)

    def test_smoke_render_group_and_slicing(self):
        s1 = MotionSceneSpec(
            scene_id="S010",
            order=10,
            visual_type="data",
            requested_template="number",
            rendered_template="number",
            props=NumberProps(headline="STEP 1", value="A").model_dump(mode="json"),
            start_time=0.0,
            end_time=1.0,
            start_frame=0,
            end_frame=30,
            duration_frames=30,
            fps=30,
            width=640,
            height=360,
            visual_group_id="grp_smoke",
        )
        s2 = MotionSceneSpec(
            scene_id="S011",
            order=11,
            visual_type="data",
            requested_template="number",
            rendered_template="number",
            props=NumberProps(headline="STEP 2", value="B").model_dump(mode="json"),
            start_time=1.0,
            end_time=2.0,
            start_frame=30,
            end_frame=60,
            duration_frames=30,
            fps=30,
            width=640,
            height=360,
            visual_group_id="grp_smoke",
        )
        group_spec = MotionGroupSpec(
            group_id="grp_smoke",
            scene_ids=["S010", "S011"],
            start_frame=0,
            end_frame=60,
            duration_frames=60,
            fps=30,
            width=640,
            height=360,
            scenes=[s1, s2],
        )

        assets = render_group_motion(group_spec, self.temp_dir)
        self.assertEqual(len(assets), 2)
        self.assertTrue(Path(assets[0].output_file).exists())
        self.assertTrue(Path(assets[1].output_file).exists())

        # Validate master and sliced clips
        for asset in assets:
            validate_rendered_motion_clip(
                rendered_path=asset.output_file,
                expected_duration_frames=30,
                expected_width=640,
                expected_height=360,
                expected_fps=30,
            )


if __name__ == "__main__":
    unittest.main()
