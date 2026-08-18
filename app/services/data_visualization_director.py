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
_TOP_RANK_RE = re.compile(r"\b(?:top\s*\d+|most\s+common|ranked|ranking|largest|smallest|leaders?|causes?)\b", re.IGNORECASE)
_PROGRESS_RE = re.compile(r"\b(?:progress|complete|completed|done|finished|steps?|fraction|goal|quota)\b", re.IGNORECASE)
_THRESHOLD_RE = re.compile(r"\b(?:limit|threshold|maximum|cap|excess|exceed|over\s*limit|damage|ceiling)\b", re.IGNORECASE)
_WATERFALL_RE = re.compile(r"\b(?:start(?:ed|ing)?|fees?|discount|deduction|final|net|balance|adjust(?:ment)?)\b", re.IGNORECASE)
_BEFORE_AFTER_RE = re.compile(r"\b(?:before|after|previously|now|old|new|prior|shifted|transition)\b", re.IGNORECASE)
_BREAKDOWN_RE = re.compile(r"\b(?:breakdown|total|deductible|insurance\s*covers|out\s*of\s*pocket|you\s*pay)\b", re.IGNORECASE)


class VisualDiversityMemory:
    """Tracks recently used DATA visual grammars and variants to avoid repetitive visual slides."""

    def __init__(self, max_history: int = 6) -> None:
        self.max_history = max_history
        self._history: list[tuple[str, str]] = []  # [(grammar, variant), ...]

    def record_usage(self, grammar: str, variant: str) -> None:
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

        # 1. Check for explicit payload intent override
        if payload.get("data_intent"):
            try:
                return SemanticDataIntent(payload["data_intent"])
            except ValueError:
                pass

        # 2. Check for Ranked Categories ("top 5", "most common", etc.)
        if _TOP_RANK_RE.search(t_lower) and len(facts) >= 2:
            return SemanticDataIntent.ranked_categories

        # 3. Check for Waterfall intent (start -> delta -> end)
        if _WATERFALL_RE.search(t_lower) and len(facts) >= 3 and ("start" in t_lower or "starting" in t_lower) and ("final" in t_lower or "net" in t_lower):
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
        if _BREAKDOWN_RE.search(t_lower) and len(facts) >= 3:
            v0 = facts[0].value
            v1 = facts[1].value
            v2 = facts[2].value
            if v0 > 0 and v1 > 0 and v2 > 0 and abs(v0 - (v1 + v2)) <= 1.0:
                return SemanticDataIntent.breakdown

        # 7. Check for Progress / Gauge (e.g. 75% complete, 3 of 4)
        if _PROGRESS_RE.search(t_lower) and len(facts) == 1:
            if facts[0].is_percent or "complete" in t_lower or "progress" in t_lower:
                return SemanticDataIntent.progress

        # 8. Check for Cumulative / Area Trend (composition over time)
        if ("cumulative" in t_lower or "reserves" in t_lower or "total over time" in t_lower or re.search(r"\bQ[1-4]\b", text)) and len(facts) >= 2:
            return SemanticDataIntent.composition_over_time

        # 9. Check for Trend Over Time (chronological years/dates or increase from A to B)
        year_matches = _YEAR_RE.findall(text)
        if len(year_matches) >= 2 or (("increased from" in t_lower or "grew from" in t_lower or "dropped from" in t_lower) and len(facts) >= 2):
            return SemanticDataIntent.trend_over_time

        # 10. Check for Before / After
        if _BEFORE_AFTER_RE.search(t_lower) and ("before" in t_lower or "previously" in t_lower or "old" in t_lower) and ("after" in t_lower or "now" in t_lower or "new" in t_lower) and len(facts) >= 2:
            return SemanticDataIntent.before_after

        # 10. Multi-category comparison
        if len(facts) >= 2:
            return SemanticDataIntent.category_comparison

        # 11. Single metric fallback
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

        if intent == SemanticDataIntent.breakdown:
            return VisualGrammar.breakdown, "stacked_breakdown"

        if intent == SemanticDataIntent.category_comparison:
            if len(facts) == 2:
                variants = ["compare_two", "split_compare"]
            else:
                variants = ["ranked_bars", "progressive_bars", "highlight_one"]
            variant = self.memory.choose_diverse_variant("bar", variants)
            return VisualGrammar.bar, variant

        if intent == SemanticDataIntent.single_metric:
            variants = ["metric_hero", "metric_with_context", "metric_delta"]
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
    ) -> tuple[bool, dict[str, Any], str | None]:
        """Validates semantic constraints and builds grounded props. Returns (is_valid, props, error_reason)."""
        t_lower = (narration or "").lower()

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
                    label = f"Option {i + 1}"
                    # Find category keyword nearby
                    for tok in tokens:
                        tok_low = tok.lower()
                        if tok_low in ("premium", "standard", "basic", "plan a", "plan b", "plan c", "tier 1", "tier 2", "yes", "no", "first", "second", "third") and tok_low not in assigned_tokens:
                            label = tok.upper()
                            assigned_tokens.add(tok_low)
                            break
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
                        "label": f.context_hint or f"Part {i + 1}",
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

            props = {
                "headline": headline,
                "eyebrow": eyebrow or "POLICY THRESHOLD",
                "current_value": act_val,
                "current_display": act_disp,
                "threshold_value": limit_val,
                "threshold_display": limit_disp,
                "threshold_label": "Coverage Limit",
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

        # 10. BAR CHART / COMPARISON VALIDATION
        if grammar == VisualGrammar.bar:
            if len(facts) < 2:
                return False, {}, "Bar chart rejected: requires at least 2 items."
            items = []
            for i, f in enumerate(facts[:5]):
                items.append({
                    "label": f"Plan {chr(65 + i)}",
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

        # 11. METRIC HERO VALIDATION
        if grammar == VisualGrammar.metric:
            val_str = facts[0].display if facts else "$0"
            num_val = facts[0].value if facts else 0.0
            props = {
                "headline": headline,
                "eyebrow": eyebrow or "KEY METRIC",
                "value": val_str,
                "numeric_value": num_val,
                "prefix": "$" if (facts and facts[0].is_currency) else None,
                "label": "Metric",
                "variant": variant,
                "layout_archetype": variant,
            }
            return True, props, None

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
