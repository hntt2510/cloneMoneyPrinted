import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.config import config
from app.models.schema import VideoAspect
from app.services import stock_providers


class TestStockProviders(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def test_forbidden_providers_rejected(self):
        for forbidden in ("douyin", "bilibili", "xiaohongshu", "youtube", "tiktok"):
            with self.assertRaises(ValueError):
                stock_providers.search_stock_candidates(forbidden, "query")

    def test_search_pexels_normalizes_metadata_without_inventing_license(self):
        config.app["pexels_api_keys"] = ["test-pexels-key"]
        fake_response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "videos": [
                    {
                        "id": 12345,
                        "duration": 12.5,
                        "url": "https://www.pexels.com/video/12345/",
                        "user": {"name": "Photographer John"},
                        "video_files": [
                            {
                                "id": 1,
                                "quality": "hd",
                                "file_type": "video/mp4",
                                "width": 1920,
                                "height": 1080,
                                "fps": 30.0,
                                "link": "https://download.pexels.com/video-12345-hd.mp4",
                            }
                        ],
                    }
                ]
            },
        )

        with patch("app.services.stock_providers.requests.get", return_value=fake_response):
            candidates = stock_providers.search_stock_candidates("pexels", "senior retirement", minimum_duration=5.0)

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.id, "pexels-12345")
        self.assertEqual(c.provider, "pexels")
        self.assertEqual(c.provider_asset_id, "12345")
        self.assertEqual(c.query, "senior retirement")
        self.assertEqual(c.download_url, "https://download.pexels.com/video-12345-hd.mp4")
        self.assertEqual(c.source_url, "https://www.pexels.com/video/12345/")
        self.assertEqual(c.duration, 12.5)
        self.assertEqual(c.width, 1920)
        self.assertEqual(c.height, 1080)
        self.assertEqual(c.fps, 30.0)
        self.assertEqual(c.author, "Photographer John")
        self.assertIsNone(c.license)

    def test_search_pixabay_preserves_explicit_license_if_provided(self):
        config.app["pixabay_api_keys"] = ["test-pixabay-key"]
        fake_response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "hits": [
                    {
                        "id": 67890,
                        "duration": 15,
                        "pageURL": "https://pixabay.com/videos/retirement-67890/",
                        "tags": "couple, retirement, sunset, beach",
                        "user": "artist_alice",
                        "license": "Custom Free License",
                        "videos": {
                            "large": {
                                "url": "https://download.pixabay.com/video-large.mp4",
                                "width": 1920,
                                "height": 1080,
                            }
                        },
                    }
                ]
            },
        )

        with patch("app.services.stock_providers.requests.get", return_value=fake_response):
            candidates = stock_providers.search_stock_candidates("pixabay", "couple retirement", minimum_duration=5.0)

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.id, "pixabay-67890")
        self.assertEqual(c.provider, "pixabay")
        self.assertEqual(c.provider_asset_id, "67890")
        self.assertEqual(c.source_url, "https://pixabay.com/videos/retirement-67890/")
        self.assertEqual(c.license, "Custom Free License")

    def test_search_coverr_does_not_fabricate_source_url_when_missing(self):
        config.app["coverr_api_keys"] = ["test-coverr-key"]
        fake_response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "hits": [
                    {
                        "id": "coverr-medicare-101",
                        "duration": "14.2",
                        "title": "Senior couple reviewing finances",
                        "description": "An older couple sitting at a table looking over medical documents",
                        "tags": ["senior", "finance", "healthcare"],
                        "author": "Coverr Studios",
                        "width": 1920,
                        "height": 1080,
                        "urls": {
                            "mp4_download": "https://download.coverr.co/video-signed.mp4?token=abc",
                            "mp4": "https://download.coverr.co/video-signed.mp4?token=abc",
                        },
                    }
                ]
            },
        )

        with patch("app.services.stock_providers.requests.get", return_value=fake_response):
            candidates = stock_providers.search_stock_candidates("coverr", "senior finances")

        self.assertEqual(len(candidates), 1)
        c = candidates[0]
        self.assertEqual(c.id, "coverr-coverr-medicare-101")
        self.assertEqual(c.provider, "coverr")
        self.assertEqual(c.provider_asset_id, "coverr-medicare-101")
        self.assertEqual(c.title, "Senior couple reviewing finances")
        self.assertEqual(c.duration, 14.2)
        self.assertIn("finance", c.tags)
        self.assertIsNone(c.source_url)
        self.assertIsNone(c.license)

    def test_provider_http_error_returns_empty_and_does_not_raise(self):
        config.app["pexels_api_keys"] = ["test-pexels-key"]
        fake_response = SimpleNamespace(status_code=500, json=lambda: {"error": "Server error"})

        with patch("app.services.stock_providers.requests.get", return_value=fake_response):
            candidates = stock_providers.search_stock_candidates("pexels", "any query")
        self.assertEqual(candidates, [])

    def test_missing_api_key_returns_empty_and_does_not_raise(self):
        config.app.pop("pexels_api_keys", None)
        candidates = stock_providers.search_stock_candidates("pexels", "any query")
        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
