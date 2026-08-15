from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import pymupdf
from PIL import Image

from app.models.evidence import EvidenceBBox
from app.services.evidence_renderer import (
    apply_highlight_overlay,
    compose_document_frame,
    compose_excerpt_card_frame,
    compute_evidence_spec_fingerprint,
    render_evidence_scene_video,
    render_pdf_page_to_image,
    validate_rendered_evidence_clip,
)


def _create_synthetic_test_pdf(dest_path: Path) -> Path:
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 100), "OFFICIAL GOVERNMENT REPORT", fontsize=18)
    p.insert_text((50, 150), "Retirement age threshold is officially set to 67.", fontsize=14)
    doc.save(str(dest_path))
    doc.close()
    return dest_path


class TestEvidenceRenderer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="evidence_rend_test_")
        self.pdf_path = Path(self.temp_dir) / "evidence_doc.pdf"
        _create_synthetic_test_pdf(self.pdf_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_rasterize_page_and_apply_highlight(self):
        page_img = render_pdf_page_to_image(self.pdf_path, page_number=1, target_long_edge=1200)
        self.assertIsInstance(page_img, Image.Image)
        self.assertGreater(page_img.width, 400)
        self.assertGreater(page_img.height, 400)

        boxes = [EvidenceBBox(x=0.08, y=0.18, width=0.6, height=0.04)]
        annotated = apply_highlight_overlay(page_img, boxes)
        self.assertEqual(annotated.size, page_img.size)

    def test_compose_document_frame(self):
        page_img = render_pdf_page_to_image(self.pdf_path, page_number=1, target_long_edge=1000)
        frame = compose_document_frame(
            annotated_page_img=page_img,
            width=640,
            height=360,
            title="Official Government Report",
            publisher="Social Security Administration",
            trust="official",
            license_info="Public Domain",
        )
        self.assertEqual(frame.size, (640, 360))

    def test_compose_excerpt_card_frame(self):
        frame = compose_excerpt_card_frame(
            width=640,
            height=360,
            title="IRS Retirement Publication",
            publisher="Internal Revenue Service",
            excerpt_text="The IRA contribution limit for 2026 is $7,000.",
            highlight_target="$7,000",
            trust="official",
        )
        self.assertEqual(frame.size, (640, 360))

    def test_render_and_validate_evidence_video(self):
        page_img = render_pdf_page_to_image(self.pdf_path, page_number=1, target_long_edge=800)
        frame = compose_document_frame(
            annotated_page_img=page_img,
            width=640,
            height=360,
            title="Test Evidence Scene",
            publisher="Test Publisher",
        )
        out_video = Path(self.temp_dir) / "S001_DOCUMENT.mp4"
        render_evidence_scene_video(
            composite_image=frame,
            output_mp4_path=out_video,
            duration_frames=30,
            fps=30,
            width=640,
            height=360,
        )
        self.assertTrue(out_video.exists())
        self.assertGreater(out_video.stat().st_size, 0)

        actual_duration = validate_rendered_evidence_clip(
            rendered_path=out_video,
            expected_duration_frames=30,
            expected_width=640,
            expected_height=360,
            expected_fps=30,
        )
        self.assertAlmostEqual(actual_duration, 1.0, delta=0.1)

    def test_spec_fingerprint_determinism(self):
        fp1 = compute_evidence_spec_fingerprint(
            scene_id="S001",
            search_query="social security",
            highlight_target="age 65",
            source_id="SRC001",
            source_sha256="abcdef123456",
            page_number=2,
            match_type="exact_target",
            highlight_boxes=[EvidenceBBox(x=0.1, y=0.2, width=0.3, height=0.05)],
            duration_frames=30,
            fps=30,
            width=1920,
            height=1080,
            render_mode="document_page",
        )
        fp2 = compute_evidence_spec_fingerprint(
            scene_id="S001",
            search_query="social security",
            highlight_target="age 65",
            source_id="SRC001",
            source_sha256="abcdef123456",
            page_number=2,
            match_type="exact_target",
            highlight_boxes=[EvidenceBBox(x=0.1, y=0.2, width=0.3, height=0.05)],
            duration_frames=30,
            fps=30,
            width=1920,
            height=1080,
            render_mode="document_page",
        )
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)


if __name__ == "__main__":
    unittest.main()
