from __future__ import annotations

import unittest

from app.models.motion import MotionGroupSpec, MotionSceneSpec
from app.services.motion_grouper import form_motion_groups


class TestMotionGrouper(unittest.TestCase):
    def _make_spec(self, scene_id: str, order: int, group_id: str | None, start_f: int, end_f: int) -> MotionSceneSpec:
        return MotionSceneSpec(
            scene_id=scene_id,
            order=order,
            visual_type="data",
            requested_template="number",
            rendered_template="number",
            props={"headline": f"Scene {order}", "value": "100"},
            start_time=start_f / 30.0,
            end_time=end_f / 30.0,
            start_frame=start_f,
            end_frame=end_f,
            duration_frames=end_f - start_f,
            fps=30,
            width=1920,
            height=1080,
            visual_group_id=group_id,
        )

    def test_form_groups_contiguous(self):
        s1 = self._make_spec("S001", 1, "grp_1", 0, 60)
        s2 = self._make_spec("S002", 2, "grp_1", 60, 120)
        s3 = self._make_spec("S003", 3, "grp_1", 120, 180)
        s4 = self._make_spec("S004", 4, None, 180, 240)

        groups = form_motion_groups([s1, s2, s3, s4])
        self.assertEqual(len(groups), 2)
        self.assertIsInstance(groups[0], MotionGroupSpec)
        self.assertEqual(groups[0].group_id, "grp_1")
        self.assertEqual(groups[0].start_frame, 0)
        self.assertEqual(groups[0].end_frame, 180)
        self.assertEqual(groups[0].duration_frames, 180)
        self.assertEqual(len(groups[0].scenes), 3)

        self.assertIsInstance(groups[1], MotionSceneSpec)
        self.assertEqual(groups[1].scene_id, "S004")

    def test_form_groups_single_cue_not_wrapped(self):
        # A visual_group_id that only contains 1 cue remains a single MotionSceneSpec
        s1 = self._make_spec("S001", 1, "isolated_grp", 0, 60)
        groups = form_motion_groups([s1])
        self.assertEqual(len(groups), 1)
        self.assertIsInstance(groups[0], MotionSceneSpec)
        self.assertEqual(groups[0].scene_id, "S001")


if __name__ == "__main__":
    unittest.main()
