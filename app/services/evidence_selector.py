from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pymupdf
from loguru import logger
from PIL import Image

from app.models.evidence import (
    EvidenceBBox,
    EvidenceCandidate,
    EvidenceSource,
    EvidenceSourceKind,
    EvidenceSourceRegistry,
    EvidenceSourceTrust,
)
from app.models.project import DocumentPayload, VisualCue
from app.services.evidence_sources import extract_webpage_content


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase alphanumeric keywords of length >= 2."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    stop_words = {
        "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with",
        "by", "is", "are", "was", "were", "be", "been", "this", "that", "it", "from",
        "as", "into", "about", "official", "evidence", "source", "document",
    }
    return {w for w in cleaned.split() if len(w) >= 2 and w not in stop_words}


def _compute_token_overlap(query_tokens: set[str], doc_tokens: set[str]) -> float:
    """Compute Jaccard-like overlap ratio between query tokens and document tokens."""
    if not query_tokens or not doc_tokens:
        return 0.0
    common = query_tokens.intersection(doc_tokens)
    return len(common) / float(len(query_tokens))


# --- PDF Inspection and Text Bounding Box Search ---

def inspect_and_extract_pdf_evidence(
    pdf_path: Path | str,
    highlight_target: str | None = None,
    quote_hint: str | None = None,
    page_hint: int | None = None,
    search_query: str = "",
    max_pages_to_scan: int = 300,
) -> tuple[int, int, str | None, str, list[EvidenceBBox]]:
    """Open PDF with PyMuPDF, search for target/quote text bounding boxes or select best page.

    Returns:
        (selected_page_number [1-indexed], total_page_count, matched_text, match_type, list_of_bboxes)
    """
    doc = None
    try:
        doc = pymupdf.open(str(Path(pdf_path).resolve()))
        total_pages = len(doc)
        if total_pages == 0:
            raise ValueError("PDF document contains zero pages")

        if doc.is_encrypted:
            raise ValueError("PDF document is encrypted / password protected")

        scan_limit = min(total_pages, max_pages_to_scan)
        query_tokens = _tokenize(search_query)

        # 1. Search for exact highlight_target
        if highlight_target and highlight_target.strip():
            clean_target = highlight_target.strip()
            # If page_hint is provided, check that page first
            pages_to_check = []
            if page_hint and 1 <= page_hint <= total_pages:
                pages_to_check.append(page_hint - 1)
            pages_to_check.extend([p for p in range(scan_limit) if p not in pages_to_check])

            for p_idx in pages_to_check:
                page = doc[p_idx]
                page_rect = page.rect
                pw, ph = float(page_rect.width), float(page_rect.height)
                if pw <= 0 or ph <= 0:
                    continue

                rects = page.search_for(clean_target, quads=False)
                if rects:
                    boxes: list[EvidenceBBox] = []
                    for r in rects:
                        # Normalize coordinates to 0..1
                        bx = max(0.0, min(1.0, float(r.x0) / pw))
                        by = max(0.0, min(1.0, float(r.y0) / ph))
                        bw = max(0.001, min(1.0 - bx, float(r.x1 - r.x0) / pw))
                        bh = max(0.001, min(1.0 - by, float(r.y1 - r.y0) / ph))
                        boxes.append(EvidenceBBox(x=round(bx, 4), y=round(by, 4), width=round(bw, 4), height=round(bh, 4)))

                    # Extract context snippet around target
                    page_text = page.get_text("text")
                    snippet = _extract_snippet_around(page_text, clean_target)
                    return p_idx + 1, total_pages, snippet, "exact_target", boxes

        # 2. Search for exact quote_hint
        if quote_hint and quote_hint.strip():
            clean_quote = quote_hint.strip()
            pages_to_check = []
            if page_hint and 1 <= page_hint <= total_pages:
                pages_to_check.append(page_hint - 1)
            pages_to_check.extend([p for p in range(scan_limit) if p not in pages_to_check])

            for p_idx in pages_to_check:
                page = doc[p_idx]
                page_rect = page.rect
                pw, ph = float(page_rect.width), float(page_rect.height)
                if pw <= 0 or ph <= 0:
                    continue

                rects = page.search_for(clean_quote, quads=False)
                if rects:
                    boxes: list[EvidenceBBox] = []
                    for r in rects:
                        bx = max(0.0, min(1.0, float(r.x0) / pw))
                        by = max(0.0, min(1.0, float(r.y0) / ph))
                        bw = max(0.001, min(1.0 - bx, float(r.x1 - r.x0) / pw))
                        bh = max(0.001, min(1.0 - by, float(r.y1 - r.y0) / ph))
                        boxes.append(EvidenceBBox(x=round(bx, 4), y=round(by, 4), width=round(bw, 4), height=round(bh, 4)))

                    page_text = page.get_text("text")
                    snippet = _extract_snippet_around(page_text, clean_quote)
                    return p_idx + 1, total_pages, snippet, "exact_quote_hint", boxes

        # 3. Explicit valid page_hint fallback
        if page_hint and 1 <= page_hint <= total_pages:
            page = doc[page_hint - 1]
            page_text = page.get_text("text").strip()
            snippet = page_text[:300] if page_text else None
            return page_hint, total_pages, snippet, "page_hint", []

        # 4. Token overlap query relevance across pages
        best_page = 1
        best_score = -1.0
        best_text = ""

        for p_idx in range(scan_limit):
            page = doc[p_idx]
            p_text = page.get_text("text").strip()
            if not p_text:
                continue
            p_tokens = _tokenize(p_text)
            overlap = _compute_token_overlap(query_tokens, p_tokens)
            if overlap > best_score:
                best_score = overlap
                best_page = p_idx + 1
                best_text = p_text

        snippet = best_text[:300] if best_text else None
        match_type = "query_relevance" if best_score > 0.1 else "none"
        return best_page, total_pages, snippet, match_type, []

    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def _extract_snippet_around(full_text: str, target: str, window: int = 150) -> str:
    """Extract excerpt snippet surrounding a target keyword or phrase."""
    if not full_text:
        return target
    lower_full = full_text.lower()
    lower_tgt = target.lower()
    pos = lower_full.find(lower_tgt)
    if pos == -1:
        # Return first non-empty lines
        lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        return " ".join(lines[:3])[:300]

    # Check for containing sentence
    for line in full_text.splitlines():
        if lower_tgt in line.lower():
            clean_line = line.strip()
            sentences = re.split(r"(?<=[.!?])\s+", clean_line)
            for s in sentences:
                if lower_tgt in s.lower():
                    return " ".join(s.split()).strip()
            return " ".join(clean_line.split()).strip()

    start = max(0, pos - window)
    end = min(len(full_text), pos + len(target) + window)
    snippet = full_text[start:end].strip()
    # Normalize whitespace
    return " ".join(snippet.split())


# --- Webpage Text & Passage Extraction ---

def extract_webpage_evidence_passage(
    html_text: str,
    source_url: str | None = None,
    highlight_target: str | None = None,
    quote_hint: str | None = None,
    search_query: str = "",
) -> tuple[str, str | None, str | None, str, str]:
    """Extract clean title, publisher, matched excerpt text, and match type from static HTML."""
    parsed = extract_webpage_content(html_text, source_url=source_url)
    title = parsed["title"] or "Web Document"
    publisher = parsed["publisher"]
    full_text = parsed["text"] or ""

    query_tokens = _tokenize(search_query)

    # 1. Exact highlight_target search
    if highlight_target and highlight_target.strip():
        clean_target = highlight_target.strip()
        if clean_target.lower() in full_text.lower():
            snippet = _extract_snippet_around(full_text, clean_target, window=160)
            return title, publisher, full_text, snippet, "exact_target"

    # 2. Exact quote_hint search
    if quote_hint and quote_hint.strip():
        clean_quote = quote_hint.strip()
        if clean_quote.lower() in full_text.lower():
            snippet = _extract_snippet_around(full_text, clean_quote, window=160)
            return title, publisher, full_text, snippet, "exact_quote_hint"

    # 3. Query relevance passage search
    paragraphs = [p.strip() for p in full_text.splitlines() if len(p.strip()) > 30]
    best_para = ""
    best_score = -1.0
    for para in paragraphs:
        p_tokens = _tokenize(para)
        overlap = _compute_token_overlap(query_tokens, p_tokens)
        if overlap > best_score:
            best_score = overlap
            best_para = para

    if best_para and best_score > 0.1:
        return title, publisher, full_text, best_para[:350], "query_relevance"

    # Fallback to initial paragraphs
    fallback = " ".join(paragraphs[:2])[:350] if paragraphs else full_text[:350]
    return title, publisher, full_text, fallback, "none"


# --- Deterministic Candidate Scoring ---

def score_evidence_candidate(
    cue: VisualCue,
    payload: DocumentPayload,
    source: EvidenceSource,
    match_type: str,
    matched_text: str | None,
    page_number: int | None = None,
    is_pinned_source: bool = False,
) -> tuple[float, dict[str, float]]:
    """Compute deterministic 100-point evidence score.

    Weights:
        Content Relevance: 40
        Target Match:      30
        Source Trust:      15
        Visual Suitability:10
        Source Specificity: 5
    """
    breakdown: dict[str, float] = {}

    # 1. Content Relevance (0 - 40)
    query_text = f"{payload.search_query} {payload.source_hint or ''} {cue.narration or ''}"
    query_tokens = _tokenize(query_text)
    doc_text = f"{source.title} {' '.join(source.tags)} {matched_text or ''}"
    doc_tokens = _tokenize(doc_text)
    relevance_ratio = _compute_token_overlap(query_tokens, doc_tokens)
    content_relevance_score = round(relevance_ratio * 40.0, 2)
    breakdown["content_relevance"] = content_relevance_score

    # 2. Target Match (0 - 30)
    if match_type == "exact_target":
        target_match_score = 30.0
    elif match_type == "exact_quote_hint":
        target_match_score = 22.0
    elif match_type == "registry_evidence_hint":
        target_match_score = 18.0
    elif match_type == "approved_region":
        target_match_score = 10.0
    elif match_type == "query_relevance":
        # Scale between 4.0 and 12.0 based on relevance
        target_match_score = round(4.0 + min(1.0, relevance_ratio) * 8.0, 2)
    elif match_type == "page_hint":
        target_match_score = 8.0
    else:
        target_match_score = 0.0
    breakdown["target_match"] = target_match_score

    # 3. Source Trust (0 - 15)
    trust_map = {
        EvidenceSourceTrust.official: 15.0,
        EvidenceSourceTrust.user_provided: 14.0,
        EvidenceSourceTrust.approved: 14.0,
        EvidenceSourceTrust.public_domain: 12.0,
        EvidenceSourceTrust.licensed: 10.0,
    }
    trust_score = trust_map.get(source.trust, 8.0)
    breakdown["source_trust"] = trust_score

    # 4. Visual Suitability (0 - 10)
    if source.kind in (EvidenceSourceKind.pdf, EvidenceSourceKind.image, EvidenceSourceKind.webpage, EvidenceSourceKind.wikimedia):
        visual_score = 10.0
    else:
        visual_score = 5.0
    breakdown["visual_suitability"] = visual_score

    # 5. Source Specificity (0 - 5)
    specificity_score = 0.0
    if is_pinned_source:
        specificity_score += 3.0
    # Check if source_hint matches publisher/title
    if payload.source_hint and (
        payload.source_hint.lower() in source.title.lower()
        or (source.publisher and payload.source_hint.lower() in source.publisher.lower())
    ):
        specificity_score += 2.0
    specificity_score = min(5.0, specificity_score)
    breakdown["source_specificity"] = specificity_score

    total_score = round(sum(breakdown.values()), 2)
    return total_score, breakdown


def rank_and_select_candidate(
    candidates: list[EvidenceCandidate],
    evidence_required: bool = True,
    min_score_threshold: float = 35.0,
) -> tuple[EvidenceCandidate | None, str | None]:
    """Rank candidates deterministically and select the best candidate.

    Tie-breaker order:
    1. Highest total score
    2. Highest target_match score
    3. Highest content_relevance score
    4. Highest source_trust score
    5. Source ID (ascending)
    6. Page number (ascending)

    Returns:
        (selected_candidate, failure_reason)
    """
    if not candidates:
        if evidence_required:
            return None, "No evidence sources available or matched for required DOCUMENT cue"
        return None, "No evidence sources available (optional evidence)"

    # Stable deterministic sorting
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (
            -c.score,
            -c.score_breakdown.get("target_match", 0.0),
            -c.score_breakdown.get("content_relevance", 0.0),
            -c.score_breakdown.get("source_trust", 0.0),
            c.source_id,
            c.page_number or 0,
        ),
    )

    top = sorted_candidates[0]

    # Check factual defensibility for image sources under evidence_required
    has_defensible_match = top.match_type in ("exact_target", "exact_quote_hint", "registry_evidence_hint")
    if top.kind in (EvidenceSourceKind.image, EvidenceSourceKind.wikimedia) and not has_defensible_match:
        if evidence_required:
            return None, f"Image candidate '{top.source_id}' lacks verified factual evidence text or registry quote hint"

    # Check minimum score threshold
    if top.score < min_score_threshold and not has_defensible_match:
        if evidence_required:
            return None, f"Top evidence candidate '{top.source_id}' scored {top.score:.1f} < threshold {min_score_threshold}"
        return None, f"Top candidate scored {top.score:.1f} (below threshold; optional fallback recommended)"

    return top, None
