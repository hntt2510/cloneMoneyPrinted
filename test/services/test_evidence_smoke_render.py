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
    render_evidence_scene_video,
    render_pdf_page_to_image,
    validate_rendered_evidence_clip,
)


def _create_synthetic_test_pdf(dest_path: Path) -> Path:
    doc = pymupdf.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((50, 100), "FEDERAL RETIREMENT BOARD", fontsize=20)
    p.insert_text((50, 150), "Section 402(b): Normal retirement age is officially established at 67.", fontsize=14)
    p.insert_text((50, 180), "Early distributions before age 59.5 are subject to a 10% penalty.", fontsize=12)
    doc.save(str(dest_path))
    doc.close()
    return dest_path


class TestEvidenceSmokeRender(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="evidence_smoke_")
        self.pdf_path = Path(self.temp_dir) / "evidence_report.pdf"
        _create_synthetic_test_pdf(self.pdf_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_smoke_render_640x360_document(self):
        page_img = render_pdf_page_to_image(self.pdf_path, page_number=1, target_long_edge=1000)
        boxes = [EvidenceBBox(x=0.08, y=0.18, width=0.75, height=0.04)]
        annotated = apply_highlight_overlay(page_img, boxes)

        frame = compose_document_frame(
            annotated_page_img=annotated,
            width=640,
            height=360,
            title="Federal Retirement Board Report",
            publisher="Federal Retirement Board",
            trust="official",
        )

        out_mp4 = Path(self.temp_dir) / "S001_640x360.mp4"
        render_evidence_scene_video(
            composite_image=frame,
            output_mp4_path=out_mp4,
            duration_frames=30,
            fps=30,
            width=640,
            height=360,
        )

        duration = validate_rendered_evidence_clip(
            rendered_path=out_mp4,
            expected_duration_frames=30,
            expected_width=640,
            expected_height=360,
            expected_fps=30,
        )
        self.assertAlmostEqual(duration, 1.0, delta=0.05)

    def test_smoke_render_1920x1080_full_hd_document(self):
        page_img = render_pdf_page_to_image(self.pdf_path, page_number=1, target_long_edge=2000)
        boxes = [EvidenceBBox(x=0.08, y=0.18, width=0.75, height=0.04)]
        annotated = apply_highlight_overlay(page_img, boxes)

        frame = compose_document_frame(
            annotated_page_img=annotated,
            width=1920,
            height=1080,
            title="Federal Retirement Board Report",
            publisher="Federal Retirement Board",
            trust="official",
            license_info="Public Domain",
        )

        out_mp4 = Path(self.temp_dir) / "S002_1920x1080.mp4"
        render_evidence_scene_video(
            composite_image=frame,
            output_mp4_path=out_mp4,
            duration_frames=30,
            fps=30,
            width=1920,
            height=1080,
        )

        duration = validate_rendered_evidence_clip(
            rendered_path=out_mp4,
            expected_duration_frames=30,
            expected_width=1920,
            expected_height=1080,
            expected_fps=30,
        )
        self.assertAlmostEqual(duration, 1.0, delta=0.05)

    def test_smoke_render_1920x1080_full_hd_excerpt_card(self):
        frame = compose_excerpt_card_frame(
            width=1920,
            height=1080,
            title="Internal Revenue Bulletin 2026",
            publisher="Internal Revenue Service",
            excerpt_text="The annual IRA contribution limit is established at $7,000 for tax year 2026.",
            highlight_target="$7,000",
            trust="official",
            license_info="U.S. Government Work",
        )

        out_mp4 = Path(self.temp_dir) / "S003_excerpt_card.mp4"
        render_evidence_scene_video(
            composite_image=frame,
            output_mp4_path=out_mp4,
            duration_frames=30,
            fps=30,
            width=1920,
            height=1080,
        )

        duration = validate_rendered_evidence_clip(
            rendered_path=out_mp4,
            expected_duration_frames=30,
            expected_width=1920,
            expected_height=1080,
            expected_fps=30,
        )
        self.assertAlmostEqual(duration, 1.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
