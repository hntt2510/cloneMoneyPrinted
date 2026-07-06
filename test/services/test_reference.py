import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import config
from app.models.schema import VideoParams
from app.services import reference


class TestReferenceImageSearch(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.original_proxy_config = dict(config.proxy)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        config.proxy.clear()
        config.proxy.update(self.original_proxy_config)

    def test_search_pexels_images_uses_tls_and_parses_metadata(self):
        config.app["pexels_api_keys"] = ["pexels-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "photos": [
                    {
                        "src": {
                            "large2x": "https://images.example/large2x.jpg",
                            "large": "https://images.example/large.jpg",
                        },
                        "url": "https://www.pexels.com/photo/example",
                        "photographer": "Alice",
                        "alt": "Old house",
                    }
                ]
            }
        )

        with patch("app.services.reference.requests.get", return_value=fake_response) as get:
            results = reference.search_images_pexels("old house")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "pexels")
        self.assertEqual(results[0]["image_url"], "https://images.example/large2x.jpg")
        self.assertEqual(results[0]["source_url"], "https://www.pexels.com/photo/example")
        self.assertEqual(results[0]["author"], "Alice")
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_search_pixabay_images_uses_tls_and_parses_metadata(self):
        config.app["pixabay_api_keys"] = ["pixabay-key"]
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "hits": [
                    {
                        "largeImageURL": "https://images.example/pixabay.jpg",
                        "pageURL": "https://pixabay.com/photos/example",
                        "user": "Bob",
                        "tags": "history, building",
                    }
                ]
            }
        )

        with patch("app.services.reference.requests.get", return_value=fake_response) as get:
            results = reference.search_images_pixabay("history building")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "pixabay")
        self.assertEqual(results[0]["image_url"], "https://images.example/pixabay.jpg")
        self.assertEqual(results[0]["source_url"], "https://pixabay.com/photos/example")
        self.assertEqual(results[0]["author"], "Bob")
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_search_wikimedia_images_uses_tls_and_parses_license_metadata(self):
        config.app.pop("tls_verify", None)
        config.proxy.clear()

        fake_response = SimpleNamespace(
            json=lambda: {
                "query": {
                    "pages": {
                        "1": {
                            "title": "File:Example.jpg",
                            "imageinfo": [
                                {
                                    "thumburl": "https://upload.wikimedia.org/example-thumb.jpg",
                                    "url": "https://upload.wikimedia.org/example.jpg",
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                        "Artist": {"value": "<b>Carol</b>"},
                                        "ObjectName": {"value": "Historic building"},
                                    },
                                }
                            ],
                        }
                    }
                }
            }
        )

        with patch("app.services.reference.requests.get", return_value=fake_response) as get:
            results = reference.search_images_wikimedia("historic building")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "wikimedia")
        self.assertEqual(
            results[0]["image_url"],
            "https://upload.wikimedia.org/example-thumb.jpg",
        )
        self.assertEqual(results[0]["source_url"], "https://commons.wikimedia.org/wiki/File:Example.jpg")
        self.assertEqual(results[0]["author"], "Carol")
        self.assertEqual(results[0]["license"], "CC BY-SA 4.0")
        self.assertTrue(get.call_args.kwargs["verify"])

    def test_build_reference_plan_falls_back_when_llm_json_fails(self):
        with patch.object(reference.llm, "_generate_response", return_value="{bad json"), patch.object(
            reference.llm,
            "generate_terms",
            return_value=["opening topic", "second topic"],
        ):
            scenes = reference.build_reference_plan(
                video_subject="test subject",
                video_script="First sentence. Second sentence.",
                max_items=2,
            )

        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0]["search_term"], "opening topic")
        self.assertEqual(scenes[1]["search_term"], "second topic")
        self.assertIn("First", scenes[0]["narration"])


class TestReferenceOverlayRender(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="reference-overlay-")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_render_reference_overlay_creates_nonempty_video(self):
        try:
            from moviepy import ColorClip
        except Exception as exc:
            self.skipTest(f"moviepy unavailable: {exc}")

        base_path = os.path.join(self.temp_dir, "base.mp4")
        output_path = os.path.join(self.temp_dir, "reference.mp4")
        image_path = os.path.join(self.temp_dir, "reference.png")

        Image.new("RGB", (240, 160), (210, 210, 190)).save(image_path)
        clip = ColorClip(size=(320, 240), color=(20, 24, 28), duration=1)
        try:
            clip.write_videofile(
                base_path,
                fps=5,
                codec="libx264",
                audio=False,
                logger=None,
            )
        except Exception as exc:
            self.skipTest(f"moviepy could not create test video: {exc}")
        finally:
            clip.close()

        params = VideoParams(video_subject="test", reference_mode_enabled=True)
        plan = [
            {
                "image_path": image_path,
                "start": 0,
                "end": 0.8,
                "title": "Old Paper",
                "narration": "A concise explained label.",
                "provider": "test",
            }
        ]

        with patch.object(reference.video_service, "_get_configured_video_codec", return_value="libx264"):
            result = reference.render_reference_overlay(
                video_path=base_path,
                output_path=output_path,
                reference_plan=plan,
                params=params,
                threads=1,
            )

        self.assertEqual(result, output_path)
        self.assertTrue(os.path.isfile(output_path))
        self.assertGreater(os.path.getsize(output_path), 0)


if __name__ == "__main__":
    unittest.main()
