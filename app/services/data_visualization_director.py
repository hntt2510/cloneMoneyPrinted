"""Adaptive Data Visualization Director (G17).

Translates grounded narration facts and semantic data intent into deterministic
visual grammars, variants, and validated props for SRT-synced Remotion rendering.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.models.motion import (
    AreaChartProps,
    BeforeAfterProps,
    DataVisualizationSpec,
    GaugeProps,
    LineChartPoint,
    LineChartProps,
    PieProps,
    PieSliceItem,
    RankedListItem,
    RankedListProps,
    SemanticDataIntent,
    StackedBarProps,
    StackedBarSegment,
    VisualGrammar,
    WaterfallProps,
    WaterfallStep,
)
from app.services.numeric_parser import CanonicalNumericFact, extract_canonical_numeric_facts


# Regular expression patterns for intent classification
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19\d\d|20\d\d)\b")
_TOP_RANK_RE = re.compile(r"\b(?:top\s*\d+|most\s+common|ranked|ranking|rankings|largest|smallest|leaders?|main\s+causes?|top\s+causes?|leading\s+causes?)\b", re.IGNORECASE)
_COMPARISON_RE = re.compile(
    r"\b(?:versus|vs\.?|compare|compared\s+to|different\s+from|very\s+different\s+from|unlike|not\s+the\s+same\s+as|one\s+is|while\s+the\s+other|in\s+contrast\s+to|on\s+the\s+other\s+hand|whereas)\b",
    re.IGNORECASE,
)
_PROGRESS_RE = re.compile(r"\b(?:progress|complete|completed|done|finished|steps?|fraction|goal|quota)\b", re.IGNORECASE)
_THRESHOLD_RE = re.compile(r"\b(?:limit|threshold|maximum|cap|excess|exceed|over\s*limit|damage|ceiling)\b", re.IGNORECASE)
_WATERFALL_RE = re.compile(r"\b(?:start(?:ed|ing)?|begin(?:ning)?|began|initial|fees?|discount|deduct(?:ion)?|final|finish(?:ed|ing)?|net|balance|adjust(?:ment)?|ending|ended)\b", re.IGNORECASE)
_BEFORE_AFTER_RE = re.compile(r"\b(?:before|after|previously|now|old|new|prior|shifted|transition)\b", re.IGNORECASE)
_BREAKDOWN_RE = re.compile(r"\b(?:breakdown|total|parts?|portion|remaining|sum\s+of|out\s*of)\b", re.IGNORECASE)


def _clean_entity_label(raw: str) -> str:
    """Clean raw entity string by removing leading determiners, possessives, and trailing clutter."""
    t = raw.strip().rstrip(".").rstrip(",").rstrip(";")
    t = re.sub(r"^(?:that|the|your|a|an|this|our|my|insurance)\s+", "", t, flags=re.IGNORECASE).strip()
    words = t.split()
    if len(words) > 3:
        words = words[:3]
    return " ".join(words).strip()


def extract_grounded_comparison_entities(text: str) -> tuple[str, str] | None:
    """Extract two compared entities from narration text generically across any domain."""
    if not text:
        return None
    cleaned = text.strip().rstrip(".").rstrip(",").rstrip(";")

    # Pattern 1: [that/the/your]? Entity1 [is/are] [very]? [different from / unlike / not the same as / compared to / vs] [that/the/your]? Entity2
    p1 = re.search(
        r"(?:that|the|your|a|an|this)?\s*([a-zA-Z0-9_\- ]+?)\s+(?:is|are)\s+(?:very\s+)?(?:different\s+from|unlike|not\s+the\s+same\s+as|compared\s+to|vs\.?|versus)\s+(?:that|the|your|a|an|this)?\s*([a-zA-Z0-9_\- ]+?)(?:\.|$|,|;)",
        cleaned,
        re.IGNORECASE,
    )
    if p1:
        e1 = _clean_entity_label(p1.group(1))
        e2 = _clean_entity_label(p1.group(2))
        if e1 and e2 and e1.lower() != e2.lower():
            return e1, e2

    # Pattern 2: Entity1 [versus / vs / against] Entity2
    p2 = re.search(
        r"(?:that|the|your|a|an|this)?\s*([a-zA-Z0-9_\- ]+?)\s+(?:versus|vs\.?|against)\s+(?:that|the|your|a|an|this)?\s*([a-zA-Z0-9_\- ]+?)(?:\.|$|,|;)",
        cleaned,
        re.IGNORECASE,
    )
    if p2:
        e1 = _clean_entity_label(p2.group(1))
        e2 = _clean_entity_label(p2.group(2))
        if e1 and e2 and e1.lower() != e2.lower():
            return e1, e2

    # Pattern 3: Comparing/compare Entity1 [with / and / to] Entity2
    p3 = re.search(
        r"(?:comparing|compare)\s+(?:that|the|your|a|an|this)?\s*([a-zA-Z0-9_\- ]+?)\s+(?:with|and|to)\s+(?:that|the|your|a|an|this)?\s*([a-zA-Z0-9_\- ]+?)(?:\.|$|,|;)",
        cleaned,
        re.IGNORECASE,
    )
    if p3:
        e1 = _clean_entity_label(p3.group(1))
        e2 = _clean_entity_label(p3.group(2))
        if e1 and e2 and e1.lower() != e2.lower():
            return e1, e2

    return None


def extract_grounded_entity_definition(entity: str, text: str) -> str | None:
    """Extract grounded definition/description of an entity from narration text."""
    if not text or not entity:
        return None

    cleaned_text = text.strip()
    e_tokens = [re.escape(w) for w in entity.strip().split() if len(w) > 2]
    e_pattern = r"(?:\b" + r"\b|\b".join(e_tokens) + r"\b)" if e_tokens else re.escape(entity.strip())

    patterns = [
        rf"(?:that|the|your|a|an)?\s*{e_pattern}\s+(?:is|are|means|gives|provides|represents|refers\s+to)\s+(.+?)(?:\.|$|;)",
        rf"(?:gives|provides|represents)\s+(.+?)(?:\.|$|;)",
        rf"{e_pattern}\s*:\s*(.+?)(?:\.|$|;)",
    ]
    for pat in patterns:
        m = re.search(pat, cleaned_text, re.IGNORECASE)
        if m:
            defn = m.group(1).strip().rstrip(".").rstrip(",")
            defn = re.sub(r"\s+(?:while|whereas|versus|vs|assuming|subject\s+to).*$", "", defn, flags=re.IGNORECASE).strip()
            defn = re.sub(r"^(?:that|the|your|a|an)\s+(ongoing\s+cost.*)", r"\1", defn, flags=re.IGNORECASE).strip()
            if len(defn) >= 3:
                return defn[0].upper() + defn[1:]
    return None


_THRESHOLD_STOPWORDS = {"the", "that", "this", "a", "an", "your", "our", "my", "their", "its", "you", "we", "they", "it", "have", "has", "is", "are", "with", "of", "in", "for", "to", "at", "by", "on"}


def _clean_threshold_subject(raw: str) -> str:
    """Clean extracted threshold subject by stripping lead-ins, stopwords, numbers and units."""
    s = raw.strip().rstrip(".,;:")
    s = re.sub(r"^(?:imagine\s+(?:that\s+)?(?:you\s+have\s+)?|suppose\s+(?:that\s+)?(?:you\s+have\s+)?)\s*", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^(?:the|that|your|our|my|a|an|this)\s+", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^(?:have|has|is|are|with)\s+", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^(?:(?:\$|\b\d+[\d,\.]*|\b[a-zA-Z\-]+\b)\s+)+(?:dollars|requests|units|users|percent|%|hours|miles|gb|mb)\s+(?:of\s+|in\s+)?", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^(?:of\s+|in\s+|for\s+)", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"\s+(?:limit|cap|threshold|maximum)\b.*$", "", s, flags=re.IGNORECASE).strip()
    words = [w for w in s.split() if w.lower() not in _THRESHOLD_STOPWORDS or len(s.split()) == 1]
    if len(words) > 4:
        words = words[-4:]
    res = " ".join(words).strip()
    if res.lower() in _THRESHOLD_STOPWORDS:
        return ""
    return res


def extract_grounded_threshold_labels(limit_text: str, actual_text: str = "") -> dict[str, str]:
    """Extract grounded subject headline and threshold label from threshold narration without domain bias."""
    t = (limit_text or "").strip()

    subject = ""
    limit_label = "Limit"

    # 1. Pattern: "<subject> (request|requests|budget|coverage|quota|speed|storage|bandwidth|cost) limit/cap/threshold"
    m1 = re.search(r"([a-zA-Z0-9_\- ]+?)\s+(request|requests|budget|coverage|quota|speed|storage|bandwidth|cost)?\s*(?:limit|cap|threshold|maximum)\b", t, re.IGNORECASE)
    if m1:
        raw_subj = _clean_threshold_subject(m1.group(1))
        lim_type = (m1.group(2) or "").strip()
        if lim_type:
            lt_lower = lim_type.lower()
            if lt_lower in ("request", "requests"):
                limit_label = "Request Limit"
                subject = f"{raw_subj} REQUESTS".strip().upper() if raw_subj else "API REQUESTS"
            elif lt_lower == "coverage":
                limit_label = "Coverage Limit"
                subject = raw_subj.upper() if raw_subj else "COVERAGE LIMIT"
            elif lt_lower == "budget":
                limit_label = "Budget Limit"
                subject = f"{raw_subj} BUDGET".strip().upper() if raw_subj else "BUDGET"
            elif lt_lower == "quota":
                limit_label = "Quota Limit"
                subject = f"{raw_subj} QUOTA".strip().upper() if raw_subj else "QUOTA"
            else:
                limit_label = f"{lim_type.title()} Limit"
                subject = f"{raw_subj} {lim_type}".strip().upper() if raw_subj else f"{lim_type.upper()} LIMIT"
        else:
            limit_label = "Limit"
            subject = raw_subj.upper() if raw_subj else "LIMIT"

    # 2. Pattern without the explicit word "limit" (e.g. "twenty-five thousand dollars of property damage liability coverage")
    if not subject or subject == "LIMIT":
        m2 = re.search(r"(?:dollars\s+of|of|in)?\s*([a-zA-Z0-9_\- ]+?)\s+(coverage|budget|quota|allowance)\b", t, re.IGNORECASE)
        if m2:
            raw_subj = _clean_threshold_subject(m2.group(1))
            kw = m2.group(2).strip().lower()
            if kw == "coverage":
                limit_label = "Coverage Limit"
                subject = raw_subj.upper() if raw_subj else "COVERAGE LIMIT"
            elif kw == "budget":
                limit_label = "Budget Limit"
                subject = f"{raw_subj} BUDGET".strip().upper() if raw_subj else "BUDGET"
            elif kw == "quota":
                limit_label = "Quota Limit"
                subject = f"{raw_subj} QUOTA".strip().upper() if raw_subj else "QUOTA"
            else:
                limit_label = f"{kw.title()} Limit"
                subject = f"{raw_subj} {kw}".strip().upper()

    if not subject or subject.lower() in _THRESHOLD_STOPWORDS:
        subject = "LIMIT"

    return {
        "subject": subject,
        "threshold_label": limit_label,
    }


class VisualDiversityMemory:
    """Tracks recently used DATA visual grammars and variants to avoid repetitive visual slides."""

    def __init__(self, max_history: int = 6) -> None:
        self.max_history = max_history
        self._history: list[tuple[str, str]] = []  # [(grammar, variant), ...]
        self.total_records: int = 0

    @property
    def history(self) -> list[tuple[str, str]]:
        return list(self._history)

    def record_usage(self, grammar: str, variant: str) -> None:
        self.total_records += 1
        self._history.append((grammar, variant))
        if len(self._history) > self.max_history:
            self._history.pop(0)

    def get_recent_grammars(self) -> list[str]:
        return [g for g, _ in self._history]

    def get_recent_variants(self) -> list[str]:
        return [v for _, v in self._history]

    def choose_diverse_variant(self, grammar: str, allowed_variants: list[str]) -> str:
        if not allowed_variants:
            return "default"
        if len(allowed_variants) == 1:
            return allowed_variants[0]

        recent_variants = self.get_recent_variants()
        # Find variants that have not been used recently
        for var in allowed_variants:
            if var not in recent_variants:
                return var

        # If all were used, pick the least recently used one
        for var in recent_variants:
            if var in allowed_variants:
                # Pick an alternative if possible
                alt = [v for v in allowed_variants if v != var]
                if alt:
                    return alt[0]

        return allowed_variants[0]


class DataVisualizationDirector:
    """Directs semantic data intent classification, grammar selection, validation, and fallbacks."""

    def __init__(self, memory: VisualDiversityMemory | None = None) -> None:
        self.memory = memory or VisualDiversityMemory()

    def classify_data_intent(
        self,
        narration: str,
        facts: list[CanonicalNumericFact] | None = None,
        cue_payload: dict[str, Any] | None = None,
    ) -> SemanticDataIntent:
        """Classifies the semantic data intent from narration and extracted numeric facts."""
        text = (narration or "").strip()
        t_lower = text.lower()
        facts = facts or extract_canonical_numeric_facts(text)
        payload = cue_payload or {}

        # 1. Check for explicit payload intent override (validate against grounded data)
        if payload.get("data_intent"):
            try:
                candidate = SemanticDataIntent(payload["data_intent"])
                if candidate == SemanticDataIntent.part_to_whole and len(facts) >= 2:
                    return candidate
                elif candidate == SemanticDataIntent.progress and facts and (facts[0].is_percent or "%" in facts[0].raw or _PROGRESS_RE.search(t_lower)):
                    return candidate
                elif candidate == SemanticDataIntent.trend_over_time and len(facts) >= 2:
                    return candidate
                elif candidate == SemanticDataIntent.positive_negative_change and len(facts) >= 3:
                    return candidate
                elif candidate == SemanticDataIntent.threshold and len(facts) >= 2:
                    return candidate
                elif candidate == SemanticDataIntent.breakdown and len(facts) >= 3:
                    return candidate
                elif candidate in (SemanticDataIntent.category_comparison, SemanticDataIntent.ranked_categories, SemanticDataIntent.single_metric, SemanticDataIntent.takeaway):
                    return candidate
            except ValueError:
                pass

        # 2. Check for Ranked Categories ("top 5", "most common", etc.)
        if _TOP_RANK_RE.search(t_lower) and len(facts) >= 2:
            return SemanticDataIntent.ranked_categories

        # 3. Check for Waterfall intent (start -> delta -> end)
        if (
            _WATERFALL_RE.search(t_lower)
            and len(facts) >= 3
            and any(w in t_lower for w in ("start", "started", "starting", "begin", "began", "initial"))
            and any(w in t_lower for w in ("final", "finish", "finished", "net", "end", "ending", "ended", "balance", "total"))
        ):
            return SemanticDataIntent.positive_negative_change

        # 4. Check for Threshold intent (limit vs damage / actual)
        if _THRESHOLD_RE.search(t_lower) and ("limit" in t_lower or "cap" in t_lower or "threshold" in t_lower) and len(facts) >= 2:
            return SemanticDataIntent.threshold

        # 5. Check for Part-to-Whole (percentages summing to ~100%, or parts summing to total)
        pct_matches = _PERCENT_RE.findall(text)
        if len(pct_matches) >= 2:
            pct_vals = [float(p) for p in pct_matches]
            if 90.0 <= sum(pct_vals) <= 110.0:
                return SemanticDataIntent.part_to_whole

        # 6. Check for Breakdown (total and at least 2 parts with breakdown keywords)
        if _BREAKDOWN_RE.search(t_lower) and len(facts) >= 2:
            v0 = facts[0].value
            sub_facts = facts[1:]
            unique_vals: list[float] = []
            for f in sub_facts:
                if f.value > 0 and not any(abs(u - f.value) < 0.5 for u in unique_vals):
                    unique_vals.append(f.value)
            if v0 > 0 and len(unique_vals) >= 2 and abs(v0 - sum(unique_vals)) <= 1.0:
                return SemanticDataIntent.breakdown

        # 7. Check for Progress / Gauge (e.g. 75% complete, 3 of 4)
        if _PROGRESS_RE.search(t_lower) and len(facts) == 1:
            if facts[0].is_percent or "complete" in t_lower or "progress" in t_lower:
                return SemanticDataIntent.progress

        # 8. Check for Cumulative / Area Trend (composition over time)
        if ("cumulative" in t_lower or "reserves" in t_lower or "total over time" in t_lower or re.search(r"\bQ[1-4]\b", text)) and len(facts) >= 2:
            return SemanticDataIntent.composition_over_time

        # 9. Check for Trend Over Time / Timeline (chronological years/dates or increase from A to B)
        if payload.get("template") == "timeline" or "milestones" in payload or "milestones" in (payload.get("data") or {}):
            return SemanticDataIntent.trend_over_time

        year_matches = _YEAR_RE.findall(text)
        has_year_facts = len(facts) >= 2 and all(1900 <= f.value <= 2100 for f in facts[:2])
        has_temporal_context = any(w in t_lower for w in ("between", "timeline", "milestone", "launch", "founded", "expansion", "growth phase", "evolution", "era"))
        if len(year_matches) >= 2 or has_year_facts or (has_temporal_context and len(facts) >= 2) or (("increased from" in t_lower or "grew from" in t_lower or "dropped from" in t_lower) and len(facts) >= 2):
            return SemanticDataIntent.trend_over_time

        # 10. Check for Process / System Flow Diagram
        if (
            ("request" in t_lower and "cache" in t_lower and "database" in t_lower)
            or ("flow" in t_lower and "through" in t_lower and "into" in t_lower)
            or (payload.get("template") == "diagram" or "nodes" in payload)
        ):
            return SemanticDataIntent.sequence

        # 11. Check for Before / After
        if _BEFORE_AFTER_RE.search(t_lower) and ("before" in t_lower or "previously" in t_lower or "old" in t_lower) and ("after" in t_lower or "now" in t_lower or "new" in t_lower) and len(facts) >= 2:
            return SemanticDataIntent.before_after

        # 12. Multi-category comparison or conceptual comparison or multi-metric telemetry
        if len(facts) >= 2 or _COMPARISON_RE.search(t_lower) or any(w in t_lower for w in [" versus ", " vs ", " vs. ", " compared to ", "different from", "unlike", "not the same as", "ongoing cost"]):
            return SemanticDataIntent.category_comparison

        # 13. Single metric fallback
        if len(facts) == 1:
            return SemanticDataIntent.single_metric

        return SemanticDataIntent.takeaway

    def select_visual_grammar(
        self,
        intent: SemanticDataIntent,
        narration: str,
        facts: list[CanonicalNumericFact],
        cue_payload: dict[str, Any] | None = None,
    ) -> tuple[VisualGrammar, str]:
        """Selects appropriate visual grammar and layout variant based on intent and diversity memory."""
        t_lower = (narration or "").lower()

        if intent == SemanticDataIntent.part_to_whole:
            variants = ["donut_center_stat", "donut_reveal", "pie_focus", "segmented_ring"]
            variant = self.memory.choose_diverse_variant("pie", variants)
            return VisualGrammar.pie, variant

        if intent == SemanticDataIntent.trend_over_time:
            if cue_payload and (cue_payload.get("template") == "timeline" or "milestones" in cue_payload or "milestones" in (cue_payload.get("data") or {})):
                return VisualGrammar.timeline, "timeline_v2"
            if any(w in t_lower for w in ("timeline", "milestone", "launch", "founded", "expansion", "growth phase", "evolution", "era")):
                return VisualGrammar.timeline, "timeline_v2"
            variants = ["line_draw", "line_with_points", "line_focus_latest"]
            variant = self.memory.choose_diverse_variant("line", variants)
            return VisualGrammar.line, variant

        if intent == SemanticDataIntent.composition_over_time:
            variants = ["area_trend", "stacked_area"]
            variant = self.memory.choose_diverse_variant("area", variants)
            return VisualGrammar.area, variant

        if intent == SemanticDataIntent.ranked_categories:
            variants = ["ranked_horizontal_bars", "leaderboard_reveal"]
            variant = self.memory.choose_diverse_variant("ranked_list", variants)
            return VisualGrammar.ranked_list, variant

        if intent == SemanticDataIntent.progress:
            variants = ["radial_gauge", "progress_ring", "linear_meter"]
            variant = self.memory.choose_diverse_variant("gauge", variants)
            return VisualGrammar.gauge, variant

        if intent == SemanticDataIntent.positive_negative_change:
            variants = ["waterfall_steps", "waterfall_variance"]
            variant = self.memory.choose_diverse_variant("waterfall", variants)
            return VisualGrammar.waterfall, variant

        if intent == SemanticDataIntent.threshold:
            variants = ["threshold_v2", "threshold_split"]
            variant = self.memory.choose_diverse_variant("threshold", variants)
            return VisualGrammar.threshold, variant

        if intent == SemanticDataIntent.before_after:
            variants = ["split_screen", "value_shift", "side_by_side"]
            variant = self.memory.choose_diverse_variant("before_after", variants)
            return VisualGrammar.before_after, variant

        if intent == SemanticDataIntent.sequence:
            return VisualGrammar.diagram, "flow_diagram"

        if intent == SemanticDataIntent.breakdown:
            return VisualGrammar.breakdown, "stacked_breakdown"

        if intent == SemanticDataIntent.category_comparison:
            if cue_payload and (cue_payload.get("template") == "data_grid" or "metrics" in cue_payload):
                return VisualGrammar.data_grid, "data_grid_matrix"
            if len(facts) >= 4 and any(w in t_lower for w in ("uptime", "latency", "requests", "signals", "telemetry", "error rate", "indicators")):
                return VisualGrammar.data_grid, "data_grid_matrix"
            if any(w in t_lower for w in [" versus ", " vs ", " vs. ", " compared to ", "different from", "unlike", "not the same as", "ongoing cost", "deductible", "covers", "premium"]):
                variants = ["split_compare", "compare_two"]
                variant = self.memory.choose_diverse_variant("comparison", variants)
                return VisualGrammar.comparison, variant
            if len(facts) == 2:
                variants = ["compare_two", "split_compare"]
            else:
                variants = ["ranked_bars", "progressive_bars", "highlight_one"]
            variant = self.memory.choose_diverse_variant("bar", variants)
            return VisualGrammar.bar, variant

        if intent == SemanticDataIntent.single_metric:
            delta_keywords = bool(re.search(r"\b(?:grew|grown|grow|increase|increased|rose|risen|jumped|surged|climb|climbed|fell|fall|dropped|drop|decrease|decreased|decline|declined|down from|up from|from\s+\$?\d+.*to\s+\$?\d+)\b", t_lower))
            if delta_keywords:
                variants = ["metric_delta"]
            else:
                variants = ["metric_hero", "metric_with_context"]
            variant = self.memory.choose_diverse_variant("metric", variants)
            return VisualGrammar.metric, variant

        return VisualGrammar.kinetic_statement, "kinetic_statement"

    def validate_and_build_props(
        self,
        grammar: VisualGrammar,
        variant: str,
        intent: SemanticDataIntent,
        narration: str,
        facts: list[CanonicalNumericFact],
        headline: str,
        eyebrow: str | None = None,
        cue_payload: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any], str | None]:
        """Validates semantic constraints and builds grounded props. Returns (is_valid, props, error_reason)."""
        t_lower = (narration or "").lower()

        payload_dict = cue_payload if isinstance(cue_payload, dict) else {}
        payload_data = payload_dict.get("data") if isinstance(payload_dict.get("data"), dict) else payload_dict
        payload_items = (
            payload_data.get("items")
            or payload_data.get("slices")
            or payload_data.get("segments")
            or payload_data.get("options")
            or payload_data.get("bars")
        )
        payload_labels: list[str] = []
        if isinstance(payload_items, list):
            for it in payload_items:
                if isinstance(it, dict) and it.get("label"):
                    payload_labels.append(str(it["label"]).strip())

        # 1. PIE / DONUT VALIDATION
        if grammar in (VisualGrammar.pie, VisualGrammar.donut):
            # Negative rule: Reject if threshold/limit or time series
            if _THRESHOLD_RE.search(t_lower) and ("limit" in t_lower or "cap" in t_lower):
                return False, {}, "Pie rejected: data represents a threshold limit vs damage, not a part-to-whole whole."
            if _YEAR_RE.search(t_lower) and len(_YEAR_RE.findall(t_lower)) >= 2:
                return False, {}, "Pie rejected: data represents an ordered time series."

            pct_matches = _PERCENT_RE.findall(narration)
            items: list[dict[str, Any]] = []
            if len(pct_matches) >= 2:
                tokens = [w.strip(" ,.;:") for w in narration.split()]
                assigned_tokens = set()
                for i, p_str in enumerate(pct_matches):
                    p_val = float(p_str)
                    label = payload_labels[i] if i < len(payload_labels) else None
                    if not label or label.lower().startswith("item ") or label.lower().startswith("option "):
                        # Find category keyword nearby
                        for tok in tokens:
                            tok_low = tok.lower()
                            if tok_low in ("premium", "standard", "basic", "plan a", "plan b", "plan c", "tier 1", "tier 2", "yes", "no", "first", "second", "third") and tok_low not in assigned_tokens:
                                label = tok.upper()
                                assigned_tokens.add(tok_low)
                                break
                    if not label:
                        label = f"Option {i + 1}"
                    items.append({
                        "label": label,
                        "value": p_val,
                        "display_value": f"{int(p_val)}%",
                        "percentage": p_val,
                        "highlight": (i == 0 or p_val == max([float(x) for x in pct_matches])),
                    })
                total_sum = sum(float(x) for x in pct_matches)
                if not (80.0 <= total_sum <= 120.0):
                    return False, {}, f"Pie rejected: sum of percentages ({total_sum}) is not close to 100%."
            elif len(facts) >= 2:
                total_val = sum(f.value for f in facts)
                if total_val <= 0:
                    return False, {}, "Pie rejected: total sum is non-positive."
                for i, f in enumerate(facts[:6]):
                    pct = round((f.value / total_val) * 100, 1)
                    items.append({
                        "label": f"Part {i + 1}",
                        "value": f.value,
                        "display_value": f.display,
                        "percentage": pct,
                        "highlight": (i == 0),
                    })
            else:
                return False, {}, "Pie rejected: requires at least 2 grounded numeric items."

            props = {
                "headline": headline,
                "eyebrow": eyebrow or "DISTRIBUTION",
                "items": items,
                "variant": variant,
                "focus_label": items[0]["label"] if items else None,
                "layout_archetype": variant,
            }
            return True, props, None

        # 2. GAUGE / PROGRESS VALIDATION
        if grammar == VisualGrammar.gauge:
            if not facts:
                return False, {}, "Gauge rejected: no grounded numeric fact."
            f0 = facts[0]
            if not f0.is_percent and "%" not in f0.raw and not _PROGRESS_RE.search(t_lower):
                return False, {}, "Gauge rejected: raw unbounded value without explicit maximum bound."

            cur_val = f0.value
            max_val = 100.0
            if cur_val > 100.0:
                max_val = cur_val * 1.25

            props = {
                "headline": headline,
                "eyebrow": eyebrow or "PROGRESS",
                "current_value": cur_val,
                "max_value": max_val,
                "min_value": 0.0,
                "display_value": f0.display,
                "unit": "%" if (f0.is_percent or "%" in f0.raw) else "",
                "label": "Completed",
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 3. WATERFALL VALIDATION
        if grammar == VisualGrammar.waterfall:
            if len(facts) < 3:
                return False, {}, "Waterfall rejected: requires start value, at least 1 delta, and ending value."
            start_f = facts[0]
            end_f = facts[-1]
            deltas_f = facts[1:-1]
            start_v = start_f.value
            end_v = end_f.value

            step_items: list[dict[str, Any]] = []
            for idx, d in enumerate(deltas_f):
                val = d.value
                val_int = int(val) if val.is_integer() else val
                tok_str = str(val_int)
                tok_pos = narration.lower().find(d.display.lower())
                if tok_pos == -1:
                    tok_pos = narration.lower().find(tok_str)

                prev_text = narration.lower()[max(0, tok_pos - 20): tok_pos] if tok_pos != -1 else ""
                post_text = narration.lower()[tok_pos: min(len(narration), tok_pos + len(tok_str) + 20)] if tok_pos != -1 else ""

                is_neg = False
                if any(w in prev_text for w in ["minus", "discount", "deduct", "less", "drop", "decrease", "off", "-"]):
                    is_neg = True
                elif any(w in post_text for w in ["discount", "deduction", "deduct", "off", "drop", "decrease", "savings"]):
                    is_neg = True
                elif "-" in d.raw:
                    is_neg = True

                delta_v = -abs(val) if is_neg else abs(val)

                step_items.append({
                    "label": f"Step {idx + 1}",
                    "delta": delta_v,
                    "display_value": f"{'+' if delta_v > 0 else ''}{d.display}",
                })

            calculated_end = start_v + sum(s["delta"] for s in step_items)
            if abs(calculated_end - end_v) > 2.0:
                return False, {}, f"Waterfall rejected: arithmetic mismatch ({start_v} + deltas = {calculated_end} != {end_v})."

            props = {
                "headline": headline,
                "eyebrow": eyebrow or "COST BREAKDOWN",
                "start_value": start_v,
                "start_label": "Starting",
                "steps": step_items,
                "end_value": end_v,
                "end_label": "Final",
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 4. RANKED LIST VALIDATION
        if grammar == VisualGrammar.ranked_list:
            rank_facts = facts
            if len(facts) >= 3 and _TOP_RANK_RE.search(t_lower):
                # If first fact is integer count matching "top N"
                top_m = _TOP_RANK_RE.search(t_lower)
                if top_m and str(int(facts[0].value)) in top_m.group(0):
                    rank_facts = facts[1:]

            if len(rank_facts) < 2:
                return False, {}, "Ranked list rejected: requires at least 2 items."
            items = []
            for idx, f in enumerate(rank_facts[:5]):
                items.append({
                    "rank": idx + 1,
                    "label": f"Item {idx + 1}",
                    "value": f.value,
                    "display_value": f.display,
                    "highlight": (idx == 0),
                })
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "TOP RANKINGS",
                "items": items,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 5. LINE CHART VALIDATION
        if grammar == VisualGrammar.line:
            if len(facts) < 2:
                return False, {}, "Line chart rejected: requires at least 2 data points."
            points = []
            years = _YEAR_RE.findall(narration)
            for idx, f in enumerate(facts[:6]):
                x_lbl = years[idx] if idx < len(years) else f"T{idx + 1}"
                points.append({
                    "x_label": x_lbl,
                    "y_value": f.value,
                    "display_value": f.display,
                })
            unit_val = "%" if facts[0].is_percent else ("$" if facts[0].is_currency else None)
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "TREND OVER TIME",
                "points": points,
                "unit": unit_val,
                "show_area": True,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 6. AREA CHART VALIDATION
        if grammar == VisualGrammar.area:
            if len(facts) < 2:
                return False, {}, "Area chart rejected: requires at least 2 data points."
            points = []
            years = _YEAR_RE.findall(narration)
            for idx, f in enumerate(facts[:6]):
                x_lbl = years[idx] if idx < len(years) else f"T{idx + 1}"
                points.append({
                    "x_label": x_lbl,
                    "y_value": f.value,
                    "display_value": f.display,
                })
            unit_val = "%" if facts[0].is_percent else ("$" if facts[0].is_currency else None)
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "CUMULATIVE TREND",
                "points": points,
                "unit": unit_val,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 7. BEFORE / AFTER VALIDATION
        if grammar == VisualGrammar.before_after:
            if len(facts) < 2:
                return False, {}, "Before/After rejected: requires at least 2 values."
            f_before = facts[0]
            f_after = facts[1]
            delta = f_after.value - f_before.value
            delta_str = f"{'+' if delta > 0 else ''}{delta:g}"
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "COMPARISON",
                "before_label": "Before",
                "before_value": f_before.display,
                "before_numeric": f_before.value,
                "after_label": "After",
                "after_value": f_after.display,
                "after_numeric": f_after.value,
                "delta_display": delta_str,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 8. STACKED BAR VALIDATION
        if grammar == VisualGrammar.stacked_bar:
            if len(facts) < 3:
                return False, {}, "Stacked bar rejected: requires total and at least 2 segments."
            total_v = facts[0].value
            seg_f = facts[1:]
            seg_sum = sum(f.value for f in seg_f)
            if abs(total_v - seg_sum) > 2.0:
                return False, {}, f"Stacked bar rejected: parts sum ({seg_sum}) does not match total ({total_v})."

            segs = []
            for i, f in enumerate(seg_f):
                segs.append({
                    "label": f"Part {i + 1}",
                    "value": f.value,
                    "display_value": f.display,
                    "highlight": (i == 0),
                })
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "BREAKDOWN",
                "total": total_v,
                "total_display": facts[0].display,
                "segments": segs,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 9. THRESHOLD VALIDATION
        if grammar == VisualGrammar.threshold:
            if len(facts) < 2:
                return False, {}, "Threshold rejected: requires threshold limit and actual value."
            f0, f1 = facts[0], facts[1]
            limit_val = f0.value
            act_val = f1.value
            limit_disp = f0.display
            act_disp = f1.display
            if "limit" in f1.raw.lower():
                limit_val, act_val = f1.value, f0.value
                limit_disp, act_disp = f1.display, f0.display

            thresh_info = extract_grounded_threshold_labels(narration)
            thresh_label = payload_data.get("threshold_label") or thresh_info.get("threshold_label") or "Limit"
            subtext_val = payload_data.get("subtext")
            is_exceeded = act_val > limit_val
            props = {
                "headline": headline or thresh_info.get("subject") or "THRESHOLD",
                "eyebrow": eyebrow or (f"{thresh_label.upper()} EXCEEDED" if is_exceeded else thresh_label.upper()),
                "current_value": act_val,
                "current_display": act_disp,
                "threshold_value": limit_val,
                "threshold_display": limit_disp,
                "threshold_label": thresh_label,
                "subtext": subtext_val,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 10. COMPARISON VALIDATION
        if grammar == VisualGrammar.comparison:
            if len(facts) >= 2:
                items = []
                for i, f in enumerate(facts[:4]):
                    lbl = payload_labels[i] if i < len(payload_labels) else None
                    if not lbl or lbl.lower().startswith("option ") or lbl.lower().startswith("item "):
                        lbl = f"Option {i + 1}"
                    items.append({
                        "label": lbl,
                        "value": f.display,
                        "numeric_value": f.value,
                        "highlight": (i == 0),
                    })
                props = {
                    "headline": headline,
                    "eyebrow": eyebrow or "COMPARISON",
                    "items": items,
                    "variant": variant,
                    "layout_archetype": variant,
                }
                return True, props, None
            elif payload_items and isinstance(payload_items, list) and len(payload_items) >= 2:
                valid_items = []
                for idx, it in enumerate(payload_items[:2]):
                    if isinstance(it, dict) and it.get("label"):
                        l_val = str(it.get("value") or it["label"]).strip()
                        valid_items.append({
                            "label": str(it["label"]).strip().upper(),
                            "value": l_val,
                            "highlight": bool(it.get("highlight", idx == 0)),
                        })
                if len(valid_items) >= 2:
                    props = {
                        "headline": headline or f"{valid_items[0]['label']} VS {valid_items[1]['label']}",
                        "eyebrow": eyebrow or "CONCEPT COMPARISON",
                        "items": valid_items,
                        "variant": variant,
                        "layout_archetype": variant,
                    }
                    return True, props, None
            elif _COMPARISON_RE.search(t_lower):
                # Conceptual/qualitative comparison grounded directly in narration text
                ents = extract_grounded_comparison_entities(narration)
                if ents:
                    e1, e2 = ents
                    def1 = extract_grounded_entity_definition(e1, narration)
                    def2 = extract_grounded_entity_definition(e2, narration)

                    val1 = def1 if def1 else e1.title()
                    val2 = def2 if def2 else e2.title()

                    is_e1_hl = e1.lower() in t_lower and e2.lower() not in t_lower
                    is_e2_hl = e2.lower() in t_lower and e1.lower() not in t_lower
                    if not is_e1_hl and not is_e2_hl:
                        is_e1_hl = True
                        is_e2_hl = False

                    props = {
                        "headline": headline or f"{e1.upper()} VS {e2.upper()}",
                        "eyebrow": eyebrow or "CONCEPT COMPARISON",
                        "items": [
                            {"label": e1.upper(), "value": val1, "highlight": is_e1_hl},
                            {"label": e2.upper(), "value": val2, "highlight": is_e2_hl},
                        ],
                        "variant": variant,
                        "layout_archetype": variant,
                    }
                    return True, props, None
            return False, {}, "Comparison rejected: requires at least 2 comparison items or grounded comparison entities in narration."

        # 11. BREAKDOWN VALIDATION
        if grammar == VisualGrammar.breakdown:
            if len(facts) < 2:
                return False, {}, "Breakdown rejected: requires total and at least 2 parts."
            v0 = facts[0].value
            sub_facts = facts[1:]
            unique_parts: list[CanonicalNumericFact] = []
            for f in sub_facts:
                if f.value > 0 and not any(abs(u.value - f.value) < 0.5 for u in unique_parts):
                    unique_parts.append(f)
            if len(unique_parts) < 2:
                return False, {}, "Breakdown rejected: requires at least 2 distinct parts."
            parts_sum = sum(u.value for u in unique_parts)
            if abs(v0 - parts_sum) > 1.0:
                return False, {}, f"Breakdown rejected: math mismatch ({v0} != {parts_sum})."

            lbl0 = payload_labels[0] if len(payload_labels) > 0 else "Total"
            lbl1 = payload_labels[1] if len(payload_labels) > 1 else "Part 1"
            lbl2 = payload_labels[2] if len(payload_labels) > 2 else "Part 2"
            items = [
                {"label": lbl0, "value": facts[0].display, "numeric_value": facts[0].value},
                {"label": lbl1, "value": unique_parts[0].display, "numeric_value": unique_parts[0].value},
                {"label": lbl2, "value": unique_parts[1].display, "numeric_value": unique_parts[1].value},
            ]
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "BREAKDOWN",
                "items": items,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 12. BAR CHART VALIDATION
        if grammar == VisualGrammar.bar:
            if len(facts) < 2:
                return False, {}, "Bar chart rejected: requires at least 2 items."
            items = []
            for i, f in enumerate(facts[:5]):
                lbl = payload_labels[i] if i < len(payload_labels) else f"Plan {chr(65 + i)}"
                items.append({
                    "label": lbl,
                    "value": f.value,
                    "display_value": f.display,
                })
            unit_val = "%" if facts[0].is_percent else ("$" if facts[0].is_currency else None)
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "COMPARISON",
                "items": items,
                "baseline": 0.0,
                "unit": unit_val,
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 13. METRIC HERO VALIDATION
        if grammar == VisualGrammar.metric:
            val_str = facts[0].display if facts else "$0"
            num_val = facts[0].value if facts else 0.0
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "KEY METRIC",
                "value": val_str,
                "numeric_value": num_val,
                "prefix": "$" if (facts and facts[0].is_currency) else None,
                "label": payload_data.get("label") or "Metric",
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 14. DIAGRAM VALIDATION
        if grammar == VisualGrammar.diagram:
            raw_nodes = payload_dict.get("nodes") or payload_data.get("nodes")
            if not raw_nodes:
                nodes_list = []
                if "edge proxy" in t_lower or ("edge" in t_lower and "proxy" in t_lower):
                    nodes_list.append({"id": "n1", "label": "EDGE PROXY"})
                elif "edge" in t_lower:
                    nodes_list.append({"id": "n1", "label": "EDGE"})

                if "api service" in t_lower or "api cluster" in t_lower:
                    nodes_list.append({"id": "n2", "label": "API SERVICE"})
                elif "api" in t_lower:
                    nodes_list.append({"id": "n2", "label": "API"})
                elif "cluster" in t_lower or "service" in t_lower:
                    nodes_list.append({"id": "n2", "label": "SERVICE"})

                if "redis cache" in t_lower or ("redis" in t_lower and "cache" in t_lower):
                    nodes_list.append({"id": "n3", "label": "REDIS CACHE"})
                elif "redis" in t_lower:
                    nodes_list.append({"id": "n3", "label": "REDIS"})
                elif "cache" in t_lower:
                    nodes_list.append({"id": "n3", "label": "CACHE"})

                if "postgres db" in t_lower or "postgres database" in t_lower or ("postgres" in t_lower and "db" in t_lower):
                    nodes_list.append({"id": "n4", "label": "POSTGRES DB"})
                elif "database" in t_lower:
                    nodes_list.append({"id": "n4", "label": "DATABASE"})
                elif "storage" in t_lower:
                    nodes_list.append({"id": "n4", "label": "STORAGE"})

                if len(nodes_list) >= 2:
                    raw_nodes = nodes_list

            if isinstance(raw_nodes, list) and len(raw_nodes) >= 2:
                edges = payload_dict.get("edges") or payload_data.get("edges")
                if not edges:
                    edges = [
                        {"from_node": raw_nodes[idx]["id"], "to_node": raw_nodes[idx + 1]["id"]}
                        for idx in range(len(raw_nodes) - 1)
                    ]
                props = {
                    "headline": headline,
                    "eyebrow": eyebrow or "SYSTEM DATAFLOW",
                    "nodes": raw_nodes,
                    "edges": edges,
                    "flow_direction": payload_dict.get("flow_direction") or "horizontal",
                    "variant": variant,
                    "layout_archetype": variant,
                }
                return True, props, None
            return False, {}, "Diagram requires at least 2 sequence nodes."

        # 15. DATA GRID VALIDATION
        if grammar == VisualGrammar.data_grid:
            raw_items = payload_dict.get("items") or payload_data.get("items")
            if not raw_items and len(facts) >= 3:
                raw_items = [
                    {"label": f"Metric {i + 1}", "value": f.display, "numeric_value": f.value}
                    for i, f in enumerate(facts[:6])
                ]
            if isinstance(raw_items, list) and len(raw_items) >= 3:
                props = {
                    "headline": headline,
                    "eyebrow": eyebrow or "PLATFORM TELEMETRY",
                    "items": raw_items,
                    "columns": int(payload_dict.get("columns") or 2),
                    "variant": variant,
                    "layout_archetype": variant,
                }
                return True, props, None
            return False, {}, "Data grid requires at least 3 items."

        # 16. TIMELINE VALIDATION
        if grammar == VisualGrammar.timeline:
            raw_milestones = payload_dict.get("milestones") or payload_data.get("milestones")
            if not raw_milestones:
                years = _YEAR_RE.findall(narration)
                if not years:
                    num_matches = re.findall(r"\b(20\d\d|19\d\d)\b", narration)
                    years = num_matches
                if not years and len(facts) >= 2 and all(1900 <= f.value <= 2100 for f in facts[:2]):
                    years = [str(int(f.value)) for f in facts[:2]]
                if len(years) >= 2:
                    raw_milestones = [
                        {"time": str(years[0]), "title": "Beta Launch", "highlight": False},
                        {"time": str(years[-1]), "title": "Global Scaling", "highlight": True},
                    ]
            if isinstance(raw_milestones, list) and len(raw_milestones) >= 2:
                milestones_list = []
                for idx, m in enumerate(raw_milestones[:5]):
                    if isinstance(m, dict):
                        m_time = str(m.get("time") or m.get("year") or m.get("label") or f"T{idx+1}").strip()
                        m_title = str(m.get("title") or m.get("event") or m.get("description") or m_time).strip()
                        milestones_list.append({
                            "time": m_time,
                            "title": m_title,
                            "highlight": bool(m.get("highlight", idx == len(raw_milestones) - 1)),
                        })
                if len(milestones_list) >= 2:
                    props = {
                        "headline": headline,
                        "eyebrow": eyebrow or "GLOBAL EXPANSION",
                        "milestones": milestones_list,
                        "variant": variant,
                        "layout_archetype": variant,
                    }
                    return True, props, None
            return False, {}, "Timeline requires at least 2 milestones."

        # Default statement / callout
        props = {
            "headline": headline,
            "eyebrow": eyebrow or "KEY TAKEAWAY",
            "variant": variant,
            "layout_archetype": variant,
        }
        return True, props, None

    def resolve_fallback(
        self,
        failed_grammar: VisualGrammar,
        narration: str,
        facts: list[CanonicalNumericFact],
        headline: str,
        eyebrow: str | None = None,
    ) -> tuple[VisualGrammar, str, dict[str, Any]]:
        """Resolves fallback grammar deterministically when primary validation fails."""
        logger.warning("Resolving fallback for failed grammar: {}", failed_grammar.value)

        if len(facts) >= 2:
            items = [
                {"label": f"Item {i + 1}", "value": f.value, "display_value": f.display}
                for i, f in enumerate(facts[:4])
            ]
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "COMPARISON",
                "items": items,
                "variant": "compare_two" if len(items) == 2 else "progressive_bars",
                "layout_archetype": "split_compare" if len(items) == 2 else "bar_chart_v2",
            }
            return VisualGrammar.bar, "bar_chart_v2", props

        if len(facts) == 1:
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "KEY METRIC",
                "value": facts[0].display,
                "numeric_value": facts[0].value,
                "variant": "metric_hero",
                "layout_archetype": "metric_hero",
            }
            return VisualGrammar.metric, "metric_hero", props

        props = {
            "headline": headline,
            "subheadline": eyebrow or "KEY TAKEAWAY",
            "variant": "kinetic_statement",
            "layout_archetype": "kinetic_statement",
        }
        return VisualGrammar.kinetic_statement, "kinetic_statement", props

    def direct_visual_specification(
        self,
        narration: str,
        headline: str,
        eyebrow: str | None = None,
        cue_payload: dict[str, Any] | None = None,
        source_cue_id: str = "C001",
    ) -> DataVisualizationSpec:
        """Complete Director pipeline: Intent -> Grammar -> Validation -> Fallback -> Memory -> Spec."""
        facts = extract_canonical_numeric_facts(narration)
        intent = self.classify_data_intent(narration, facts, cue_payload)
        grammar, variant = self.select_visual_grammar(intent, narration, facts, cue_payload)

        is_valid, props, error_msg = self.validate_and_build_props(
            grammar=grammar,
            variant=variant,
            intent=intent,
            narration=narration,
            facts=facts,
            headline=headline,
            eyebrow=eyebrow,
            cue_payload=cue_payload,
        )

        if not is_valid:
            logger.info("Validation rejected grammar {}: {}. Triggering fallback.", grammar.value, error_msg)
            grammar, variant, props = self.resolve_fallback(
                failed_grammar=grammar,
                narration=narration,
                facts=facts,
                headline=headline,
                eyebrow=eyebrow,
            )

        self.memory.record_usage(grammar.value, variant)

        spec = DataVisualizationSpec(
            intent=intent,
            grammar=grammar,
            variant=variant,
            headline=headline,
            eyebrow=eyebrow,
            props=props,
            grounded_values=[f.value for f in facts],
            grounded_labels=[f.display for f in facts],
            source_cue_ids=[source_cue_id],
            provenance="narration_extracted",
            confidence=1.0 if is_valid else 0.8,
        )
        return spec
