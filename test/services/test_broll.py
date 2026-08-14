import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.project import (
    BrollCandidate,
    BrollPayload,
    JobStatus,
    ProjectMetadata,
    ProjectSpec,
    SelectedBrollAsset,
    TimelineCue,
    VisualCue,
    VisualPurpose,
    VisualType,
)
from app.models.schema import VideoAspect
from app.services import broll
from app.services.broll import (
    BrollAcquisitionError,
    BrollSelectionContext,
    acquire_broll_scene,
    collect_and_rank_candidates,
    download_candidate,
    get_video_duration,
    render_scene_clip,
    score_candidate,
)
from app.utils import utils


def _create_synthetic_video(path: Path | str, duration: float = 6.0, width: int = 1280, height: int = 720, fps: int = 24) -> Path:
    """Create a minimal fast synthetic video file for test fixtures using ffmpeg."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = utils.get_ffmpeg_binary()
    cmd = [
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=blue:s={width}x{height}:d={duration}:r={fps}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(dest),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or not dest.exists():
        # Fallback to MoviePy ColorClip if needed
        from moviepy.video.VideoClip import ColorClip
        clip = ColorClip(size=(width, height), color=(0, 0, 255), duration=duration)
        clip.write_videofile(str(dest), fps=fps, codec="libx264", logger=None)
        clip.close()
    return dest


def _sample_project(aspect: VideoAspect = VideoAspect.landscape) -> ProjectSpec:
    return ProjectSpec(
        schema_version="1.0",
        project=ProjectMetadata(title="Test B-roll", aspect_ratio=aspect, fps=30),
        script={"subject": "Retirement Planning", "script": "Medicare begins at 65."},
        narration={"mode": "tts"},
        timeline_cues=[
            TimelineCue(id="S001", order=1, start=0.0, end=4.0, narration="Medicare begins at 65.")
        ],
        visual_cues=[
            VisualCue(
                id="S001",
                order=1,
                start=0.0,
                end=4.0,
                narration="Medicare begins at 65.",
                visual_type=VisualType.broll,
                purpose=VisualPurpose.context,
                payload=BrollPayload(
                    search_query="senior couple",
                    fallback_queries=["retiree healthcare", "doctor consultation"],
                    avoid=["animation", "text overlay"],
                    source_priority=["pexels", "pixabay", "coverr"],
                ).model_dump(mode="json"),
            )
        ],
    )


def _candidate(
    cid: str = "c1",
    provider: str = "pexels",
    query: str = "senior couple",
    duration: float = 10.0,
    width: int = 1920,
    height: int = 1080,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    download_url: str = "https://example.com/dl1.mp4",
    source_url: str = "https://example.com/src1",
) -> BrollCandidate:
    return BrollCandidate(
        id=cid,
        provider=provider,
        provider_asset_id=cid,
        query=query,
        download_url=download_url,
        source_url=source_url,
        duration=duration,
        width=width,
        height=height,
        title=title,
        description=description,
        tags=tags or [],
    )


class TestBrollSelectionContext(unittest.TestCase):
    def test_duplicate_asset_id_and_url_prevention(self):
        ctx = BrollSelectionContext()
        c1 = _candidate(cid="p1", download_url="https://dl.example/v1.mp4?token=123", source_url="https://src.example/1")
        c1_dup_url = _candidate(cid="p2", download_url="https://dl.example/v1.mp4?token=456")
        c1_dup_id = _candidate(cid="p1", download_url="https://dl.example/other.mp4")

        asset = SelectedBrollAsset(
            scene_id="S001",
            provider="pexels",
            provider_asset_id="p1",
            query_used="senior",
            candidate_id="p1",
            download_url="https://dl.example/v1.mp4?token=123",
            source_file="source.mp4",
            rendered_file="rendered.mp4",
            source_duration=10.0,
            trim_start=0.0,
            trim_end=4.0,
            scene_duration=4.0,
            width=1920,
            height=1080,
        )

        ctx.record_selection(c1, asset)

        self.assertTrue(ctx.is_duplicate(c1_dup_id))
        self.assertTrue(ctx.is_duplicate(c1_dup_url))

        c2 = _candidate(cid="p3", download_url="https://dl.example/v2.mp4", source_url="https://src.example/2")
        self.assertFalse(ctx.is_duplicate(c2))


class TestBrollScoring(unittest.TestCase):
    def test_semantic_match_outweighs_pure_resolution(self):
        # Candidate A: 1080p with strong semantic token overlap
        cand_a = _candidate(
            cid="a",
            query="senior couple retirement",
            title="Senior couple enjoying retirement",
            tags=["senior", "couple", "retirement", "park"],
            width=1920,
            height=1080,
        )
        # Candidate B: 4K UHD with zero semantic token overlap
        cand_b = _candidate(
            cid="b",
            query="senior couple retirement",
            title="City skyline traffic night",
            tags=["city", "cars", "highway"],
            width=3840,
            height=2160,
        )

        score_a, breakdown_a = score_candidate(cand_a, scene_duration=4.0)
        score_b, breakdown_b = score_candidate(cand_b, scene_duration=4.0)

        self.assertGreater(score_a, score_b)
        self.assertGreater(breakdown_a["semantic"], breakdown_b["semantic"])
        self.assertGreater(breakdown_b["quality"], breakdown_a["quality"])

    def test_avoid_terms_penalizes_compatibility(self):
        cand_clean = _candidate(cid="c1", tags=["senior", "office", "documents"])
        cand_avoid = _candidate(cid="c2", tags=["senior", "animation", "cartoon"])

        _, breakdown_clean = score_candidate(cand_clean, scene_duration=4.0, avoid_terms=["animation", "text overlay"])
        _, breakdown_avoid = score_candidate(cand_avoid, scene_duration=4.0, avoid_terms=["animation", "text overlay"])

        self.assertEqual(breakdown_clean["compatibility"], 15.0)
        self.assertEqual(breakdown_avoid["compatibility"], 0.0)

    def test_duration_suitability_scores(self):
        cand_short = _candidate(cid="short", duration=3.0)
        cand_optimal = _candidate(cid="optimal", duration=8.0)
        cand_long = _candidate(cid="long", duration=150.0)

        _, b_short = score_candidate(cand_short, scene_duration=5.0)
        _, b_opt = score_candidate(cand_optimal, scene_duration=5.0)
        _, b_long = score_candidate(cand_long, scene_duration=5.0)

        self.assertEqual(b_short["duration"], 0.0)
        self.assertEqual(b_opt["duration"], 10.0)
        self.assertEqual(b_long["duration"], 5.0)

    def test_aspect_ratio_scores(self):
        cand_landscape = _candidate(cid="land", width=1920, height=1080)
        cand_portrait = _candidate(cid="port", width=1080, height=1920)

        _, b_land_for_16_9 = score_candidate(cand_landscape, scene_duration=4.0, target_aspect=VideoAspect.landscape)
        _, b_port_for_16_9 = score_candidate(cand_portrait, scene_duration=4.0, target_aspect=VideoAspect.landscape)

        self.assertEqual(b_land_for_16_9["aspect"], 10.0)
        self.assertEqual(b_port_for_16_9["aspect"], 5.0)


class TestCandidateRankingAndFallback(unittest.TestCase):
    def test_fallback_query_selected_when_primary_returns_zero(self):
        project = _sample_project()
        cue = project.visual_cues[0]
        ctx = BrollSelectionContext()

        def mock_search(provider, query, **kwargs):
            if query == "senior couple":
                return []
            if query == "retiree healthcare":
                return [_candidate(cid=f"{provider}-1", provider=provider, query=query, duration=10.0)]
            return []

        with patch("app.services.broll.search_stock_candidates", side_effect=mock_search):
            candidates = collect_and_rank_candidates(cue, project, ctx)

        self.assertGreater(len(candidates), 0)
        self.assertEqual(candidates[0].query, "retiree healthcare")

    def test_provider_fallback_when_first_provider_fails(self):
        project = _sample_project()
        cue = project.visual_cues[0]
        ctx = BrollSelectionContext()

        def mock_search(provider, query, **kwargs):
            if provider == "pexels":
                raise RuntimeError("Pexels 500 error")
            if provider == "pixabay":
                return [_candidate(cid="pixabay-1", provider="pixabay", query=query, duration=10.0)]
            return []

        with patch("app.services.broll.search_stock_candidates", side_effect=mock_search):
            candidates = collect_and_rank_candidates(cue, project, ctx)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].provider, "pixabay")


class TestWinnerOnlyDownloadAndRetry(unittest.TestCase):
    def test_only_winner_is_downloaded_and_retries_next_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            synthetic_source = _create_synthetic_video(task_dir / "mock_winner.mp4", duration=8.0)

            project = _sample_project()
            cue = project.visual_cues[0]
            ctx = BrollSelectionContext()

            cand1 = _candidate(cid="c1", query="senior couple", download_url="https://dl.example/c1.mp4", title="Best match")
            cand2 = _candidate(cid="c2", query="senior couple", download_url="https://dl.example/c2.mp4", title="Second match")
            cand3 = _candidate(cid="c3", query="senior couple", download_url="https://dl.example/c3.mp4", title="Third match")

            download_attempts = []

            def mock_download(candidate, dest_path):
                download_attempts.append(candidate.id)
                if candidate.id == "c1":
                    raise ValueError("Network drop on candidate 1")
                # Candidate 2 succeeds: copy synthetic video to dest
                import shutil
                shutil.copyfile(synthetic_source, dest_path)
                return Path(dest_path)

            with patch("app.services.broll.collect_and_rank_candidates", return_value=[cand1, cand2, cand3]), \
                 patch("app.services.broll.download_candidate", side_effect=mock_download):
                asset = acquire_broll_scene(cue, project, task_dir, ctx)

            # Only c1 (failed) and c2 (succeeded) were downloaded. c3 was never downloaded!
            self.assertEqual(download_attempts, ["c1", "c2"])
            self.assertEqual(asset.candidate_id, "c2")
            self.assertTrue(Path(asset.rendered_file).exists())


class TestExactDurationAndSceneRendering(unittest.TestCase):
    def test_render_scene_clip_exact_duration_and_full_frame(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            source_file = _create_synthetic_video(temp_path / "source.mp4", duration=8.0, width=1280, height=720, fps=24)
            rendered_file = temp_path / "rendered.mp4"

            # Required scene: 3.5s at 1920x1080 30fps
            src_dur, trim_start, trim_end = render_scene_clip(
                source_path=source_file,
                destination_path=rendered_file,
                scene_duration=3.5,
                target_width=1920,
                target_height=1080,
                fps=30,
            )

            self.assertTrue(rendered_file.exists())
            self.assertGreater(rendered_file.stat().st_size, 0)
            actual_duration = get_video_duration(rendered_file)
            self.assertAlmostEqual(actual_duration, 3.5, delta=0.1)

            # Verify trim calculations
            self.assertEqual(trim_end - trim_start, 3.5)
            self.assertGreaterEqual(trim_start, 0.0)

    def test_render_scene_clip_portrait_9_16(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            source_file = _create_synthetic_video(temp_path / "source_land.mp4", duration=6.0, width=1920, height=1080, fps=24)
            rendered_file = temp_path / "rendered_port.mp4"

            # Render 9:16 portrait (1080x1920)
            render_scene_clip(
                source_path=source_file,
                destination_path=rendered_file,
                scene_duration=2.0,
                target_width=1080,
                target_height=1920,
                fps=30,
            )

            self.assertTrue(rendered_file.exists())
            actual_duration = get_video_duration(rendered_file)
            self.assertAlmostEqual(actual_duration, 2.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
