import json
import os
import shutil
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
    RenderValidationError,
    acquire_broll_scene,
    collect_and_rank_candidates,
    collect_and_rank_candidates_for_query,
    download_candidate,
    get_video_duration,
    render_scene_clip,
    sanitize_url_for_persistence,
    score_candidate,
    validate_rendered_clip,
)
from app.services.stock_providers import StockSearchResult
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
    source_url: str | None = "https://example.com/src1",
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
            download_url="https://dl.example/v1.mp4",
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
        cand_a = _candidate(
            cid="a",
            query="senior couple retirement",
            title="Senior couple enjoying retirement",
            tags=["senior", "couple", "retirement", "park"],
            width=1920,
            height=1080,
        )
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


class TestQueryFallbackStagedAcquisition(unittest.TestCase):
    def test_fallback_query_succeeds_after_primary_candidates_exhausted(self):
        """Primary query returns 10 candidates that all fail download;

        fallback query 1 returns 1 candidate that succeeds.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            synthetic_source = _create_synthetic_video(task_dir / "valid_fallback.mp4", duration=8.0)

            project = _sample_project()
            cue = project.visual_cues[0]
            ctx = BrollSelectionContext()

            # Primary query yields 10 candidates
            primary_candidates = [
                _candidate(cid=f"prim-{i}", query="senior couple", download_url=f"https://dl.example/prim-{i}.mp4")
                for i in range(10)
            ]
            # Fallback query yields 1 candidate
            fallback_candidates = [
                _candidate(cid="fall-1", query="retiree healthcare", download_url="https://dl.example/fall-1.mp4")
            ]

            def mock_search_detailed(provider, query, **kwargs):
                if query == "senior couple":
                    return StockSearchResult(provider=provider, query=query, candidates=primary_candidates if provider == "pexels" else [])
                if query == "retiree healthcare":
                    return StockSearchResult(provider=provider, query=query, candidates=fallback_candidates if provider == "pexels" else [])
                return StockSearchResult(provider=provider, query=query, candidates=[])

            download_attempts = []

            def mock_download(candidate, dest_path):
                download_attempts.append(candidate.id)
                if candidate.id.startswith("prim-"):
                    raise ValueError(f"Download failed for primary {candidate.id}")
                # Fallback succeeds
                shutil.copyfile(synthetic_source, dest_path)
                return Path(dest_path)

            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search_detailed), \
                 patch("app.services.broll.download_candidate", side_effect=mock_download):
                asset = acquire_broll_scene(cue, project, task_dir, ctx)

            # Verified: All 10 primary candidates were attempted and failed, then fallback query candidate was attempted and succeeded!
            self.assertEqual(len(download_attempts), 11)
            self.assertEqual(download_attempts[-1], "fall-1")
            self.assertEqual(asset.candidate_id, "fall-1")
            self.assertEqual(asset.query_used, "retiree healthcare")
            self.assertEqual(asset.metadata["attempts"], 11)


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

            def mock_search_detailed(provider, query, **kwargs):
                if query == "senior couple" and provider == "pexels":
                    return StockSearchResult(provider="pexels", query=query, candidates=[cand1, cand2, cand3])
                return StockSearchResult(provider=provider, query=query, candidates=[])

            def mock_download(candidate, dest_path):
                download_attempts.append(candidate.id)
                if candidate.id == "c1":
                    raise ValueError("Network drop on candidate 1")
                shutil.copyfile(synthetic_source, dest_path)
                return Path(dest_path)

            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search_detailed), \
                 patch("app.services.broll.download_candidate", side_effect=mock_download):
                asset = acquire_broll_scene(cue, project, task_dir, ctx)

            # c1 failed, c2 succeeded -> c3 was never downloaded
            self.assertEqual(download_attempts, ["c1", "c2"])
            self.assertEqual(asset.candidate_id, "c2")
            self.assertTrue(Path(asset.rendered_file).exists())


class TestExactDurationAndSceneRendering(unittest.TestCase):
    def test_render_scene_clip_exact_duration_and_full_frame_landscape(self):
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
            actual_duration = validate_rendered_clip(
                rendered_path=rendered_file,
                scene_duration=3.5,
                target_width=1920,
                target_height=1080,
                target_fps=30,
            )
            self.assertAlmostEqual(actual_duration, 3.5, delta=0.05)
            self.assertEqual(trim_end - trim_start, 3.5)

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
            actual_duration = validate_rendered_clip(
                rendered_path=rendered_file,
                scene_duration=2.0,
                target_width=1080,
                target_height=1920,
                target_fps=30,
            )
            self.assertAlmostEqual(actual_duration, 2.0, delta=0.05)

    def test_render_validation_rejects_excessive_duration_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            short_clip = _create_synthetic_video(temp_path / "short.mp4", duration=2.0, width=1920, height=1080, fps=30)

            with self.assertRaises(RenderValidationError):
                validate_rendered_clip(
                    rendered_path=short_clip,
                    scene_duration=4.0,
                    target_width=1920,
                    target_height=1080,
                    target_fps=30,
                )

    def test_render_validation_rejects_dimension_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            clip_720p = _create_synthetic_video(temp_path / "720p.mp4", duration=3.0, width=1280, height=720, fps=30)

            with self.assertRaises(RenderValidationError):
                validate_rendered_clip(
                    rendered_path=clip_720p,
                    scene_duration=3.0,
                    target_width=1920,
                    target_height=1080,
                    target_fps=30,
                )


class TestResumeAndProvenance(unittest.TestCase):
    def test_resumed_scene_registers_duplicate_memory_for_subsequent_scenes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            s001_rendered = _create_synthetic_video(task_dir / "broll" / "S001" / "rendered.mp4", duration=4.0, width=1920, height=1080, fps=30)
            s001_meta = task_dir / "broll" / "S001" / "metadata.json"
            existing_asset = SelectedBrollAsset(
                scene_id="S001",
                provider="pexels",
                provider_asset_id="asset-100",
                query_used="senior couple",
                candidate_id="pexels-asset-100",
                download_url="https://dl.example/video100.mp4",
                source_file="source.mp4",
                rendered_file=str(s001_rendered.resolve()),
                source_duration=8.0,
                trim_start=2.0,
                trim_end=6.0,
                scene_duration=4.0,
                width=1920,
                height=1080,
            )
            s001_meta.write_text(json.dumps(existing_asset.model_dump(mode="json")), encoding="utf-8")

            project = _sample_project()
            cue_s001 = project.visual_cues[0]
            ctx = BrollSelectionContext()

            # Resume S001
            resumed_asset = acquire_broll_scene(cue_s001, project, task_dir, ctx)
            self.assertEqual(resumed_asset.provider_asset_id, "asset-100")

            # Now verify that context remembered asset-100 as duplicate
            dup_candidate = _candidate(cid="asset-100", provider="pexels", download_url="https://dl.example/video100.mp4")
            self.assertTrue(ctx.is_duplicate(dup_candidate))

    def test_corrupt_resume_artifact_triggers_fresh_reacquisition(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            scene_dir = task_dir / "broll" / "S001"
            scene_dir.mkdir(parents=True, exist_ok=True)
            (scene_dir / "rendered.mp4").write_text("corrupted content", encoding="utf-8")
            (scene_dir / "metadata.json").write_text("{invalid json", encoding="utf-8")

            synthetic_source = _create_synthetic_video(task_dir / "valid_source.mp4", duration=8.0)
            project = _sample_project()
            cue = project.visual_cues[0]
            ctx = BrollSelectionContext()

            cand = _candidate(cid="fresh-1", query="senior couple", download_url="https://dl.example/fresh.mp4")

            def mock_search_detailed(provider, query, **kwargs):
                return StockSearchResult(provider=provider, query=query, candidates=[cand] if provider == "pexels" else [])

            def mock_download(candidate, dest_path):
                shutil.copyfile(synthetic_source, dest_path)
                return Path(dest_path)

            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search_detailed), \
                 patch("app.services.broll.download_candidate", side_effect=mock_download):
                asset = acquire_broll_scene(cue, project, task_dir, ctx)

            self.assertEqual(asset.candidate_id, "fresh-1")
            self.assertTrue((scene_dir / "rendered.mp4").exists())
            self.assertGreater((scene_dir / "rendered.mp4").stat().st_size, 0)

    def test_signed_download_token_is_not_persisted_in_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            synthetic_source = _create_synthetic_video(task_dir / "source.mp4", duration=8.0)
            project = _sample_project()
            cue = project.visual_cues[0]
            ctx = BrollSelectionContext()

            secret_token = "SECRET_SIGNATURE_TOKEN_XYZ_12345"
            raw_signed_url = f"https://signed-cdn.example.com/video.mp4?token={secret_token}&expires=9999"

            cand = _candidate(cid="signed-1", query="senior couple", download_url=raw_signed_url)

            def mock_search_detailed(provider, query, **kwargs):
                return StockSearchResult(provider=provider, query=query, candidates=[cand] if provider == "pexels" else [])

            def mock_download(candidate, dest_path):
                self.assertEqual(candidate.download_url, raw_signed_url)
                shutil.copyfile(synthetic_source, dest_path)
                return Path(dest_path)

            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search_detailed), \
                 patch("app.services.broll.download_candidate", side_effect=mock_download):
                asset = acquire_broll_scene(cue, project, task_dir, ctx)

            self.assertNotIn(secret_token, asset.download_url)
            self.assertEqual(asset.download_url, "https://signed-cdn.example.com/video.mp4")

            meta_json = (task_dir / "broll" / "S001" / "metadata.json").read_text(encoding="utf-8")
            self.assertNotIn(secret_token, meta_json)

    def test_providers_searched_recorded_when_all_searches_return_zero_results(self):
        """When all 3 providers return valid empty results, providers_searched contains all 3,

        candidate_ids_attempted is empty, and errors is empty.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            project = _sample_project()
            cue = project.visual_cues[0]
            ctx = BrollSelectionContext()

            def mock_search_detailed(provider, query, **kwargs):
                return StockSearchResult(provider=provider, query=query, candidates=[])

            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search_detailed):
                with self.assertRaises(BrollAcquisitionError) as cm:
                    acquire_broll_scene(cue, project, task_dir, ctx)

            diag = cm.exception.diagnostics
            self.assertEqual(diag["scene_id"], "S001")
            self.assertEqual(diag["providers_searched"], ["pexels", "pixabay", "coverr"])
            self.assertEqual(diag["candidate_ids_attempted"], [])
            self.assertEqual(diag["errors"], [])

    def test_provider_error_recorded_and_fallback_provider_succeeds(self):
        """When Pexels fails with HTTP 500, Pixabay returns zero, Coverr succeeds."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_dir = Path(tmp_dir)
            synthetic_source = _create_synthetic_video(task_dir / "coverr_winner.mp4", duration=8.0)
            project = _sample_project()
            cue = project.visual_cues[0]
            ctx = BrollSelectionContext()

            coverr_cand = _candidate(cid="cov-1", provider="coverr", query="senior couple", download_url="https://dl.example/cov.mp4")

            def mock_search_detailed(provider, query, **kwargs):
                if provider == "pexels":
                    return StockSearchResult(provider="pexels", query=query, candidates=[], error="pexels: HTTP 500")
                if provider == "pixabay":
                    return StockSearchResult(provider="pixabay", query=query, candidates=[])
                if provider == "coverr":
                    return StockSearchResult(provider="coverr", query=query, candidates=[coverr_cand])
                return StockSearchResult(provider=provider, query=query, candidates=[])

            def mock_download(candidate, dest_path):
                shutil.copyfile(synthetic_source, dest_path)
                return Path(dest_path)

            with patch("app.services.broll.search_stock_candidates_detailed", side_effect=mock_search_detailed), \
                 patch("app.services.broll.download_candidate", side_effect=mock_download):
                asset = acquire_broll_scene(cue, project, task_dir, ctx)

            self.assertEqual(asset.provider, "coverr")
            self.assertEqual(asset.candidate_id, "cov-1")


if __name__ == "__main__":
    unittest.main()
