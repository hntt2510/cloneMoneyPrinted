from __future__ import annotations

import unittest
from pydantic import ValidationError

from app.models.evidence import (
    EvidenceBBox,
    EvidenceSource,
    EvidenceSourceKind,
    EvidenceSourceRegistry,
    EvidenceSourceTrust,
)
from app.models.project import DocumentPayload


class TestEvidenceModels(unittest.TestCase):
    def test_evidence_bbox_valid(self):
        box = EvidenceBBox(x=0.1, y=0.2, width=0.5, height=0.3)
        self.assertEqual(box.x, 0.1)
        self.assertEqual(box.y, 0.2)
        self.assertEqual(box.width, 0.5)
        self.assertEqual(box.height, 0.3)

    def test_evidence_bbox_invalid_out_of_bounds(self):
        with self.assertRaises(ValidationError):
            EvidenceBBox(x=-0.1, y=0.2, width=0.5, height=0.3)
        with self.assertRaises(ValidationError):
            EvidenceBBox(x=0.8, y=0.2, width=0.5, height=0.3)  # x + width > 1.0
        with self.assertRaises(ValidationError):
            EvidenceBBox(x=0.2, y=0.8, width=0.3, height=0.5)  # y + height > 1.0

    def test_evidence_source_valid_pdf_with_url(self):
        src = EvidenceSource(
            id="SRC001",
            kind=EvidenceSourceKind.pdf,
            url="https://example.com/report.pdf",
            title="Annual Report",
            publisher="SSA",
            trust=EvidenceSourceTrust.official,
            tags=["retirement", "benefits"],
            page_hint=12,
            quote_hint="Benefits begin at age 65",
        )
        self.assertEqual(src.id, "SRC001")
        self.assertEqual(src.kind, EvidenceSourceKind.pdf)
        self.assertEqual(src.trust, EvidenceSourceTrust.official)
        self.assertEqual(src.page_hint, 12)

    def test_evidence_source_valid_local_image(self):
        src = EvidenceSource(
            id="SRC002",
            kind=EvidenceSourceKind.image,
            local_file="sources/chart.png",
            title="Growth Chart",
            trust=EvidenceSourceTrust.user_provided,
            bbox_hint=EvidenceBBox(x=0.1, y=0.1, width=0.8, height=0.5),
        )
        self.assertEqual(src.id, "SRC002")
        self.assertIsNotNone(src.bbox_hint)

    def test_evidence_source_missing_location_rejected(self):
        with self.assertRaises(ValidationError):
            EvidenceSource(
                id="SRC003",
                kind=EvidenceSourceKind.pdf,
                title="Missing Location PDF",
                trust=EvidenceSourceTrust.official,
            )

    def test_evidence_source_both_url_and_local_file_rejected(self):
        with self.assertRaises(ValidationError):
            EvidenceSource(
                id="SRC004",
                kind=EvidenceSourceKind.pdf,
                url="https://example.com/doc.pdf",
                local_file="sources/doc.pdf",
                title="Ambiguous Location PDF",
                trust=EvidenceSourceTrust.official,
            )

    def test_evidence_registry_unique_ids(self):
        s1 = EvidenceSource(
            id="SRC001",
            kind=EvidenceSourceKind.pdf,
            url="https://example.com/doc1.pdf",
            title="Doc 1",
            trust=EvidenceSourceTrust.official,
        )
        s2 = EvidenceSource(
            id="SRC002",
            kind=EvidenceSourceKind.webpage,
            url="https://example.com/page",
            title="Page 1",
            trust=EvidenceSourceTrust.licensed,
        )
        registry = EvidenceSourceRegistry(sources=[s1, s2])
        self.assertEqual(len(registry.sources), 2)

    def test_evidence_registry_duplicate_ids_rejected(self):
        s1 = EvidenceSource(
            id="SRC001",
            kind=EvidenceSourceKind.pdf,
            url="https://example.com/doc1.pdf",
            title="Doc 1",
            trust=EvidenceSourceTrust.official,
        )
        s2 = EvidenceSource(
            id="SRC001",
            kind=EvidenceSourceKind.webpage,
            url="https://example.com/page",
            title="Page 1",
            trust=EvidenceSourceTrust.licensed,
        )
        with self.assertRaises(ValidationError):
            EvidenceSourceRegistry(sources=[s1, s2])

    def test_document_payload_backward_compatibility_and_source_ids(self):
        # Without source_ids
        payload1 = DocumentPayload(
            search_query="social security age",
            source_hint="SSA",
        )
        self.assertEqual(payload1.source_ids, [])
        self.assertEqual(payload1.evidence_required, True)

        # With source_ids
        payload2 = DocumentPayload(
            search_query="social security age",
            source_hint="SSA",
            source_ids=["SRC001", "SRC005"],
        )
        self.assertEqual(payload2.source_ids, ["SRC001", "SRC005"])


if __name__ == "__main__":
    unittest.main()
