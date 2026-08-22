from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CanonicalNumericFact:
    value: float
    is_percent: bool = False
    is_currency: bool = False
    display: str = ""
    raw: str = ""

    def matches(self, other: CanonicalNumericFact | float | int) -> bool:
        if isinstance(other, (int, float)):
            return abs(self.value - float(other)) < 1e-5
        if isinstance(other, CanonicalNumericFact):
            if self.is_percent != other.is_percent:
                return False
            return abs(self.value - other.value) < 1e-5
        return False


_WORD_UNITS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_WORD_TENS: dict[str, int] = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_WORD_SCALES: dict[str, int] = {
    "hundred": 100,
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
}

_DIGIT_RE = re.compile(
    r"""(?xi)
    (?:\$|€|£|¥)?\s*
    (?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*
    (?:k|m|b|billion|million|thousand|%|percent|pct|dollars?|bucks?|cents?)?
    """
)

# Spoken number token pattern (words with optional hyphens)
_SPOKEN_TOKEN_RE = re.compile(
    r"""(?xi)
    \b(?:
        (?:zero|one|two|three|four|five|six|seven|eight|nine|ten|
           eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|
           twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)
        (?:-(?:one|two|three|four|five|six|seven|eight|nine))?
        |hundred|thousand|million|billion
        |and
        |dollars?|bucks?|cents?|percent|pct|%
    )\b
    """
)


def _format_display(value: float, is_currency: bool, is_percent: bool) -> str:
    if is_currency:
        if value.is_integer():
            return f"${int(value):,}"
        return f"${value:,.2f}"
    if is_percent:
        if value.is_integer():
            return f"{int(value)}%"
        return f"{value:g}%"
    if value.is_integer():
        return f"{int(value):,}" if value >= 1000 else str(int(value))
    return f"{value:g}"


def parse_spoken_number_phrase(tokens: list[str]) -> tuple[float, bool, bool] | None:
    """Parse a sequence of normalized English words into a numeric value, is_currency, is_percent.

    Returns None if the sequence does not represent a valid quantitative number.
    """
    if not tokens:
        return None

    is_currency = False
    is_percent = False

    cleaned_tokens: list[str] = []
    for t in tokens:
        tl = t.lower()
        if tl in ("dollar", "dollars", "bucks", "cents"):
            is_currency = True
        elif tl in ("percent", "pct", "%"):
            is_percent = True
        elif tl != "and":
            cleaned_tokens.append(tl)

    if not cleaned_tokens:
        return None

    # Disallow non-quantitative conversational idioms like "one more"
    if cleaned_tokens == ["one"] and not (is_currency or is_percent):
        return None

    current = 0
    total = 0
    valid = False

    for tok in cleaned_tokens:
        # Check spoken year syntax (e.g., "twenty twenty-two" -> 2000 + 22 = 2022, "nineteen ninety-nine" -> 1900 + 99 = 1999)
        if current in (18, 19, 20, 21) and ("-" in tok or tok in _WORD_TENS or (tok in _WORD_UNITS and _WORD_UNITS[tok] > 0)):
            current *= 100

        # Check hyphenated compound (e.g. twenty-five)
        if "-" in tok:
            parts = tok.split("-")
            if len(parts) == 2 and parts[0] in _WORD_TENS and parts[1] in _WORD_UNITS:
                current += _WORD_TENS[parts[0]] + _WORD_UNITS[parts[1]]
                valid = True
                continue
            else:
                return None

        if tok in _WORD_UNITS:
            current += _WORD_UNITS[tok]
            valid = True
        elif tok in _WORD_TENS:
            current += _WORD_TENS[tok]
            valid = True
        elif tok == "hundred":
            if current == 0:
                current = 1
            current *= 100
            valid = True
        elif tok in _WORD_SCALES:
            scale = _WORD_SCALES[tok]
            if current == 0:
                current = 1
            total += current * scale
            current = 0
            valid = True
        else:
            return None

    final_val = float(total + current)
    if not valid:
        return None
    return final_val, is_currency, is_percent


def parse_digit_token(raw: str) -> CanonicalNumericFact | None:
    """Parse a single digit-based token (e.g. $6,000, 25K, 40%) into CanonicalNumericFact."""
    text = raw.strip()
    if not text:
        return None

    is_currency = any(c in text for c in ("$", "€", "£", "¥")) or any(
        w in text.lower() for w in ("dollar", "dollars", "buck", "bucks")
    )
    is_percent = "%" in text or "percent" in text.lower() or "pct" in text.lower()

    clean = re.sub(r"[^\d\.kmKMbB]", "", text).strip()
    if not clean:
        return None

    multiplier = 1.0
    if clean[-1] in "kK":
        multiplier = 1_000.0
        clean = clean[:-1].strip()
    elif clean[-1] in "mM":
        multiplier = 1_000_000.0
        clean = clean[:-1].strip()
    elif clean[-1] in "bB":
        multiplier = 1_000_000_000.0
        clean = clean[:-1].strip()

    clean = clean.rstrip(".")
    if not clean:
        return None

    try:
        val = float(clean) * multiplier
        disp = _format_display(val, is_currency, is_percent)
        return CanonicalNumericFact(
            value=val,
            is_percent=is_percent,
            is_currency=is_currency,
            display=disp,
            raw=raw.strip(),
        )
    except ValueError:
        return None


def extract_canonical_numeric_facts(value: Any) -> list[CanonicalNumericFact]:
    """Extract all canonical numeric facts (both digit and spoken English forms) from text or nested structures."""
    facts: list[CanonicalNumericFact] = []

    if isinstance(value, bool):
        return facts
    if isinstance(value, (int, float)):
        val = float(value)
        facts.append(
            CanonicalNumericFact(
                value=val,
                is_percent=False,
                is_currency=False,
                display=_format_display(val, False, False),
                raw=str(value),
            )
        )
        return facts

    if isinstance(value, dict):
        for v in value.values():
            facts.extend(extract_canonical_numeric_facts(v))
        return facts

    if isinstance(value, (list, tuple, set)):
        for v in value:
            facts.extend(extract_canonical_numeric_facts(v))
        return facts

    if not isinstance(value, str):
        return facts

    text = value.strip()
    if not text:
        return facts

    # 1. Extract digit-based facts
    for m in _DIGIT_RE.finditer(text):
        cand = m.group(0).strip()
        # Avoid matching solitary punctuation
        if re.search(r"\d", cand):
            fact = parse_digit_token(cand)
            if fact:
                facts.append(fact)

    # 2. Extract spoken-number phrases using sliding token sequences
    words_matches = list(_SPOKEN_TOKEN_RE.finditer(text))
    if words_matches:
        # Group contiguous or near-contiguous spoken tokens
        groups: list[list[re.Match]] = []
        current_group: list[re.Match] = []
        last_end = -1

        for match in words_matches:
            start, end = match.span()
            if last_end == -1 or (start - last_end <= 2 and text[last_end:start].strip() in ("", "-", "and")):
                current_group.append(match)
            else:
                if current_group:
                    groups.append(current_group)
                current_group = [match]
            last_end = end

        if current_group:
            groups.append(current_group)

        for grp in groups:
            tokens = [m.group(0) for m in grp]
            parsed = parse_spoken_number_phrase(tokens)
            if parsed:
                val, is_curr, is_pct = parsed
                raw_str = text[grp[0].start() : grp[-1].end()]
                disp = _format_display(val, is_curr, is_pct)
                facts.append(
                    CanonicalNumericFact(
                        value=val,
                        is_percent=is_pct,
                        is_currency=is_curr,
                        display=disp,
                        raw=raw_str,
                    )
                )

    # Deduplicate facts by (value, is_percent) while preserving currency preference
    deduped: list[CanonicalNumericFact] = []
    seen: dict[tuple[float, bool], int] = {}
    for f in facts:
        key = (round(f.value, 4), f.is_percent)
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(f)
        else:
            # Upgrade existing if new one is explicitly currency
            idx = seen[key]
            if f.is_currency and not deduped[idx].is_currency:
                deduped[idx] = f

    return deduped
