import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import (
    SUPPORTED_VIDEO_SOURCES,
    VideoAspect,
    VideoParams,
    VideoSource,
    normalize_saved_video_source,
)


class TestVideoAspect(unittest.TestCase):
    def test_to_resolution_known_aspects(self):
        self.assertEqual(VideoAspect.landscape.to_resolution(), (1920, 1080))
        self.assertEqual(VideoAspect.portrait.to_resolution(), (1080, 1920))
        self.assertEqual(VideoAspect.square.to_resolution(), (1080, 1080))

    def test_to_resolution_rejects_unsupported_value(self):
        with self.assertRaises(ValueError):
            VideoAspect.to_resolution("4:5")


class TestVideoSource(unittest.TestCase):
    def test_supported_sources_are_accepted(self):
        for source in SUPPORTED_VIDEO_SOURCES:
            with self.subTest(source=source):
                params = VideoParams(video_subject="test", video_source=source)
                self.assertEqual(params.video_source.value, source)

    def test_unsupported_sources_are_rejected(self):
        for source in ("douyin", "bilibili", "xiaohongshu", "random_unknown"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    VideoParams(video_subject="test", video_source=source)

    def test_saved_source_migration_defaults_to_pexels(self):
        self.assertEqual(normalize_saved_video_source("douyin"), VideoSource.pexels.value)
        self.assertEqual(normalize_saved_video_source("random_unknown"), "pexels")
        self.assertEqual(normalize_saved_video_source("PIXABAY"), "pixabay")


if __name__ == "__main__":
    unittest.main()
