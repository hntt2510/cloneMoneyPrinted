import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from app.models.motion import (
    KineticBeat,
    KineticBeatKind,
    MotionAnimationPlan,
    MotionGroupSpec,
    MotionSceneSpec,
)
from app.models.project import ProjectSpec, VisualCue, VisualType
from app.services.kinetic_beat_deriver import derive_kinetic_beats
from app.services.motion_grouper import form_motion_groups
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_group_motion, render_scene_motion
from app.services.visual_planner import _apply_diversity
from app.utils import utils


def _extract_frame(mp4_path: Path, timestamp_sec: float, output_png: Path) -> np.ndarray:
    """Extract a single frame from MP4 at timestamp using ffmpeg and return as numpy RGB array."""
    ffmpeg_bin = utils.get_ffmpeg_binary()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(mp4_path.resolve()),
        "-ss",
        f"{timestamp_sec:.3f}",
        "-vframes",
        "1",
        str(output_png.resolve()),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not output_png.exists():
        raise RuntimeError(f"Failed to extract frame at {timestamp_sec}s from {mp4_path}: {res.stderr.decode('utf-8', errors='ignore')}")
    img = Image.open(output_png).convert("RGB")
    return np.array(img)


def _frame_diff(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    """Compute mean absolute pixel difference between two frames."""
    return float(np.mean(np.abs(frame_a.astype(float) - frame_b.astype(float))))


class TestG16RealRemotionRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node_available = shutil.which("node") is not None

    def setUp(self):
        if not self.node_available:
            self.skipTest("Node.js binary not available in PATH; skipping real render tests.")
        self.temp_dir = tempfile.mkdtemp(prefix="g16_render_test_")

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass

    def test_render_metric_hero_6k(self):
        """A. Render real Metric Hero $6K clip and verify multi-state frame evolution."""
        plan = derive_kinetic_beats(
            narration="Suppose repairing your car costs six thousand dollars.",
            fps=30,
            duration_frames=90,
            template="number",
            props={"numeric_value": 6000, "headline": "REPAIR COST"},
        )
        scene = MotionSceneSpec(
            scene_id="S001",
            order=1,
            visual_type="data",
            requested_template="number",
            rendered_template="number",
            props={
                "headline": "TOTAL REPAIR",
                "value": "$6,000",
                "numeric_value": 6000,
                "eyebrow": "REPAIR COST",
                "label": "ESTIMATED DAMAGE",
                "layout_archetype": "metric_hero",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
            animation_plan=plan,
            layout_archetype="metric_hero",
        )

        asset = render_scene_motion(scene, self.temp_dir)
        output_file = Path(asset.output_file)
        self.assertTrue(output_file.exists())
        self.assertGreater(output_file.stat().st_size, 1000)

        # Extract frames at 15% (0.45s) and 85% (2.55s)
        f_early = _extract_frame(output_file, 0.45, Path(self.temp_dir) / "f_early.png")
        f_late = _extract_frame(output_file, 2.55, Path(self.temp_dir) / "f_late.png")
        diff = _frame_diff(f_early, f_late)
        self.assertGreater(diff, 2.0, f"Frames should show visual evolution (got diff={diff})")

    def test_render_cost_breakdown_group_master(self):
        """B. Render full $6K/$1K/$5K group master and prove continuous multi-phase evolution."""
        scenes = [
            MotionSceneSpec(
                scene_id="S001",
                order=1,
                visual_type="data",
                requested_template="comparison",
                rendered_template="comparison",
                props={
                    "headline": "TOTAL REPAIR",
                    "value": "$6,000",
                    "numeric_value": 6000,
                    "eyebrow": "REPAIR COST",
                    "layout_archetype": "stacked_breakdown",
                    "total": {"label": "TOTAL REPAIR", "value": "$6,000", "numeric_value": 6000},
                    "parts": [
                        {"label": "YOU PAY", "value": "$1,000", "numeric_value": 1000, "highlight": True},
                        {"label": "INSURANCE", "value": "$5,000", "numeric_value": 5000, "highlight": False},
                    ],
                },
                start_time=0.0,
                end_time=2.0,
                start_frame=0,
                end_frame=60,
                duration_frames=60,
                fps=30,
                width=1280,
                height=720,
                visual_group_id="vg_cost",
                layout_archetype="stacked_breakdown",
            ),
            MotionSceneSpec(
                scene_id="S002",
                order=2,
                visual_type="data",
                requested_template="comparison",
                rendered_template="comparison",
                props={
                    "headline": "YOUR DEDUCTIBLE",
                    "value": "$1,000",
                    "numeric_value": 1000,
                    "eyebrow": "DEDUCTIBLE",
                    "layout_archetype": "stacked_breakdown",
                    "total": {"label": "TOTAL REPAIR", "value": "$6,000", "numeric_value": 6000},
                    "parts": [
                        {"label": "YOU PAY", "value": "$1,000", "numeric_value": 1000, "highlight": True},
                        {"label": "INSURANCE", "value": "$5,000", "numeric_value": 5000, "highlight": False},
                    ],
                },
                start_time=2.0,
                end_time=4.0,
                start_frame=60,
                end_frame=120,
                duration_frames=60,
                fps=30,
                width=1280,
                height=720,
                visual_group_id="vg_cost",
                layout_archetype="stacked_breakdown",
            ),
            MotionSceneSpec(
                scene_id="S003",
                order=3,
                visual_type="data",
                requested_template="comparison",
                rendered_template="comparison",
                props={
                    "headline": "INSURANCE COVERS",
                    "value": "$5,000",
                    "numeric_value": 5000,
                    "eyebrow": "INSURANCE",
                    "layout_archetype": "stacked_breakdown",
                    "total": {"label": "TOTAL REPAIR", "value": "$6,000", "numeric_value": 6000},
                    "parts": [
                        {"label": "YOU PAY", "value": "$1,000", "numeric_value": 1000, "highlight": True},
                        {"label": "INSURANCE", "value": "$5,000", "numeric_value": 5000, "highlight": False},
                    ],
                },
                start_time=4.0,
                end_time=6.0,
                start_frame=120,
                end_frame=180,
                duration_frames=60,
                fps=30,
                width=1280,
                height=720,
                visual_group_id="vg_cost",
                layout_archetype="stacked_breakdown",
            ),
        ]

        group = MotionGroupSpec(
            group_id="vg_cost",
            scene_ids=["S001", "S002", "S003"],
            start_frame=0,
            end_frame=180,
            duration_frames=180,
            fps=30,
            width=1280,
            height=720,
            scenes=scenes,
        )

        assets = render_group_motion(group, self.temp_dir)
        self.assertEqual(len(assets), 3)

        master_path = Path(self.temp_dir) / "motion" / "groups" / "vg_cost" / "master.mp4"
        self.assertTrue(master_path.exists())

        # Extract frames at representative phase midpoints:
        # Phase A (0..2.0s): 0.9s (Total $6K only)
        # Phase B (2.0..4.0s): 3.0s ($6K + $1K split)
        # Phase C (4.0..6.0s): 4.2s ($6K + $1K + $5K, before equation)
        # Phase D (Final): 5.7s (Resolved equation)
        f_15 = _extract_frame(master_path, 0.9, Path(self.temp_dir) / "breakdown_15.png")
        f_40 = _extract_frame(master_path, 3.0, Path(self.temp_dir) / "breakdown_40.png")
        f_65 = _extract_frame(master_path, 4.2, Path(self.temp_dir) / "breakdown_65.png")
        f_90 = _extract_frame(master_path, 5.7, Path(self.temp_dir) / "breakdown_90.png")

        diff_15_40 = _frame_diff(f_15, f_40)
        diff_40_65 = _frame_diff(f_40, f_65)
        diff_65_90 = _frame_diff(f_65, f_90)

        self.assertGreater(diff_15_40, 1.0, "Phase A to Phase B should show visible split")
        self.assertGreater(diff_40_65, 1.0, "Phase B to Phase C should show insurance resolution")
        self.assertGreater(diff_65_90, 1.0, "Phase C to Phase D should show equation resolution")

    def test_render_premium_vs_deductible_comparison(self):
        """C. Render split compare Premium vs Deductible and verify divider animation."""
        plan = derive_kinetic_beats(
            narration="Compare insurance premium against your deductible.",
            fps=30,
            duration_frames=90,
            template="comparison",
            props={
                "items": [
                    {"label": "PREMIUM", "value": "$150/mo", "highlight": False},
                    {"label": "DEDUCTIBLE", "value": "$1,000", "highlight": True},
                ]
            },
        )
        scene = MotionSceneSpec(
            scene_id="S004",
            order=4,
            visual_type="data",
            requested_template="comparison",
            rendered_template="comparison",
            props={
                "headline": "PREMIUM VS DEDUCTIBLE",
                "items": [
                    {"label": "PREMIUM", "value": "$150/mo", "highlight": False},
                    {"label": "DEDUCTIBLE", "value": "$1,000", "highlight": True},
                ],
                "layout_archetype": "split_compare",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
            animation_plan=plan,
            layout_archetype="split_compare",
        )

        asset = render_scene_motion(scene, self.temp_dir)
        output_file = Path(asset.output_file)
        self.assertTrue(output_file.exists())

        f_start = _extract_frame(output_file, 0.4, Path(self.temp_dir) / "comp_start.png")
        f_end = _extract_frame(output_file, 2.6, Path(self.temp_dir) / "comp_end.png")
        diff = _frame_diff(f_start, f_end)
        self.assertGreater(diff, 2.0)

    def test_render_threshold_25k_40k(self):
        """D. Render $25K limit vs $40K damage threshold and verify limit crossing."""
        plan = derive_kinetic_beats(
            narration="Your damage is forty thousand dollars exceeding the twenty five thousand dollar limit.",
            fps=30,
            duration_frames=120,
            template="threshold",
            props={"threshold_value": 25000, "current_value": 40000, "threshold_display": "$25K", "current_display": "$40K"},
        )
        scene = MotionSceneSpec(
            scene_id="S005",
            order=5,
            visual_type="data",
            requested_template="threshold",
            rendered_template="threshold",
            props={
                "headline": "POLICY LIMIT EXCEEDED",
                "threshold_value": 25000,
                "current_value": 40000,
                "threshold_display": "$25K",
                "current_display": "$40K",
                "threshold_label": "Coverage Limit",
                "layout_archetype": "threshold_v2",
            },
            start_time=0.0,
            end_time=4.0,
            start_frame=0,
            end_frame=120,
            duration_frames=120,
            fps=30,
            width=1280,
            height=720,
            animation_plan=plan,
            layout_archetype="threshold_v2",
        )

        asset = render_scene_motion(scene, self.temp_dir)
        output_file = Path(asset.output_file)
        self.assertTrue(output_file.exists())

        # Frame at 0.4s (limit marker only, empty bar), 1.4s (growing bar below threshold), 3.6s (crossed limit / OVER LIMIT)
        f_limit = _extract_frame(output_file, 0.4, Path(self.temp_dir) / "thresh_limit.png")
        f_grow = _extract_frame(output_file, 1.4, Path(self.temp_dir) / "thresh_grow.png")
        f_cross = _extract_frame(output_file, 3.6, Path(self.temp_dir) / "thresh_cross.png")

        diff_lim_grow = _frame_diff(f_limit, f_grow)
        diff_grow_cross = _frame_diff(f_grow, f_cross)

        self.assertGreater(diff_lim_grow, 1.0, f"Limit to grow should show bar growth (got {diff_lim_grow})")
        self.assertGreater(diff_grow_cross, 1.0, f"Grow to cross should show threshold overflow (got {diff_grow_cross})")

    def test_render_kinetic_statement_text(self):
        """E. Render kinetic statement text and verify clean MP4 output."""
        plan = derive_kinetic_beats(
            narration="The cheapest policy is not automatically the best policy.",
            fps=30,
            duration_frames=90,
            template="text",
            props={"headline": "CHEAPEST IS NOT BEST"},
        )
        scene = MotionSceneSpec(
            scene_id="S006",
            order=6,
            visual_type="text",
            requested_template="text",
            rendered_template="text",
            props={
                "headline": "CHEAPEST IS NOT BEST",
                "subheadline": "Quality matters most",
                "layout_archetype": "kinetic_statement",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
            animation_plan=plan,
            layout_archetype="kinetic_statement",
        )

        asset = render_scene_motion(scene, self.temp_dir)
        output_file = Path(asset.output_file)
        self.assertTrue(output_file.exists())


if __name__ == "__main__":
    unittest.main()
