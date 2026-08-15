from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import pymupdf

from app.models.evidence import (
    EvidenceBBox,
    EvidenceCandidate,
    EvidenceSource,
    EvidenceSourceKind,
    EvidenceSourceTrust,
)
from app.models.project import DocumentPayload, VisualCue, VisualPurpose, VisualType
from app.services.evidence_selector import (
    extract_webpage_evidence_passage,
    inspect_and_extract_pdf_evidence,
    rank_and_select_candidate,
    score_evidence_candidate,
)


def _create_synthetic_test_pdf(dest_path: Path) -> Path:
    """Create a 3-page synthetic PDF for deterministic test evaluation."""
    doc = pymupdf.open()

    # Page 1: General intro
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((50, 100), "CHAPTER 1: Overview of Federal Benefits", fontsize=16)
    p1.insert_text((50, 140), "This report outlines key retirement policy considerations.", fontsize=12)

    # Page 2: Target evidence
    p2 = doc.new_page(width=612, height=792)
    p2.insert_text((50, 100), "CHAPTER 2: Medicare and Social Security Rules", fontsize=16)
    p2.insert_text((50, 140), "Medicare eligibility generally begins at age 65 for qualified individuals.", fontsize=12)
    p2.insert_text((50, 170), "Early claiming before full retirement age results in permanent reduction.", fontsize=12)

    # Page 3: Appendix
    p3 = doc.new_page(width=612, height=792)
    p3.insert_text((50, 100), "APPENDIX A: Glossary and Historical Data", fontsize=16)
    p3.insert_text((50, 140), "Historical indices from 1980 through 2024.", fontsize=12)

    doc.save(str(dest_path))
    doc.close()
    return dest_path


class TestEvidenceSelector(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="evidence_sel_test_")
        self.pdf_path = Path(self.temp_dir) / "sample_policy.pdf"
        _create_synthetic_test_pdf(self.pdf_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pdf_exact_target_match_and_bounding_rect(self):
        p_num, p_count, matched_txt, m_type, bboxes, body_meta = inspect_and_extract_pdf_evidence(
            pdf_path=self.pdf_path,
            highlight_target="age 65",
            search_query="medicare eligibility age",
        )
        self.assertEqual(p_count, 3)
        self.assertEqual(p_num, 2)  # Page 2 contains "age 65"
        self.assertEqual(m_type, "exact_target")
        self.assertIn("Medicare eligibility generally begins at age 65", matched_txt)
        self.assertTrue(len(bboxes) >= 1)
        b = bboxes[0]
        self.assertTrue(0.0 <= b.x <= 1.0)
        self.assertTrue(0.0 <= b.y <= 1.0)
        self.assertTrue(0.0 < b.width <= 1.0)
        self.assertTrue(0.0 < b.height <= 1.0)

    def test_pdf_query_relevance_fallback(self):
        # Query matching page 1 without exact highlight target
        p_num, p_count, matched_txt, m_type, bboxes, body_meta = inspect_and_extract_pdf_evidence(
            pdf_path=self.pdf_path,
            highlight_target=None,
            search_query="overview of federal benefits report considerations",
        )
        self.assertEqual(p_num, 1)
        self.assertEqual(m_type, "query_relevance")
        self.assertEqual(len(bboxes), 0)  # No fake bounding box

    def test_webpage_exact_excerpt_extraction(self):
        html_doc = """
        <html><head><title>IRS Contribution Limits</title></head>
        <body>
            <p>For tax year 2026, the IRA contribution limit is $7,000.</p>
            <p>Catch-up contributions allow an additional $1,000 for individuals aged 50 and older.</p>
        </body></html>
        """
        title, pub, full_txt, snippet, m_type, body_meta = extract_webpage_evidence_passage(
            html_text=html_doc,
            source_url="https://www.irs.gov/retirement/limits",
            highlight_target="$7,000",
            search_query="IRA contribution limit 2026",
        )
        self.assertEqual(m_type, "exact_target")
        self.assertIn("the IRA contribution limit is $7,000", snippet)
        # Verify exact excerpt words are preserved without modification
        self.assertEqual(snippet, "For tax year 2026, the IRA contribution limit is $7,000.")

    def test_evidence_scoring_and_ranking(self):
        cue = VisualCue(
            id="S001",
            order=1,
            visual_type=VisualType.document,
            purpose=VisualPurpose.evidence,
            start=0.0,
            end=2.0,
            narration="Medicare eligibility begins at age 65.",
            payload={"search_query": "Medicare eligibility age 65", "source_hint": "SSA Report", "highlight_target": "age 65"},
        )
        payload = DocumentPayload.model_validate(cue.payload)

        # Candidate A: Official source with exact target match
        src_a = EvidenceSource(
            id="SRC_OFFICIAL",
            kind=EvidenceSourceKind.pdf,
            url="https://ssa.gov/medicare.pdf",
            title="Official Medicare Eligibility Rules",
            publisher="Social Security Administration",
            trust=EvidenceSourceTrust.official,
            tags=["medicare", "age 65", "eligibility"],
        )
        cand_a = EvidenceCandidate(
            id="A_p2",
            source_id="SRC_OFFICIAL",
            kind=EvidenceSourceKind.pdf,
            title=src_a.title,
            publisher=src_a.publisher,
            trust=src_a.trust,
            query=payload.search_query,
            page_number=2,
            matched_text="Medicare eligibility generally begins at age 65",
            match_type="exact_target",
            highlight_boxes=[EvidenceBBox(x=0.1, y=0.15, width=0.3, height=0.05)],
            score=0.0,
        )
        score_a, breakdown_a = score_evidence_candidate(
            cue=cue, payload=payload, source=src_a, match_type="exact_target", matched_text=cand_a.matched_text
        )
        cand_a.score = score_a
        cand_a.score_breakdown = breakdown_a

        # Candidate B: Licensed generic source without exact target
        src_b = EvidenceSource(
            id="SRC_GENERIC",
            kind=EvidenceSourceKind.image,
            url="https://stock.example.com/building.jpg",
            title="Social Security Administration Headquarters Building Exterior",
            publisher="Stock Photography Corp",
            trust=EvidenceSourceTrust.licensed,
            tags=["building", "exterior", "government"],
        )
        cand_b = EvidenceCandidate(
            id="B_img",
            source_id="SRC_GENERIC",
            kind=EvidenceSourceKind.image,
            title=src_b.title,
            publisher=src_b.publisher,
            trust=src_b.trust,
            query=payload.search_query,
            matched_text=src_b.title,
            match_type="query_relevance",
            highlight_boxes=[],
            score=0.0,
        )
        score_b, breakdown_b = score_evidence_candidate(
            cue=cue, payload=payload, source=src_b, match_type="query_relevance", matched_text=cand_b.matched_text
        )
        cand_b.score = score_b
        cand_b.score_breakdown = breakdown_b

        # Candidate A must strictly outscore Candidate B
        self.assertGreater(cand_a.score, cand_b.score)

        selected, fail_reason = rank_and_select_candidate([cand_b, cand_a], evidence_required=True)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.source_id, "SRC_OFFICIAL")

    def test_required_evidence_fails_when_no_candidates(self):
        selected, fail_reason = rank_and_select_candidate([], evidence_required=True)
        self.assertIsNone(selected)
        self.assertIn("No evidence sources available", fail_reason)

    def test_optional_evidence_skips_when_no_candidates(self):
        selected, fail_reason = rank_and_select_candidate([], evidence_required=False)
        self.assertIsNone(selected)
        self.assertIn("optional evidence", fail_reason)

    def test_generic_ssa_building_image_alone_cannot_satisfy_required_evidence(self):
        # A generic image of SSA building without verified evidence text must fail under evidence_required=True
        cand_building = EvidenceCandidate(
            id="SRC_SSA_BLDG_img",
            source_id="SRC_SSA_BLDG",
            kind=EvidenceSourceKind.image,
            title="Social Security Administration Headquarters Building",
            publisher="Stock Photos LLC",
            trust=EvidenceSourceTrust.official,
            query="Medicare eligibility begins at age 65",
            matched_text="Social Security Administration Headquarters Building",
            match_type="query_relevance",
            highlight_boxes=[],
            score=40.0,
        )
        selected, fail_reason = rank_and_select_candidate([cand_building], evidence_required=True)
        self.assertIsNone(selected)
        self.assertIn("not factually defensible", fail_reason)

    def test_approved_user_provided_image_with_quote_hint_allowed(self):
        # User provided image with registered quote_hint has registry_evidence_hint match type and can be selected
        cand_user = EvidenceCandidate(
            id="SRC_CHART_img",
            source_id="SRC_CHART",
            kind=EvidenceSourceKind.image,
            title="Official Medicare Age Chart",
            publisher="SSA",
            trust=EvidenceSourceTrust.user_provided,
            query="Medicare eligibility begins at age 65",
            matched_text="Medicare eligibility begins at age 65",
            match_type="registry_evidence_hint",
            highlight_boxes=[EvidenceBBox(x=0.1, y=0.1, width=0.8, height=0.2)],
            score=55.0,
        )
        selected, fail_reason = rank_and_select_candidate([cand_user], evidence_required=True)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.source_id, "SRC_CHART")
        self.assertEqual(selected.match_type, "registry_evidence_hint")

    def test_pdf_metadata_trap_rejected_when_body_is_unrelated(self):
        # Create PDF whose body is purely unrelated administrative text
        trap_pdf = Path(self.temp_dir) / "trap_policy.pdf"
        doc = pymupdf.open()
        p = doc.new_page(width=612, height=792)
        p.insert_text((50, 100), "This document discusses internal office equipment procurement.", fontsize=14)
        doc.save(str(trap_pdf))
        doc.close()

        p_num, p_count, matched_txt, m_type, bboxes, body_meta = inspect_and_extract_pdf_evidence(
            pdf_path=trap_pdf,
            search_query="Medicare eligibility begins at age 65",
        )
        self.assertEqual(m_type, "none")

        # Candidate with official metadata but match_type="none"
        cand_trap = EvidenceCandidate(
            id="SRC_TRAP_p1",
            source_id="SRC_TRAP",
            kind=EvidenceSourceKind.pdf,
            title="Official Medicare Eligibility Age 65 Report",
            publisher="Social Security Administration",
            trust=EvidenceSourceTrust.official,
            query="Medicare eligibility begins at age 65",
            matched_text=matched_txt,
            match_type=m_type,
            highlight_boxes=[],
            score=45.0,  # Score is high from metadata alone
            metadata=dict(body_relevance_ratio=body_meta.get("ratio", 0.0)),
        )

        selected, fail_reason = rank_and_select_candidate([cand_trap], evidence_required=True)
        self.assertIsNone(selected)
        self.assertIn("not factually defensible", fail_reason)

    def test_webpage_metadata_trap_rejected_when_body_is_unrelated(self):
        trap_html = """
        <html>
        <head><title>Official Medicare Eligibility Age 65 Report</title></head>
        <body>
            <p>Office supply order forms and printer maintenance guidelines.</p>
        </body>
        </html>
        """
        title, pub, full_txt, snippet, m_type, body_meta = extract_webpage_evidence_passage(
            html_text=trap_html,
            search_query="Medicare eligibility begins at age 65",
        )
        self.assertEqual(m_type, "none")

        cand_trap_web = EvidenceCandidate(
            id="SRC_TRAP_WEB",
            source_id="SRC_TRAP_WEB",
            kind=EvidenceSourceKind.webpage,
            title=title,
            publisher="Social Security Administration",
            trust=EvidenceSourceTrust.official,
            query="Medicare eligibility begins at age 65",
            matched_text=snippet,
            match_type=m_type,
            highlight_boxes=[],
            score=45.0,
            metadata=dict(body_relevance_ratio=body_meta.get("ratio", 0.0)),
        )

        selected, fail_reason = rank_and_select_candidate([cand_trap_web], evidence_required=True)
        self.assertIsNone(selected)
        self.assertIn("not factually defensible", fail_reason)

    def test_pdf_query_relevance_true_positive(self):
        p_num, p_count, matched_txt, m_type, bboxes, body_meta = inspect_and_extract_pdf_evidence(
            pdf_path=self.pdf_path,
            highlight_target=None,
            search_query="Medicare eligibility age 65",
        )
        self.assertEqual(m_type, "query_relevance")
        self.assertEqual(p_num, 2)
        self.assertGreaterEqual(body_meta.get("ratio", 0.0), 0.25)

        cand = EvidenceCandidate(
            id="SRC_PDF_p2",
            source_id="SRC_PDF",
            kind=EvidenceSourceKind.pdf,
            title="Medicare Report",
            publisher="SSA",
            trust=EvidenceSourceTrust.official,
            query="Medicare eligibility age 65",
            page_number=p_num,
            matched_text=matched_txt,
            match_type=m_type,
            highlight_boxes=bboxes,
            score=50.0,
            metadata=dict(body_relevance_ratio=body_meta.get("ratio", 0.0)),
        )
        selected, fail_reason = rank_and_select_candidate([cand], evidence_required=True)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.source_id, "SRC_PDF")

    def test_webpage_query_relevance_true_positive(self):
        html = """
        <html><body>
            <p>Full retirement age is 67 for individuals born in 1960 or later.</p>
        </body></html>
        """
        title, pub, full_txt, snippet, m_type, body_meta = extract_webpage_evidence_passage(
            html_text=html,
            search_query="full retirement age 67 born 1960",
        )
        self.assertEqual(m_type, "query_relevance")
        self.assertGreaterEqual(body_meta.get("ratio", 0.0), 0.25)

        cand = EvidenceCandidate(
            id="SRC_WEB_1",
            source_id="SRC_WEB_1",
            kind=EvidenceSourceKind.webpage,
            title="Retirement Rules",
            trust=EvidenceSourceTrust.official,
            query="full retirement age 67 born 1960",
            matched_text=snippet,
            match_type=m_type,
            score=50.0,
            metadata=dict(body_relevance_ratio=body_meta.get("ratio", 0.0)),
        )
        selected, fail_reason = rank_and_select_candidate([cand], evidence_required=True)
        self.assertIsNotNone(selected)

    def test_page_hint_false_positive_continues_searching_and_selects_relevant_page(self):
        # page_hint is 1 (which has no medicare info), but page 2 has actual medicare info
        p_num, p_count, matched_txt, m_type, bboxes, body_meta = inspect_and_extract_pdf_evidence(
            pdf_path=self.pdf_path,
            page_hint=1,
            search_query="Medicare eligibility age 65",
        )
        self.assertEqual(p_num, 2)  # Found and selected page 2
        self.assertEqual(m_type, "query_relevance")

    def test_page_hint_true_positive_accepted_on_body_content(self):
        p_num, p_count, matched_txt, m_type, bboxes, body_meta = inspect_and_extract_pdf_evidence(
            pdf_path=self.pdf_path,
            page_hint=2,
            search_query="Medicare eligibility age 65",
        )
        self.assertEqual(p_num, 2)
        self.assertEqual(m_type, "query_relevance")
        self.assertGreaterEqual(body_meta.get("ratio", 0.0), 0.25)


if __name__ == "__main__":
    unittest.main()
