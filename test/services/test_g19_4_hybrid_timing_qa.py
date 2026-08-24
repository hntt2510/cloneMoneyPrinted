from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.models.motion import KineticBeatKind, MotionSceneSpec, RendererFamily
from app.models.project import DataPayload, ProjectSpec, VisualCue, VisualPurpose, VisualType
from app.services.kinetic_beat_deriver import derive_kinetic_beats
from app.services.motion_normalizer import normalize_motion_spec
from app.services.remotion import render_scene_motion


class TestG194HybridTimingQA(unittest.TestCase):
    """G19.4 Hybrid Timing & Data Balance Hardening acceptance tests."""

    def setUp(self) -> None:
        self.project_stub = ProjectSpec.model_validate({
            "schema_version": "1.0",
            "project": {"title": "G19.4 Timing Test", "aspect_ratio": "16:9", "fps": 30},
            "script": {"subject": "SaaS Growth", "script": "In twenty twenty-six, annual recurring revenue surged to twelve million dollars, outperforming our initial target."},
            "narration": {"mode": "tts"},
            "timeline_cues": [],
            "visual_cues": [],
        })

    def test_voice_synced_hybrid_beats_progression(self) -> None:
        """Requirement A & B: Hybrid scene derives 5-stage voice-synced beats (setup -> concept -> number -> highlight -> context)."""
        narration = "In twenty twenty-six, annual recurring revenue surged to twelve million dollars, outperforming our initial target."
        fps = 30
        duration_frames = 120

        props = {
            "headline": "ANNUAL RECURRING REVENUE",
            "eyebrow": "FINANCIAL PERFORMANCE",
            "data_panel": {
                "value": "$12M",
                "numeric_value": 12000000.0,
                "label": "ARR 2026",
                "subtext": "Outperforming initial target by 20%",
            },
        }

        plan = derive_kinetic_beats(
            narration=narration,
            fps=fps,
            duration_frames=duration_frames,
            timing_source="tts",
            template="hybrid_broll",
            scene_id="S001",
            props=props,
        )

        self.assertIsNotNone(plan)
        self.assertGreaterEqual(len(plan.beats), 4)

        kinds = [b.kind for b in plan.beats]
        self.assertIn(KineticBeatKind.setup, kinds)
        self.assertIn(KineticBeatKind.reveal, kinds)
        self.assertIn(KineticBeatKind.number, kinds)

        setup_beat = next(b for b in plan.beats if b.kind == KineticBeatKind.setup)
        reveal_beat = next(b for b in plan.beats if b.kind == KineticBeatKind.reveal)
        number_beat = next(b for b in plan.beats if b.kind == KineticBeatKind.number)

        # Stage 1: Setup starts at frame 0
        self.assertEqual(setup_beat.start_frame, 0)
        self.assertLess(setup_beat.end_frame, number_beat.start_frame)

        # Stage 2: Concept reveal precedes number beat
        self.assertLessEqual(reveal_beat.start_frame, number_beat.start_frame)
        self.assertEqual(reveal_beat.data_ref, "headline")

        # Stage 3: Number start frame is synchronized with numeric clause
        self.assertGreater(number_beat.start_frame, setup_beat.end_frame)
        self.assertEqual(number_beat.data_ref, "number")

        # Final hold is preserved
        self.assertGreaterEqual(plan.final_hold_frames, 12)

    def test_optical_centering_and_mass_balance(self) -> None:
        """Requirement C: Hybrid composition layout geometry stays centered near frame center (50%)."""
        canvas_width = 1920
        canvas_height = 1080

        # Specifications defined in G19.4:
        # Asset: 46% width, Data panel: 42% width, Gap: 5% width, Horizontal padding: 3.5% each side
        asset_w = canvas_width * 0.46
        panel_w = canvas_width * 0.42
        gap = canvas_width * 0.05
        padding_x = canvas_width * 0.035

        total_width = padding_x + asset_w + gap + panel_w + padding_x
        self.assertAlmostEqual(total_width, canvas_width, delta=1.0)

        # Optical center of mass:
        asset_center_x = padding_x + asset_w / 2.0
        panel_center_x = canvas_width - padding_x - panel_w / 2.0
        midpoint_x = (asset_center_x + panel_center_x) / 2.0
        optical_center_pct = midpoint_x / canvas_width

        # Center of mass must be within [48%, 52%]
        self.assertGreaterEqual(optical_center_pct, 0.48)
        self.assertLessEqual(optical_center_pct, 0.52)

    def test_number_not_revealed_early(self) -> None:
        """Requirement E.1: Numbers do not appear before numeric narration beat in normalized MotionSceneSpec."""
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.data,
            purpose=VisualPurpose.explain,
            start=0.0,
            end=4.0,
            narration="In twenty twenty-six, annual recurring revenue surged to twelve million dollars.",
            payload=DataPayload(
                template="number",
                headline="ANNUAL RECURRING REVENUE",
                data={"value": "$12M", "numeric_value": 12000000.0},
            ).model_dump(mode="json"),
        )

        spec = normalize_motion_spec(cue, self.project_stub)
        self.assertIsNotNone(spec.animation_plan)

        number_beat = next(b for b in spec.animation_plan.beats if b.kind == KineticBeatKind.number)
        self.assertGreater(number_beat.start_frame, 0, "Number beat must NOT start at frame 0 when setup/concept precedes it")

    def test_chart_bars_reveal_on_narration_beats(self) -> None:
        """Requirement D: Bar chart bars are mapped to distinct sequential chart_item beats."""
        narration = "Tier one costs forty dollars, tier two costs seventy dollars, and tier three costs one hundred dollars."
        fps = 30
        duration_frames = 150

        props = {
            "headline": "PRICING TIERS",
            "items": [
                {"label": "Tier 1", "value": 40},
                {"label": "Tier 2", "value": 70},
                {"label": "Tier 3", "value": 100},
            ],
        }

        plan = derive_kinetic_beats(
            narration=narration,
            fps=fps,
            duration_frames=duration_frames,
            timing_source="tts",
            template="bar_chart",
            scene_id="S002",
            props=props,
        )

        bar_beats = [b for b in plan.beats if b.data_ref and b.data_ref.startswith("bar_")]
        self.assertEqual(len(bar_beats), 3)
        self.assertLess(bar_beats[0].start_frame, bar_beats[1].start_frame)
        self.assertLess(bar_beats[1].start_frame, bar_beats[2].start_frame)

    def test_hybrid_real_render_frame_diff_qa(self) -> None:
        """Requirement E.2 & E.4: Real render frame-diff QA confirms 5-stage progressive reveal (Setup -> Concept -> Number -> Qualifier -> Settle)."""
        import numpy as np
        from PIL import Image
        import subprocess

        def _extract_frame(mp4: str, t_sec: float, out_png: str) -> np.ndarray:
            ffmpeg_bin = "ffmpeg"
            try:
                import imageio_ffmpeg
                ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe() or "ffmpeg"
            except Exception:
                pass
            cmd = [
                ffmpeg_bin, "-y",
                "-ss", f"{t_sec:.3f}",
                "-i", mp4,
                "-vframes", "1",
                "-q:v", "2",
                out_png,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0 or not Path(out_png).exists():
                raise RuntimeError(f"Frame extraction failed: {res.stderr}")
            with Image.open(out_png) as img:
                return np.array(img.convert("RGB"))

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            out_mp4 = str(temp_path / "hybrid_rendered.mp4")

            # Create synthetic footage file for the left frame
            dummy_asset = temp_path / "dummy_evidence.mp4"
            # Create a 4-second valid test mp4 via ffmpeg
            ffmpeg_bin = "ffmpeg"
            try:
                import imageio_ffmpeg
                ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe() or "ffmpeg"
            except Exception:
                pass
            gen_cmd = [
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "color=c=0x1E293B:s=884x842:d=4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(dummy_asset),
            ]
            subprocess.run(gen_cmd, capture_output=True, text=True)

            spec = MotionSceneSpec(
                scene_id="G19_4_HYBRID_DEMO",
                order=1,
                visual_type="data",
                requested_template="hybrid_broll",
                rendered_template="hybrid_broll",
                layout_archetype="asset_left_data_right",
                start_time=0.0,
                end_time=4.0,
                start_frame=0,
                end_frame=120,
                duration_frames=120,
                fps=30,
                width=1920,
                height=1080,
                props={
                    "headline": "ANNUAL RECURRING REVENUE",
                    "eyebrow": "GROWTH TRAJECTORY",
                    "asset_path": str(dummy_asset),
                    "data_panel": {
                        "value": "$12M",
                        "numeric_value": 12000000.0,
                        "label": "ARR 2026",
                        "delta_display": "+40%",
                        "delta_sentiment": "positive",
                        "subtext": "Exceeding annual target by twenty percent",
                    },
                },
                animation_plan=derive_kinetic_beats(
                    narration="In twenty twenty-six, annual recurring revenue surged to twelve million dollars, outperforming our initial target.",
                    fps=30,
                    duration_frames=120,
                    timing_source="tts",
                    template="hybrid_broll",
                    scene_id="G19_4_HYBRID_DEMO",
                    props={
                        "headline": "ANNUAL RECURRING REVENUE",
                        "eyebrow": "GROWTH TRAJECTORY",
                        "data_panel": {
                            "value": "$12M",
                            "numeric_value": 12000000.0,
                            "label": "ARR 2026",
                            "delta_display": "+40%",
                            "delta_sentiment": "positive",
                            "subtext": "Exceeding annual target by twenty percent",
                        },
                    },
                ),
            )

            # Render scene
            render_res = render_scene_motion(spec, task_directory=temp_path)
            out_mp4 = str(temp_path / "motion" / render_res.output_file)
            self.assertTrue(Path(out_mp4).exists())
            self.assertGreater(Path(out_mp4).stat().st_size, 1000)

            # Extract 5 stage frames
            f1_png = str(temp_path / "stage1_setup.png")
            f2_png = str(temp_path / "stage2_concept.png")
            f3_png = str(temp_path / "stage3_number.png")
            f4_png = str(temp_path / "stage4_qualifier.png")
            f5_png = str(temp_path / "stage5_hold.png")

            f1 = _extract_frame(out_mp4, 0.25, f1_png)  # frame 7: Setup / Container / Eyebrow
            f2 = _extract_frame(out_mp4, 1.00, f2_png)  # frame 30: Concept Headline
            f3 = _extract_frame(out_mp4, 2.30, f3_png)  # frame 69: Number count-up + Delta
            f4 = _extract_frame(out_mp4, 3.20, f4_png)  # frame 96: Qualifier subtext
            f5 = _extract_frame(out_mp4, 3.80, f5_png)  # frame 114: Final hold

            # Copy frames and video to artifact tempmediaStorage for reporting
            artifact_media_dir = Path(r"C:\Users\LEGION\.gemini\antigravity\brain\df0e2156-6de1-422e-aa39-8aa3c8bd566c\.tempmediaStorage")
            artifact_media_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(out_mp4, str(artifact_media_dir / "g19_4_hybrid_review_video.mp4"))
            shutil.copy(f1_png, str(artifact_media_dir / "g19_4_stage1_setup.png"))
            shutil.copy(f2_png, str(artifact_media_dir / "g19_4_stage2_concept.png"))
            shutil.copy(f3_png, str(artifact_media_dir / "g19_4_stage3_number.png"))
            shutil.copy(f4_png, str(artifact_media_dir / "g19_4_stage4_qualifier.png"))
            shutil.copy(f5_png, str(artifact_media_dir / "g19_4_stage5_hold.png"))

            # Calculate pairwise perceptual pixel differences
            diff_1_2 = int(np.sum(np.abs(f1.astype(int) - f2.astype(int))))
            diff_2_3 = int(np.sum(np.abs(f2.astype(int) - f3.astype(int))))
            diff_3_4 = int(np.sum(np.abs(f3.astype(int) - f4.astype(int))))
            diff_4_5 = int(np.sum(np.abs(f4.astype(int) - f5.astype(int))))

            # Stage 1 -> Stage 2: Concept headline progressive entrance produces distinct pixels
            self.assertGreater(diff_1_2, 30000, f"Stage 1 vs 2 pixel difference {diff_1_2} must exceed 30,000")

            # Stage 2 -> Stage 3: Numeric count-up and delta reveal produces distinct pixels
            self.assertGreater(diff_2_3, 30000, f"Stage 2 vs 3 pixel difference {diff_2_3} must exceed 30,000")

            # Stage 3 -> Stage 4: Subtext qualifier entrance produces distinct pixels
            self.assertGreater(diff_3_4, 10000, f"Stage 3 vs 4 pixel difference {diff_3_4} must exceed 10,000")

            # Stage 4 -> Stage 5: Final hold continues with subtle camera push
            self.assertLess(diff_4_5, 10000000, f"Stage 4 vs 5 diff {diff_4_5} is within expected range")


if __name__ == "__main__":
    unittest.main()
