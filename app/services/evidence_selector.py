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


MIN_BODY_RELEVANCE_RATIO = 0.25

STOP_WORDS = {
    "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of", "with",
    "by", "is", "are", "was", "were", "be", "been", "this", "that", "it", "from",
    "as", "into", "about", "official", "evidence", "source", "document", "report",
    "website", "information", "page", "section", "chapter", "guide", "video",
}


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase alphanumeric keywords of length >= 2, excluding stop words."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return {w for w in cleaned.split() if len(w) >= 2 and w not in STOP_WORDS}


def _compute_token_overlap(query_tokens: set[str], doc_tokens: set[str]) -> float:
    """Compute overlap ratio between query tokens and document tokens."""
    if not query_tokens or not doc_tokens:
        return 0.0
    common = query_tokens.intersection(doc_tokens)
    return len(common) / float(len(query_tokens))


def compute_body_relevance(query_tokens: set[str], body_text: str | None) -> tuple[float, int, int]:
    """Compute pure content body token overlap (excluding title, publisher, tags).

    Returns:
        (overlap_ratio, matched_tokens_count, total_query_tokens)
    """
    if not query_tokens or not body_text:
        return 0.0, 0, len(query_tokens) if query_tokens else 0
    body_tokens = _tokenize(body_text)
    if not body_tokens:
        return 0.0, 0, len(query_tokens)
    common = query_tokens.intersection(body_tokens)
    ratio = len(common) / float(len(query_tokens))
    return round(ratio, 4), len(common), len(query_tokens)


# --- PDF Inspection and Text Bounding Box Search ---

def inspect_and_extract_pdf_evidence(
    pdf_path: Path | str,
    highlight_target: str | None = None,
    quote_hint: str | None = None,
    page_hint: int | None = None,
    search_query: str = "",
    max_pages_to_scan: int = 300,
) -> tuple[int, int, str | None, str, list[EvidenceBBox], dict[str, Any]]:
    """Open PDF with PyMuPDF, search for target/quote text bounding boxes or select best page by body content.

    Returns:
        (selected_page_number [1-indexed], total_page_count, matched_text, match_type, list_of_bboxes, body_relevance_meta)
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

        # Helper to format body relevance metadata
        def _make_body_meta(p_text: str | None) -> dict[str, Any]:
            r, m, t = compute_body_relevance(query_tokens, p_text)
            return {"ratio": r, "matched": m, "total": t}

        # 1. Search for exact highlight_target (page_hint page first if valid)
        if highlight_target and highlight_target.strip():
            clean_target = highlight_target.strip()
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
                        bx = max(0.0, min(1.0, float(r.x0) / pw))
                        by = max(0.0, min(1.0, float(r.y0) / ph))
                        bw = max(0.001, min(1.0 - bx, float(r.x1 - r.x0) / pw))
                        bh = max(0.001, min(1.0 - by, float(r.y1 - r.y0) / ph))
                        boxes.append(EvidenceBBox(x=round(bx, 4), y=round(by, 4), width=round(bw, 4), height=round(bh, 4)))

                    page_text = page.get_text("text")
                    snippet = _extract_snippet_around(page_text, clean_target)
                    return p_idx + 1, total_pages, snippet, "exact_target", boxes, _make_body_meta(page_text)

        # 2. Search for exact quote_hint (page_hint page first if valid)
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
                    return p_idx + 1, total_pages, snippet, "exact_quote_hint", boxes, _make_body_meta(page_text)

        # 3. Check page_hint page body relevance first
        if page_hint and 1 <= page_hint <= total_pages:
            page = doc[page_hint - 1]
            page_text = page.get_text("text").strip()
            p_ratio, p_matched, p_total = compute_body_relevance(query_tokens, page_text)
            if p_ratio >= MIN_BODY_RELEVANCE_RATIO:
                snippet = page_text[:300] if page_text else None
                return page_hint, total_pages, snippet, "query_relevance", [], {"ratio": p_ratio, "matched": p_matched, "total": p_total}

        # 4. Token overlap query relevance across all pages
        best_page = 1
        best_ratio = -1.0
        best_matched = 0
        best_text = ""

        for p_idx in range(scan_limit):
            page = doc[p_idx]
            p_text = page.get_text("text").strip()
            if not p_text:
                continue
            ratio, matched, total = compute_body_relevance(query_tokens, p_text)
            if ratio > best_ratio:
                best_ratio = ratio
                best_matched = matched
                best_page = p_idx + 1
                best_text = p_text

        if best_ratio >= MIN_BODY_RELEVANCE_RATIO:
            snippet = best_text[:300] if best_text else None
            return best_page, total_pages, snippet, "query_relevance", [], {"ratio": best_ratio, "matched": best_matched, "total": len(query_tokens)}

        # No page body satisfied relevance floor -> match_type is "none"
        snippet = best_text[:300] if best_text else None
        return 1, total_pages, snippet, "none", [], {"ratio": max(0.0, best_ratio), "matched": best_matched, "total": len(query_tokens)}

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
        lines = [l.strip() for l in full_text.splitlines() if l.strip()]
        return " ".join(lines[:3])[:300]

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
    return " ".join(snippet.split())


# --- Webpage Text & Passage Extraction ---

def extract_webpage_evidence_passage(
    html_text: str,
    source_url: str | None = None,
    highlight_target: str | None = None,
    quote_hint: str | None = None,
    search_query: str = "",
) -> tuple[str, str | None, str | None, str, str, dict[str, Any]]:
    """Extract clean title, publisher, matched excerpt text, match type, and body relevance from static HTML."""
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
            r, m, t = compute_body_relevance(query_tokens, snippet)
            return title, publisher, full_text, snippet, "exact_target", {"ratio": r, "matched": m, "total": t}

    # 2. Exact quote_hint search
    if quote_hint and quote_hint.strip():
        clean_quote = quote_hint.strip()
        if clean_quote.lower() in full_text.lower():
            snippet = _extract_snippet_around(full_text, clean_quote, window=160)
            r, m, t = compute_body_relevance(query_tokens, snippet)
            return title, publisher, full_text, snippet, "exact_quote_hint", {"ratio": r, "matched": m, "total": t}

    # 3. Query relevance passage search across paragraphs
    paragraphs = [p.strip() for p in full_text.splitlines() if len(p.strip()) > 30]
    best_para = ""
    best_ratio = -1.0
    best_matched = 0

    for para in paragraphs:
        ratio, matched, total = compute_body_relevance(query_tokens, para)
        if ratio > best_ratio:
            best_ratio = ratio
            best_matched = matched
            best_para = para

    if best_para and best_ratio >= MIN_BODY_RELEVANCE_RATIO:
        return title, publisher, full_text, best_para[:350], "query_relevance", {"ratio": best_ratio, "matched": best_matched, "total": len(query_tokens)}

    # Fallback paragraph (marked as match_type="none" to prevent metadata-only acceptance)
    fallback = " ".join(paragraphs[:2])[:350] if paragraphs else full_text[:350]
    return title, publisher, full_text, fallback, "none", {"ratio": max(0.0, best_ratio), "matched": best_matched, "total": len(query_tokens)}


# --- Deterministic Candidate Scoring ---

def score_evidence_candidate(
    cue: VisualCue,
    payload: DocumentPayload,
    source: EvidenceSource,
    match_type: str,
    matched_text: str | None,
    page_number: int | None = None,
    is_pinned_source: bool = False,
    body_relevance_ratio: float = 0.0,
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
        # Scale between 6.0 and 16.0 based on body relevance ratio
        eff_ratio = max(relevance_ratio, body_relevance_ratio)
        target_match_score = round(6.0 + min(1.0, eff_ratio) * 10.0, 2)
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
    if payload.source_hint and (
        payload.source_hint.lower() in source.title.lower()
        or (source.publisher and payload.source_hint.lower() in source.publisher.lower())
    ):
        specificity_score += 2.0
    specificity_score = min(5.0, specificity_score)
    breakdown["source_specificity"] = specificity_score

    total_score = round(sum(breakdown.values()), 2)
    return total_score, breakdown


def is_candidate_factually_defensible(candidate: EvidenceCandidate) -> tuple[bool, str]:
    """Determine whether candidate is factually grounded in verified source content."""
    if candidate.match_type in ("exact_target", "exact_quote_hint"):
        return True, f"Verified {candidate.match_type} in source content"

    if candidate.kind == EvidenceSourceKind.pdf:
        if candidate.match_type == "query_relevance":
            body_ratio = float(candidate.metadata.get("body_relevance_ratio", 0.0))
            if body_ratio >= MIN_BODY_RELEVANCE_RATIO:
                return True, f"PDF page body has verified query relevance ({body_ratio:.2f} >= {MIN_BODY_RELEVANCE_RATIO})"
            return False, f"PDF page body relevance ({body_ratio:.2f}) is below factual threshold ({MIN_BODY_RELEVANCE_RATIO})"
        return False, f"PDF candidate match_type '{candidate.match_type}' does not provide verified factual evidence"

    elif candidate.kind == EvidenceSourceKind.webpage:
        if candidate.match_type == "query_relevance":
            body_ratio = float(candidate.metadata.get("body_relevance_ratio", 0.0))
            if body_ratio >= MIN_BODY_RELEVANCE_RATIO:
                return True, f"Webpage passage has verified query relevance ({body_ratio:.2f} >= {MIN_BODY_RELEVANCE_RATIO})"
            return False, f"Webpage passage relevance ({body_ratio:.2f}) is below factual threshold ({MIN_BODY_RELEVANCE_RATIO})"
        return False, f"Webpage candidate match_type '{candidate.match_type}' does not provide verified factual evidence"

    elif candidate.kind in (EvidenceSourceKind.image, EvidenceSourceKind.wikimedia):
        if candidate.match_type == "registry_evidence_hint":
            return True, "Image has registered explicit evidence quote hint"
        return False, f"Image/Wikimedia candidate '{candidate.source_id}' lacks registered factual evidence quote"

    return False, f"Unsupported or non-defensible source kind: {candidate.kind}"


def rank_and_select_candidate(
    candidates: list[EvidenceCandidate],
    evidence_required: bool = True,
    min_score_threshold: float = 35.0,
) -> tuple[EvidenceCandidate | None, str | None]:
    """Rank candidates deterministically and select the best candidate.

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

    # Check factual defensibility
    is_defensible, def_reason = is_candidate_factually_defensible(top)
    if evidence_required and not is_defensible:
        return None, f"Top evidence candidate '{top.source_id}' is not factually defensible: {def_reason}"

    if not is_defensible and top.score < min_score_threshold:
        return None, f"Top candidate scored {top.score:.1f} (below threshold; optional fallback recommended)"

    if evidence_required and top.score < min_score_threshold and top.match_type not in ("exact_target", "exact_quote_hint"):
        return None, f"Top evidence candidate '{top.source_id}' scored {top.score:.1f} < threshold {min_score_threshold}"

    return top, None
