from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any

@dataclass
class MotionCopy:
    eyebrow: str | None = None      # e.g. "REPAIR COST"
    headline: str | None = None     # e.g. "YOUR DEDUCTIBLE"
    primary_value: str | None = None # e.g. "$1,000"
    secondary_value: str | None = None
    label: str | None = None        # e.g. "YOU PAY FIRST"
    comparison_label: str | None = None  # e.g. "VS"
    takeaway: str | None = None     # e.g. "OVER LIMIT"


_NARRATION_SENTENCE_RE = re.compile(
    r'\b(suppose|imagine|consider|if you|when you|this means|that means|which means|so you|so the|'
    r'in other words|remember that|as we|for example|let\'s say|now suppose)\b',
    re.IGNORECASE
)

MAX_MOTION_HEADLINE_WORDS = 5

def _is_narration_leak(text: str) -> bool:
    """Return True if text looks like a full spoken sentence."""
    if not text:
        return False
    words = text.strip().split()
    if len(words) > MAX_MOTION_HEADLINE_WORDS:
        return True
    if _NARRATION_SENTENCE_RE.search(text):
        return True
    return False


_FILLER_WORDS = {'the','a','an','is','are','was','were','your','our','their','this','that','these','those',
               'of','in','at','to','for','on','by','with','from','suppose','consider','imagine',
               'when','if','as','be','been','have','has','which','who','what','we','you','they','it'}

def _truncate_motion_headline(text: str) -> str:
    """Extract concise motion headline from potentially verbose text."""
    if not text:
        return "KEY DATA"
    text = text.strip()
    if not _is_narration_leak(text):
        return text

    words = re.findall(r'\b[a-zA-Z0-9$,\.]+\b', text)
    kept = [w for w in words if w.lower() not in _FILLER_WORDS][:4]
    return ' '.join(kept).upper() if kept else text[:30].upper()


_SEMANTIC_CONCEPT_MAPPINGS = [
    # (regex pattern, eyebrow, headline, default_label)
    (r"\b(?:repair(?:ing)?\s+(?:your\s+)?car\s+costs?|repair\s+costs?|total\s+repair)\b", "REPAIR COST", "TOTAL REPAIR", "ESTIMATED DAMAGE"),
    (r"\b(?:collision\s+deductible|comprehensive\s+deductible|your\s+deductible|deductible)\b", "DEDUCTIBLE", "YOUR DEDUCTIBLE", "YOU PAY FIRST"),
    (r"\b(?:insurance\s+company\s+covers|insurance\s+portion|insurance\s+pays|insurer\s+pays|insurance\s+coverage)\b", "INSURANCE", "INSURANCE COVERS", "POLICY BENEFIT"),
    (r"\b(?:coverage\s+limit|policy\s+limit|maximum\s+coverage|liability\s+limit)\b", "COVERAGE LIMIT", "POLICY LIMIT", "MAX PAYOUT"),
    (r"\b(?:damage\s+costs?|total\s+damage|amount\s+of\s+damage|damage\s+exceeds?)\b", "DAMAGE", "TOTAL DAMAGE", "ESTIMATED REPAIR"),
    (r"\b(?:monthly\s+premium|annual\s+premium|insurance\s+premium|premium)\b", "PREMIUM", "POLICY PREMIUM", "RECURRING COST"),
    (r"\b(?:out[\s-]of[\s-]pocket)\b", "OUT OF POCKET", "YOUR SHARE", "DIRECT EXPENSE"),
    (r"\b(?:liability\s+coverage|bodily\s+injury|property\s+damage)\b", "LIABILITY", "LIABILITY COVERAGE", "THIRD PARTY"),
    (r"\b(?:collision\s+coverage)\b", "COLLISION", "COLLISION COVERAGE", "VEHICLE DAMAGE"),
    (r"\b(?:comprehensive\s+coverage)\b", "COMPREHENSIVE", "COMPREHENSIVE COVERAGE", "NON-COLLISION"),
]


def extract_motion_copy(
    narration: str,
    payload: dict[str, Any],
    template: str,
) -> MotionCopy:
    """Extract deterministic motion copy roles from narration + payload."""
    data = payload.get("data", {}) if isinstance(payload.get("data"), dict) else {}
    raw_headline = str(payload.get("headline") or "").strip()
    narr_lower = narration.lower() if narration else ""

    # 1. Match semantic concept mapping
    matched_eyebrow = None
    matched_headline = None
    matched_label = None
    for pat, eb, hl, lbl in _SEMANTIC_CONCEPT_MAPPINGS:
        if re.search(pat, narr_lower, re.IGNORECASE):
            matched_eyebrow = eb
            matched_headline = hl
            matched_label = lbl
            break

    # Headline resolution: prefer explicit payload headline if concise, else matched semantic headline, else truncated
    if raw_headline and not _is_narration_leak(raw_headline):
        headline = raw_headline.upper()
    elif matched_headline:
        headline = matched_headline
    else:
        headline = _truncate_motion_headline(raw_headline or narration)

    # Eyebrow resolution
    eyebrow = None
    if data.get("eyebrow"):
        eyebrow = str(data["eyebrow"]).upper().strip()
    elif data.get("label"):
        eyebrow = str(data["label"]).upper().strip()
    elif matched_eyebrow:
        eyebrow = matched_eyebrow
    elif template in ("number", "counter"):
        text_without_fillers = " ".join([w for w in re.findall(r'\b[a-zA-Z]+\b', narration[:60]) if w.lower() not in _FILLER_WORDS])
        m = re.search(r'\b([a-zA-Z]+(?: [a-zA-Z]+){0,2})\b', text_without_fillers)
        if m:
            eyebrow = m.group(0).upper()

    # Primary value resolution
    primary_value = None
    if template in ("number", "counter"):
        val = data.get("display_value") or data.get("value") or data.get("end_value")
        if val:
            prefix = data.get("prefix", "")
            suffix = data.get("suffix", "")
            primary_value = f"{prefix}{val}{suffix}"

    # Label resolution
    label = None
    if data.get("subtext"):
        label = str(data["subtext"])[:40]
    elif data.get("context_label"):
        label = str(data["context_label"])[:40]
    elif matched_label:
        label = matched_label

    takeaway = None
    if data.get("takeaway"):
        takeaway = str(data["takeaway"])[:50]

    return MotionCopy(
        eyebrow=eyebrow,
        headline=headline,
        primary_value=primary_value,
        label=label,
        takeaway=takeaway,
    )
