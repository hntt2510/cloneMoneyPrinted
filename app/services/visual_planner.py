from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.models.project import (
    BrollPayload,
    BrollSemanticIntent,
    DataPayload,
    DataTemplate,
    DocumentPayload,
    ProjectSpec,
    TextPayload,
    TimelineCue,
    VisualCue,
    VisualPlan,
    VisualPurpose,
    VisualType,
)
from app.services import llm
from app.services.data_visualization_director import (
    DataVisualizationDirector,
    extract_grounded_comparison_entities,
    extract_grounded_entity_definition,
    extract_grounded_threshold_labels,
)
from app.services.numeric_parser import (
    CanonicalNumericFact,
    extract_canonical_numeric_facts,
)

BATCH_SIZE = 10
REPAIR_ATTEMPTS = 2
MIN_DURATION_SECONDS = 0.5
MAX_SEARCH_QUERY_WORDS = 8

_DOCUMENT_RE = re.compile(
    r"\b(article|document|study|report|filing|memo|record|evidence|exhibit|paperwork|policy document|form|publication)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"\b(versus|vs\.?|compare|compared|different\s+from|very\s+different\s+from|unlike|not\s+the\s+same\s+as|one\s+is|while\s+the\s+other|in\s+contrast\s+to|on\s+the\s+other\s+hand|whereas|more\s+than|less\s+than|higher\s+than|lower\s+than|increase|decrease|growth|decline)\b",
    re.IGNORECASE,
)


def grammar_to_data_template(grammar: Any) -> DataTemplate:
    val = grammar.value if hasattr(grammar, "value") else str(grammar).lower()
    mapping = {
        "metric": DataTemplate.number,
        "number": DataTemplate.number,
        "counter": DataTemplate.counter,
        "comparison": DataTemplate.comparison,
        "breakdown": DataTemplate.breakdown,
        "bar": DataTemplate.bar_chart,
        "bar_chart": DataTemplate.bar_chart,
        "stacked_bar": DataTemplate.stacked_bar,
        "line": DataTemplate.line_chart,
        "line_chart": DataTemplate.line_chart,
        "area": DataTemplate.area,
        "area_chart": DataTemplate.area,
        "pie": DataTemplate.pie,
        "donut": DataTemplate.donut,
        "threshold": DataTemplate.threshold,
        "gauge": DataTemplate.gauge,
        "timeline": DataTemplate.timeline,
        "waterfall": DataTemplate.waterfall,
        "ranked_list": DataTemplate.ranked_list,
        "before_after": DataTemplate.before_after,
        "age_marker": DataTemplate.age_marker,
        "callout": DataTemplate.callout,
        "kinetic_statement": DataTemplate.callout,
    }
    return mapping.get(val, DataTemplate.callout)


class PlannerError(ValueError):
    """Raised when the LLM planner returns an invalid visual decision."""


class PlannerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    order: int
    visual_type: VisualType
    purpose: VisualPurpose
    payload: dict[str, Any]
    visual_group_id: str | None = None


class PlannerBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cues: list[PlannerDecision]


def _strip_code_fence(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _parse_batch_response(value: str) -> PlannerBatch:
    raw = json.loads(_strip_code_fence(value))
    if isinstance(raw, list):
        raw = {"cues": raw}
    return PlannerBatch.model_validate(raw)


def _validate_numeric_grounding(
    facts_to_check: list[CanonicalNumericFact],
    allowed_facts: list[CanonicalNumericFact],
    cue_id: str,
    payload_type: str,
) -> None:
    """Validate that all numeric facts in facts_to_check are grounded in allowed_facts."""
    ungrounded: list[CanonicalNumericFact] = []
    for f in facts_to_check:
        if not any(f.matches(a) for a in allowed_facts):
            ungrounded.append(f)

    if ungrounded:
        formatted = ", ".join(
            f"{f.value:g}%" if f.is_percent else f"{f.value:g}"
            for f in sorted(ungrounded, key=lambda x: (x.value, x.is_percent))
        )
        raise PlannerError(
            f"ungrounded numeric value(s) {formatted} in {payload_type} for timeline cue {cue_id}"
        )


def _build_local_context(
    timeline_cues: list[TimelineCue],
    current_index: int,
    visual_group_id: str | None = None,
    all_decisions: list[PlannerDecision] | None = None,
) -> str:
    """Build grounding context limited to current cue + immediately adjacent cues,
    plus any cues that share the same visual_group_id.
    """
    indices_to_include = {current_index}
    if current_index > 0:
        indices_to_include.add(current_index - 1)
    if current_index < len(timeline_cues) - 1:
        indices_to_include.add(current_index + 1)

    if visual_group_id and all_decisions:
        for idx, dec in enumerate(all_decisions):
            if dec.visual_group_id == visual_group_id and idx < len(timeline_cues):
                indices_to_include.add(idx)

    sorted_indices = sorted(indices_to_include)
    parts = [timeline_cues[i].narration for i in sorted_indices if 0 <= i < len(timeline_cues)]
    return " ".join(parts)


def _validate_grounded_data(
    decision: PlannerDecision,
    timeline_cue: TimelineCue,
    local_context: str,
) -> None:
    """Validate DATA visual: all numeric facts in headline AND data must be grounded
    in the local context using canonical fact comparison.
    """
    if decision.visual_type != VisualType.data:
        return
    payload = decision.payload if isinstance(decision.payload, dict) else {}
    allowed_facts = extract_canonical_numeric_facts(local_context)

    # Validate headline numeric facts
    headline = payload.get("headline")
    if headline:
        headline_facts = extract_canonical_numeric_facts(str(headline))
        _validate_numeric_grounding(
            headline_facts, allowed_facts, timeline_cue.id, "DATA headline"
        )

    # Validate all data payload facts recursively
    data_content = payload.get("data") if "data" in payload else payload
    data_facts = extract_canonical_numeric_facts(data_content)
    _validate_numeric_grounding(
        data_facts, allowed_facts, timeline_cue.id, "DATA payload"
    )


def _validate_grounded_text(
    decision: PlannerDecision,
    timeline_cue: TimelineCue,
    local_context: str,
) -> None:
    """Validate TEXT visual: headline/subheadline must not introduce new numeric claims
    absent from the local context.
    """
    if decision.visual_type != VisualType.text:
        return
    payload = TextPayload.model_validate(decision.payload)
    allowed_facts = extract_canonical_numeric_facts(local_context)

    text_facts = extract_canonical_numeric_facts(payload.headline)
    if payload.subheadline is not None:
        text_facts.extend(extract_canonical_numeric_facts(payload.subheadline))
    _validate_numeric_grounding(
        text_facts, allowed_facts, timeline_cue.id, "TEXT payload"
    )


def _build_prompt(
    project: ProjectSpec,
    cues: list[TimelineCue],
    previous: list[VisualCue],
    repair_error: str | None = None,
) -> str:
    context = [
        {
            "id": cue.id,
            "order": cue.order,
            "narration": cue.narration,
        }
        for cue in cues
    ]
    recent = [
        {
            "id": cue.id,
            "visual_type": cue.visual_type.value,
            "purpose": cue.purpose.value,
            "query": cue.payload.get("search_query"),
            "template": cue.payload.get("template"),
            "group": cue.visual_group_id,
        }
        for cue in previous[-3:]
    ]
    search_terms = project.script.search_terms if hasattr(project.script, "search_terms") and project.script.search_terms else []

    prompt = (
        "You are an autonomous Visual Director for an informational video.\n"
        "Your role is to direct the visual narrative: understand what each cue communicates and select the most compelling, accurate treatment.\n"
        "Return strict JSON with a top-level `cues` array containing exactly one decision per requested timeline cue.\n\n"
        "DIRECTING RULES:\n"
        "1. Visual Type Selection:\n"
        "   - BROLL: Use when physical real-world actions, places, objects, or human context enhance the message.\n"
        "   - DATA: Use when numbers, percentages, comparisons, cost breakdowns, thresholds/limits, progress, or timelines are discussed. Provide grounded structured props.\n"
        "   - DOCUMENT: Use when an official source, law, policy, study, or document proof is referenced.\n"
        "   - TEXT: Use only for short emphatic takeaways or section transitions.\n"
        "2. Action-Aware B-roll Search:\n"
        "   - Distinguish NOUN/TOPIC from ACTION/RELATIONSHIP. (e.g. for 'tree branch falls on parked car', do NOT search generic 'car in rain'; search 'fallen tree branch on parked car storm').\n"
        "   - Broll payload MUST include:\n"
        "     * `search_query`: camera-visible literal action query (Tier 1)\n"
        "     * `fallback_queries`: list of semantic fallback queries\n"
        "     * `query_tiers`: {\"tier1\": \"literal event\", \"tier2\": \"outcome/state visual\", \"tier3\": \"close alternative\", \"tier4\": \"broad context\"}\n"
        "     * `semantic_intent`: {\"subject\": \"...\", \"action\": \"...\", \"object\": \"...\", \"setting\": \"...\", \"outcome\": \"...\", \"must_show_concepts\": [...], \"preferred_visuals\": [...], \"acceptable_alternatives\": [...], \"reject_visuals\": [...]}\n"
        "     * `avoid`: list of unwanted visual concepts\n"
        "     * `source_priority`: ['pexels', 'pixabay', 'coverr']\n"
        "3. Structured DATA Cues & Semantic Context:\n"
        "   - Provide grounded structured facts, numeric values, and semantic context. The deterministic visualization director will arbitrate and choose the final chart grammar (e.g. pie/donut, gauge, waterfall, bar, line, threshold, breakdown, comparison).\n"
        "   - Headline for DATA templates MUST be a concise 1-4 word topic label. NOT the full spoken sentence.\n"
        "   - Example: narration='Suppose repairing your car costs six thousand dollars.' → headline='REPAIR COST'\n"
        "   - Supply grounded facts in payload data: `items`, `values`, `threshold_value`, `start_value`, `end_value`, `markers`, etc.\n"
        "   - You may optionally suggest `data_intent`: 'part_to_whole', 'progress', 'positive_negative_change', 'trend_over_time', 'category_comparison', 'threshold', 'breakdown', 'ranked_categories', 'single_metric'.\n"
        "4. Multi-Cue Visual Grouping:\n"
        "   - Set `visual_group_id` (e.g. 'vg_limit_comparison') on adjacent cues that express one evolving motion concept.\n"
        "5. Factual Grounding:\n"
        "   - All numeric values must be grounded strictly in the supplied narration context. Both spoken word numbers ('six thousand dollars') and digits ('$6,000') are valid.\n"
        f"\nProject title: {project.project.title}"
        f"\nProject subject: {project.script.subject}"
        f"\nGlobal search terms: {json.dumps(search_terms, ensure_ascii=False)}"
        f"\nLanguage: {project.project.language}"
        f"\nStyle preset: {project.production.video_style_preset}"
        f"\nRecent decisions: {json.dumps(recent, ensure_ascii=False)}"
        f"\nRequested cues: {json.dumps(context, ensure_ascii=False)}"
    )
    if repair_error:
        prompt += f"\n\nREPAIR INSTRUCTIONS: The previous response failed validation with error:\n{repair_error}\nFix the JSON payload so that it strictly adheres to all schema rules."
    return prompt


def _build_cue_repair_prompt(
    project: ProjectSpec,
    invalid_items: list[dict[str, Any]],
) -> str:
    """Build a targeted repair prompt for specific invalid cues in a batch."""
    prompt = (
        "You are an autonomous Visual Director repairing invalid decisions for specific timeline cues.\n"
        "Return strict JSON with a top-level `cues` array containing corrected decisions for the requested cues ONLY.\n\n"
        "REPAIR REQUIREMENTS:\n"
        "1. Fix the specific validation error reported for each cue.\n"
        "2. Ensure all numbers in DATA/TEXT headlines and payload data are strictly grounded in the cue narration.\n"
        "3. Provide the full valid structured props for the requested template (e.g. comparison items, threshold values, number value).\n"
        f"\nProject title: {project.project.title}"
        f"\nCues to repair: {json.dumps(invalid_items, ensure_ascii=False, indent=2)}"
    )
    return prompt


def _purpose_for(kind: VisualType, narration: str) -> VisualPurpose:
    if kind == VisualType.document:
        return VisualPurpose.evidence
    if kind == VisualType.data:
        return VisualPurpose.compare if _COMPARISON_RE.search(narration) else VisualPurpose.explain
    if kind == VisualType.text:
        return VisualPurpose.emphasis
    return VisualPurpose.context


def classify_narration(narration: str) -> VisualType:
    text = narration.strip()
    if _DOCUMENT_RE.search(text):
        return VisualType.document

    numeric_facts = extract_canonical_numeric_facts(text)
    if numeric_facts:
        return VisualType.data

    if text.isupper() or (
        len(text.split()) <= 3
        and not _COMPARISON_RE.search(text)
    ):
        return VisualType.text

    if _COMPARISON_RE.search(text):
        return VisualType.data

    t_lower = text.lower()
    if any(k in t_lower for k in ("deductible vs", "premium vs", "policy limit vs", "cost breakdown", "versus")):
        return VisualType.data

    return VisualType.broll


def _extract_intent_concepts(text: str) -> tuple[list[str], list[str], str, str, str]:
    """Extract must-show concepts, reject keywords, and core subject/action/object from narration."""
    t_lower = text.lower()
    must_show: list[str] = []
    reject_keywords: list[str] = ["windshield", "wipers", "interior", "bokeh", "blurry"]
    subject = "vehicle"
    action = "event"
    obj = "scene"

    if any(w in t_lower for w in ("car", "vehicle", "auto", "automobile", "truck")):
        must_show.append("car")
        subject = "car"
    if any(w in t_lower for w in ("tree", "branch", "limb", "falling object", "falls")):
        must_show.append("tree branch")
        action = "tree branch falls on"
    if any(w in t_lower for w in ("storm", "rain", "hurricane", "wind")):
        must_show.append("storm")
    if any(w in t_lower for w in ("damage", "damaged", "crush", "crushed", "broken", "dent", "repair", "falls", "branch")):
        must_show.append("damage")
    if any(w in t_lower for w in ("accident", "crash", "collision", "hit", "impact")):
        must_show.append("collision")
        action = "side impact collision"
    if any(w in t_lower for w in ("paperwork", "document", "policy", "review", "bill", "claim")):
        must_show.append("document")
        subject = "driver"
        action = "reviews paperwork"

    if not must_show:
        words = [w for w in re.findall(r"\b[a-zA-Z]{4,}\b", t_lower) if w not in ("your", "this", "that", "with", "from", "have", "what")]
        must_show = words[:3]

    return must_show, reject_keywords, subject, action, obj


def _fallback_payload(
    kind: VisualType,
    narration: str,
    project: ProjectSpec,
    director: DataVisualizationDirector | None = None,
) -> dict[str, Any]:
    text = narration.strip()
    if kind == VisualType.document:
        return DocumentPayload(
            search_query=text[:80],
            source_hint="Official Documentation",
            highlight_target=None,
            evidence_required=True,
        ).model_dump(mode="json")

    if kind == VisualType.text:
        return TextPayload(headline=text[:120]).model_dump(mode="json")

    if kind == VisualType.data:
        active_director = director or DataVisualizationDirector()
        spec = active_director.direct_visual_specification(
            narration=text,
            headline=text[:120],
        )
        template_enum = grammar_to_data_template(spec.grammar)
        return DataPayload(
            template=template_enum,
            headline=spec.props.get("headline") or text[:120],
            data=spec.props,
            layout_archetype=spec.variant,
            data_intent=spec.intent.value,
            visual_grammar=spec.grammar.value,
        ).model_dump(mode="json")

    # VisualType.broll
    must_show, reject_keywords, subj, act, obj = _extract_intent_concepts(text)
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    primary_query = " ".join(words[:MAX_SEARCH_QUERY_WORDS]) if words else project.script.subject

    search_terms = project.script.search_terms if hasattr(project.script, "search_terms") and project.script.search_terms else []
    seed_pool = " ".join(search_terms[:2]) if search_terms else project.script.subject

    tier1 = primary_query
    tier2 = f"{primary_query} aftermath damage" if "damage" in must_show else f"{primary_query} action"
    tier3 = f"{seed_pool} {primary_query}"[:80].strip()
    tier4 = seed_pool

    fallback_queries = [tier2, tier3, tier4]
    semantic_intent = BrollSemanticIntent(
        subject=subj,
        action=act,
        object=obj,
        setting="real world",
        outcome="scene narrative",
        must_show_concepts=must_show,
        preferred_visuals=[primary_query, tier2],
        acceptable_alternatives=[tier3],
        reject_visuals=reject_keywords,
    )

    return BrollPayload(
        search_query=primary_query,
        fallback_queries=fallback_queries,
        avoid=reject_keywords,
        source_priority=["pexels", "pixabay", "coverr"],
        semantic_intent=semantic_intent,
        query_tiers={
            "tier1": tier1,
            "tier2": tier2,
            "tier3": tier3,
            "tier4": tier4,
        },
    ).model_dump(mode="json")


def fallback_visual(
    project: ProjectSpec,
    cue: TimelineCue,
    director: DataVisualizationDirector | None = None,
) -> VisualCue:
    kind = classify_narration(cue.narration)
    return VisualCue(
        id=cue.id,
        order=cue.order,
        visual_type=kind,
        purpose=_purpose_for(kind, cue.narration),
        start=cue.start,
        end=cue.end,
        narration=cue.narration,
        payload=_fallback_payload(kind, cue.narration, project, director=director),
        visual_group_id=None,
    )


def adapt_data_visual_cue(
    decision_or_cue: PlannerDecision | VisualCue,
    cue: TimelineCue,
    local_context: str,
    director: DataVisualizationDirector,
) -> VisualCue:
    """Central adaptation function: arbitrates DATA cues through DataVisualizationDirector."""
    raw_payload = getattr(decision_or_cue, "payload", {}) or {}
    headline = str(raw_payload.get("headline") or "Key Data").strip()

    spec = director.direct_visual_specification(
        narration=cue.narration,
        headline=headline,
        cue_payload=raw_payload,
        source_cue_id=cue.id,
    )

    template_enum = grammar_to_data_template(spec.grammar)
    canonical_payload = DataPayload(
        template=template_enum,
        headline=spec.props.get("headline") or headline,
        data=spec.props,
        layout_archetype=spec.variant,
        data_intent=spec.intent.value,
        visual_grammar=spec.grammar.value,
    ).model_dump(mode="json")

    purpose = getattr(decision_or_cue, "purpose", None)
    if not purpose or not isinstance(purpose, VisualPurpose):
        purpose = _purpose_for(VisualType.data, cue.narration)

    visual_group_id = getattr(decision_or_cue, "visual_group_id", None)

    return VisualCue(
        id=cue.id,
        order=cue.order,
        visual_type=VisualType.data,
        purpose=purpose,
        start=cue.start,
        end=cue.end,
        narration=cue.narration,
        payload=canonical_payload,
        visual_group_id=visual_group_id,
    )


def _canonical_visual(
    decision: PlannerDecision,
    cue: TimelineCue,
    local_context: str,
    director: DataVisualizationDirector | None = None,
) -> VisualCue:
    if decision.id != cue.id or decision.order != cue.order:
        raise PlannerError(
            f"decision id/order mismatch: got ({decision.id}, {decision.order}), expected ({cue.id}, {cue.order})"
        )
    if decision.visual_type == VisualType.data:
        _validate_grounded_data(decision, cue, local_context)
        active_director = director or DataVisualizationDirector()
        return adapt_data_visual_cue(decision, cue, local_context, active_director)

    if decision.visual_type == VisualType.text:
        _validate_grounded_text(decision, cue, local_context)
        return VisualCue(
            id=cue.id,
            order=cue.order,
            visual_type=decision.visual_type,
            purpose=decision.purpose,
            start=cue.start,
            end=cue.end,
            narration=cue.narration,
            payload=decision.payload,
            visual_group_id=decision.visual_group_id,
        )

    return VisualCue(
        id=cue.id,
        order=cue.order,
        visual_type=decision.visual_type,
        purpose=decision.purpose,
        start=cue.start,
        end=cue.end,
        narration=cue.narration,
        payload=decision.payload,
        visual_group_id=decision.visual_group_id,
    )


def _apply_diversity(
    project: ProjectSpec,
    cues: list[TimelineCue],
    decisions: list[VisualCue],
) -> list[VisualCue]:
    from app.services.numeric_parser import extract_canonical_numeric_facts

    # 1. Detect multi-cue breakdown group sequences across consecutive cues (4 cues or 3 cues)
    n = len(decisions)
    i = 0
    while i < n - 1:
        # Check 4-cue window first (e.g. Total, Deductible, You Pay first $1k, Insurance covers remaining $5k)
        if i + 3 < n:
            window = [decisions[i], decisions[i + 1], decisions[i + 2], decisions[i + 3]]
            w_narrs = [(c.narration or "").lower() for c in window]
            if (
                any(w in w_narrs[0] for w in ("repair", "cost", "damage", "total"))
                and any(w in w_narrs[1] for w in ("deductible", "you pay", "out of pocket"))
                and any(w in w_narrs[2] for w in ("responsible", "first", "pay", "deductible"))
                and any(w in w_narrs[3] for w in ("insurance", "insurer", "cover", "remaining"))
            ):
                f_list = [extract_canonical_numeric_facts(c.narration or "") for c in window]
                if all(f_list):
                    v0 = f_list[0][0].value
                    sub_facts = [f[0] for f in f_list[1:]]
                    unique_sub: list[CanonicalNumericFact] = []
                    for f in sub_facts:
                        if f.value > 0 and not any(abs(u.value - f.value) < 0.5 for u in unique_sub):
                            unique_sub.append(f)
                    if v0 > 0 and len(unique_sub) >= 2 and abs(v0 - sum(u.value for u in unique_sub)) <= 1.0:
                        gid = window[0].visual_group_id or "vg_cost_breakdown"
                        total_item = {"label": "TOTAL REPAIR", "value": f_list[0][0].display, "numeric_value": v0}
                        parts_items = [
                            {"label": "DEDUCTIBLE / YOU PAY", "value": unique_sub[0].display, "numeric_value": unique_sub[0].value, "highlight": True},
                            {"label": "INSURANCE", "value": unique_sub[1].display, "numeric_value": unique_sub[1].value, "highlight": False},
                        ]
                        for c_idx, c in enumerate(window):
                            c.visual_group_id = gid
                            c.visual_type = VisualType.data
                            c.purpose = VisualPurpose.explain
                            if c_idx == 0:
                                h_val = "TOTAL REPAIR"
                                d_val = f_list[0][0].display
                                n_val = v0
                            elif c_idx == 1:
                                h_val = "COLLISION DEDUCTIBLE"
                                d_val = unique_sub[0].display
                                n_val = unique_sub[0].value
                            elif c_idx == 2:
                                h_val = "YOUR OUT-OF-POCKET"
                                d_val = unique_sub[0].display
                                n_val = unique_sub[0].value
                            elif c_idx == 3:
                                h_val = "INSURANCE COVERS"
                                d_val = unique_sub[1].display
                                n_val = unique_sub[1].value

                            c.payload = DataPayload(
                                template=DataTemplate.breakdown,
                                headline=h_val,
                                data={
                                    "total": total_item,
                                    "parts": parts_items,
                                    "value": d_val,
                                    "numeric_value": n_val,
                                },
                                layout_archetype="stacked_breakdown",
                                data_intent="breakdown",
                                visual_grammar="breakdown",
                            ).model_dump(mode="json")
                        i += 4
                        continue

        # Check 3-cue window
        if i + 2 < n:
            c0, c1, c2 = decisions[i], decisions[i + 1], decisions[i + 2]
            n0 = (c0.narration or "").lower()
            n1 = (c1.narration or "").lower()
            n2 = (c2.narration or "").lower()
            if (
                any(w in n0 for w in ("repair", "cost", "damage", "total"))
                and any(w in n1 for w in ("deductible", "you pay", "out of pocket"))
                and any(w in n2 for w in ("insurance", "insurer", "cover", "remaining"))
            ):
                f0 = extract_canonical_numeric_facts(c0.narration or "")
                f1 = extract_canonical_numeric_facts(c1.narration or "")
                f2 = extract_canonical_numeric_facts(c2.narration or "")
                if f0 and f1 and f2:
                    v0, v1, v2 = f0[0].value, f1[0].value, f2[0].value
                    if v0 > 0 and v1 > 0 and v2 > 0 and abs(v0 - (v1 + v2)) <= 1.0:
                        gid = c0.visual_group_id or c1.visual_group_id or c2.visual_group_id or "vg_cost_breakdown"
                        total_item = {"label": "TOTAL REPAIR", "value": f0[0].display, "numeric_value": v0}
                        parts_items = [
                            {"label": "DEDUCTIBLE / YOU PAY", "value": f1[0].display, "numeric_value": v1, "highlight": True},
                            {"label": "INSURANCE", "value": f2[0].display, "numeric_value": v2, "highlight": False},
                        ]
                        for c_idx, c in enumerate([c0, c1, c2]):
                            c.visual_group_id = gid
                            c.visual_type = VisualType.data
                            c.purpose = VisualPurpose.explain
                            if c_idx == 0:
                                h_val = "TOTAL REPAIR"
                                d_val = f0[0].display
                                n_val = v0
                            elif c_idx == 1:
                                h_val = "COLLISION DEDUCTIBLE"
                                d_val = f1[0].display
                                n_val = v1
                            elif c_idx == 2:
                                h_val = "INSURANCE COVERS"
                                d_val = f2[0].display
                                n_val = v2

                            c.payload = DataPayload(
                                template=DataTemplate.breakdown,
                                headline=h_val,
                                data={
                                    "total": total_item,
                                    "parts": parts_items,
                                    "value": d_val,
                                    "numeric_value": n_val,
                                },
                                layout_archetype="stacked_breakdown",
                                data_intent="breakdown",
                                visual_grammar="breakdown",
                            ).model_dump(mode="json")
                        i += 3
                        continue
        i += 1

    # 2. Detect multi-cue conceptual comparison sequences generically across any domain
    i = 0
    while i < n - 1:
        if i + 2 < n:
            window = [decisions[i], decisions[i + 1], decisions[i + 2]]
            c0_narr = (window[0].narration or "")
            c1_narr = (window[1].narration or "")
            c2_narr = (window[2].narration or "")

            ents = extract_grounded_comparison_entities(c0_narr)
            if not ents and _COMPARISON_RE.search(c0_narr.lower()):
                ents = extract_grounded_comparison_entities(f"{c0_narr} {c1_narr}")

            if ents:
                ent1, ent2 = ents
                # Extract definitions from adjacent cues
                def_c1_e1 = extract_grounded_entity_definition(ent1, c1_narr)
                def_c1_e2 = extract_grounded_entity_definition(ent2, c1_narr)
                def_c2_e1 = extract_grounded_entity_definition(ent1, c2_narr)
                def_c2_e2 = extract_grounded_entity_definition(ent2, c2_narr)

                e1_defined = def_c1_e1 or def_c2_e1
                e2_defined = def_c1_e2 or def_c2_e2

                if e1_defined or e2_defined or (ent1.lower() in c1_narr.lower() and ent2.lower() in c2_narr.lower()) or (ent2.lower() in c1_narr.lower() and ent1.lower() in c2_narr.lower()):
                    if def_c1_e2 or (ent2.lower() in c1_narr.lower() and ent1.lower() not in c1_narr.lower()):
                        primary_e1 = ent2
                        primary_e2 = ent1
                        val1 = def_c1_e2 or def_c2_e2 or extract_grounded_entity_definition(ent2, c0_narr) or ent2.title()
                        val2 = def_c2_e1 or def_c1_e1 or extract_grounded_entity_definition(ent1, c0_narr) or ent1.title()
                    else:
                        primary_e1 = ent1
                        primary_e2 = ent2
                        val1 = def_c1_e1 or def_c2_e1 or extract_grounded_entity_definition(ent1, c0_narr) or ent1.title()
                        val2 = def_c2_e2 or def_c1_e2 or extract_grounded_entity_definition(ent2, c0_narr) or ent2.title()

                    gid = window[0].visual_group_id or f"vg_{re.sub(r'[^a-zA-Z0-9]', '_', primary_e1.lower())}_vs_{re.sub(r'[^a-zA-Z0-9]', '_', primary_e2.lower())}"

                    for c_idx, c in enumerate(window):
                        c.visual_group_id = gid
                        c.visual_type = VisualType.data
                        c.purpose = VisualPurpose.compare
                        if c_idx == 0:
                            h_val = f"{primary_e1.upper()} VS {primary_e2.upper()}"
                            hl1, hl2 = True, False
                        elif c_idx == 1:
                            h_val = primary_e1.upper()
                            hl1, hl2 = True, False
                        elif c_idx == 2:
                            h_val = primary_e2.upper()
                            hl1, hl2 = False, True

                        items_val = [
                            {"label": primary_e1.upper(), "value": val1, "highlight": hl1},
                            {"label": primary_e2.upper(), "value": val2, "highlight": hl2},
                        ]

                        c.payload = DataPayload(
                            template=DataTemplate.comparison,
                            headline=h_val,
                            data={
                                "items": items_val,
                                "eyebrow": "CONCEPT COMPARISON",
                            },
                            layout_archetype="split_compare",
                            data_intent="category_comparison",
                            visual_grammar="comparison",
                        ).model_dump(mode="json")
                    i += 3
                    continue
        i += 1

    # 3. Detect multi-cue threshold sequences (e.g. limit in cue 0, damage in cue 1)
    i = 0
    while i < n - 1:
        c0, c1 = decisions[i], decisions[i + 1]
        n0 = (c0.narration or "").lower()
        n1 = (c1.narration or "").lower()
        f0 = extract_canonical_numeric_facts(c0.narration or "")
        f1 = extract_canonical_numeric_facts(c1.narration or "")
        if f0 and f1:
            is_c0_limit = any(w in n0 for w in ("coverage", "limit", "cap", "threshold", "maximum", "quota", "budget", "allowance", "ceiling"))
            is_c1_actual = any(w in n1 for w in ("damage", "cause", "claim", "actual", "cost", "loss", "exceed", "reach", "reaches", "traffic", "spending", "usage", "load", "files", "transactions"))
            is_c1_limit = any(w in n1 for w in ("coverage", "limit", "cap", "threshold", "maximum", "quota", "budget", "allowance", "ceiling"))
            is_c0_actual = any(w in n0 for w in ("damage", "cause", "claim", "actual", "cost", "loss", "exceed", "reach", "reaches", "traffic", "spending", "usage", "load", "files", "transactions"))

            if (is_c0_limit and is_c1_actual) or (is_c0_actual and is_c1_limit):
                if is_c0_limit:
                    limit_cue, act_cue = c0, c1
                    limit_fact, act_fact = f0[0], f1[0]
                else:
                    limit_cue, act_cue = c1, c0
                    limit_fact, act_fact = f1[0], f0[0]

                thresh_info = extract_grounded_threshold_labels(limit_cue.narration or "", act_cue.narration or "")
                subj = thresh_info["subject"]
                t_label = thresh_info["threshold_label"]

                gid = c0.visual_group_id or c1.visual_group_id or f"vg_{re.sub(r'[^a-zA-Z0-9]', '_', subj.lower())}_threshold"
                is_exceeded = act_fact.value > limit_fact.value

                for c_idx, c in enumerate([c0, c1]):
                    c.visual_group_id = gid
                    c.visual_type = VisualType.data
                    c.purpose = VisualPurpose.explain
                    if c == limit_cue:
                        h_val = subj
                        eyebrow_val = t_label.upper()
                    else:
                        h_val = f"{subj} EXCEEDED" if is_exceeded else subj
                        eyebrow_val = "LIMIT EXCEEDED" if is_exceeded else "WITHIN LIMIT"

                    c.payload = DataPayload(
                        template=DataTemplate.threshold,
                        headline=h_val,
                        data={
                            "threshold_value": limit_fact.value,
                            "threshold_display": limit_fact.display,
                            "threshold_label": t_label,
                            "current_value": act_fact.value,
                            "current_display": act_fact.display,
                            "eyebrow": eyebrow_val,
                        },
                        layout_archetype="threshold_v2",
                        data_intent="threshold",
                        visual_grammar="threshold",
                    ).model_dump(mode="json")
                i += 2
                continue
        i += 1

    # Canonicalize visual groups (VG001, VG002...) for contiguous groups
    group_counter = 1
    current_raw_group = None
    current_canonical_group = None

    for cue in decisions:
        raw_gid = cue.visual_group_id
        if raw_gid and str(raw_gid).strip():
            raw_gid_clean = str(raw_gid).strip()
            if raw_gid_clean != current_raw_group:
                current_raw_group = raw_gid_clean
                current_canonical_group = f"VG{group_counter:03d}"
                group_counter += 1
            cue.visual_group_id = current_canonical_group
        else:
            current_raw_group = None
            current_canonical_group = None
            cue.visual_group_id = None

    for idx, (cue, decision) in enumerate(zip(cues, decisions)):
        if decision.visual_type == VisualType.broll:
            q = (decision.payload.get("search_query") or "").strip()
            if not q:
                decision.payload["search_query"] = project.script.subject
        elif decision.visual_type == VisualType.text:
            text = (decision.payload.get("headline") or "").strip()
            if not text:
                decision.payload["headline"] = cue.narration[:120]
    return decisions


def normalize_visual_cue_boundaries(
    cues: list[VisualCue],
    *,
    fps: int = 30,
    total_duration_seconds: float | None = None,
    total_duration_frames: int | None = None,
) -> list[VisualCue]:
    if not cues:
        return []

    sorted_cues = sorted(cues, key=lambda cue: cue.order)
    normalized: list[VisualCue] = []
    current_frame = 0
    min_duration_frames = max(1, round(MIN_DURATION_SECONDS * fps))

    for index, cue in enumerate(sorted_cues):
        if index < len(sorted_cues) - 1:
            next_cue = sorted_cues[index + 1]
            raw_next_frame = round(next_cue.start * fps)
            end_frame = max(current_frame + min_duration_frames, raw_next_frame)
        else:
            raw_cue_end_frame = round(cue.end * fps)
            end_frame = max(current_frame + min_duration_frames, raw_cue_end_frame)

        start_sec = current_frame / float(fps)
        end_sec = end_frame / float(fps)

        normalized.append(
            VisualCue(
                id=cue.id,
                order=cue.order,
                visual_type=cue.visual_type,
                purpose=cue.purpose,
                start=start_sec,
                end=end_sec,
                narration=cue.narration,
                payload=cue.payload,
                visual_group_id=cue.visual_group_id,
            )
        )
        current_frame = end_frame

    if total_duration_frames is not None and normalized:
        last = normalized[-1]
        last_start_frame = round(last.start * fps)
        target_end_frame = max(last_start_frame + min_duration_frames, total_duration_frames)
        normalized[-1] = VisualCue(
            id=last.id,
            order=last.order,
            visual_type=last.visual_type,
            purpose=last.purpose,
            start=last.start,
            end=target_end_frame / float(fps),
            narration=last.narration,
            payload=last.payload,
            visual_group_id=last.visual_group_id,
        )
    elif total_duration_seconds is not None and normalized:
        last = normalized[-1]
        target_end = max(last.start + MIN_DURATION_SECONDS, total_duration_seconds)
        normalized[-1] = VisualCue(
            id=last.id,
            order=last.order,
            visual_type=last.visual_type,
            purpose=last.purpose,
            start=last.start,
            end=target_end,
            narration=last.narration,
            payload=last.payload,
            visual_group_id=last.visual_group_id,
        )

    return normalized


def validate_scene_timeline_coverage(
    cues: list[Any],
    expected_duration_frames: int,
    fps: int = 30,
) -> tuple[bool, list[str]]:
    """Validate that visual cues form contiguous, non-overlapping coverage matching expected_duration_frames."""
    if not cues:
        return False, ["No visual cues provided"]

    errors: list[str] = []
    sorted_cues = sorted(cues, key=lambda c: (getattr(c, "order", 0) if getattr(c, "order", 0) is not None else 0))

    first_cue = sorted_cues[0]
    if hasattr(first_cue, "start_frame") and first_cue.start_frame is not None:
        first_start_frame = first_cue.start_frame
    else:
        first_start = getattr(first_cue, "start", 0.0) or 0.0
        first_start_frame = round(first_start * fps)

    if first_start_frame != 0:
        errors.append(f"First scene does not start at frame 0 (starts at frame {first_start_frame})")

    prev_end_frame = first_start_frame
    for idx, cue in enumerate(sorted_cues):
        if hasattr(cue, "start_frame") and cue.start_frame is not None:
            curr_start_frame = cue.start_frame
            curr_end_frame = (
                cue.end_frame
                if cue.end_frame is not None
                else (curr_start_frame + getattr(cue, "duration_frames", 1))
            )
        else:
            c_start = getattr(cue, "start", None)
            c_end = getattr(cue, "end", None)
            if c_start is not None:
                curr_start_frame = round(c_start * fps)
            else:
                curr_start_frame = prev_end_frame

            if c_end is not None:
                curr_end_frame = round(c_end * fps)
            else:
                dur_f = getattr(cue, "duration_frames", None)
                if dur_f is not None:
                    curr_end_frame = curr_start_frame + dur_f
                else:
                    curr_end_frame = curr_start_frame + round(1.0 * fps)

        cue_id = getattr(cue, "scene_id", getattr(cue, "id", f"scene_{idx+1}"))
        prev_id = getattr(sorted_cues[idx - 1], "scene_id", getattr(sorted_cues[idx - 1], "id", f"scene_{idx}"))

        if idx > 0 and curr_start_frame != prev_end_frame:
            errors.append(
                f"Gap or overlap between scene {prev_id} (end frame {prev_end_frame}) and scene {cue_id} (start frame {curr_start_frame})"
            )

        if curr_end_frame <= curr_start_frame:
            errors.append(f"Scene {cue_id} has non-positive frame duration ({curr_start_frame}..{curr_end_frame})")

        prev_end_frame = curr_end_frame

    last_end_frame = prev_end_frame
    total_scene_frames = sum(
        (
            cue.duration_frames
            if hasattr(cue, "duration_frames") and cue.duration_frames is not None
            else (
                round((cue.end - cue.start) * fps)
                if getattr(cue, "start", None) is not None and getattr(cue, "end", None) is not None
                else 0
            )
        )
        for cue in sorted_cues
    )
    if total_scene_frames != expected_duration_frames:
        uncovered = expected_duration_frames - total_scene_frames
        errors.append(
            f"Timeline coverage mismatch: {total_scene_frames} scene frames vs {expected_duration_frames} expected ({uncovered} uncovered frames)"
        )
    elif last_end_frame != expected_duration_frames:
        uncovered = expected_duration_frames - last_end_frame
        errors.append(
            f"Timeline coverage mismatch: {last_end_frame} scene frames vs {expected_duration_frames} expected ({uncovered} uncovered frames)"
        )

    return len(errors) == 0, errors


def plan_visuals(
    project: ProjectSpec,
    timeline_cues: list[TimelineCue],
    *,
    response_fn: Callable[[str], str] | None = None,
    batch_size: int = BATCH_SIZE,
    total_duration_seconds: float | None = None,
    total_duration_frames: int | None = None,
    director: DataVisualizationDirector | None = None,
) -> list[VisualCue]:
    """Autonomous Visual Director planner with independent per-cue validation and targeted repair."""
    active_director = director or DataVisualizationDirector()
    response_fn = response_fn or llm.generate_response
    planned: list[VisualCue] = []
    timeline_index_by_id = {cue.id: idx for idx, cue in enumerate(timeline_cues)}

    for start in range(0, len(timeline_cues), batch_size):
        batch = timeline_cues[start : start + batch_size]
        previous = planned[-3:]

        valid_decisions: dict[str, VisualCue] = {}
        invalid_cues: dict[str, tuple[TimelineCue, PlannerDecision | None, str]] = {}

        # 1. Initial Batch Call
        raw_response: PlannerBatch | None = None
        batch_parse_error = None
        for _batch_attempt in range(2):
            try:
                raw_text = response_fn(_build_prompt(project, batch, previous, batch_parse_error))
                raw_response = _parse_batch_response(raw_text)
                break
            except Exception as exc:
                batch_parse_error = str(exc)

        # 2. Per-Cue Independent Validation
        if raw_response and raw_response.cues:
            decision_by_id = {d.id: d for d in raw_response.cues}
            for cue in batch:
                dec = decision_by_id.get(cue.id)
                if not dec:
                    invalid_cues[cue.id] = (cue, None, "Missing decision in planner response")
                    continue
                try:
                    local_ctx = _build_local_context(
                        timeline_cues,
                        timeline_index_by_id[cue.id],
                        visual_group_id=dec.visual_group_id,
                        all_decisions=raw_response.cues,
                    )
                    vis = _canonical_visual(dec, cue, local_ctx, director=active_director)
                    valid_decisions[cue.id] = vis
                except (ValueError, TypeError, ValidationError, PlannerError) as exc:
                    invalid_cues[cue.id] = (cue, dec, str(exc))
        else:
            for cue in batch:
                invalid_cues[cue.id] = (cue, None, batch_parse_error or "Batch JSON parse failure")

        # 3. Targeted Per-Cue Repair Loop (only for invalid cues)
        for _repair_attempt in range(REPAIR_ATTEMPTS):
            if not invalid_cues:
                break

            repair_items = [
                {
                    "id": cue.id,
                    "order": cue.order,
                    "narration": cue.narration,
                    "previous_invalid_payload": dec.payload if dec else None,
                    "error": err,
                }
                for cue, dec, err in invalid_cues.values()
            ]

            try:
                repair_text = response_fn(_build_cue_repair_prompt(project, repair_items))
                repaired_batch = _parse_batch_response(repair_text)
                repaired_decision_by_id = {d.id: d for d in repaired_batch.cues}

                still_invalid: dict[str, tuple[TimelineCue, PlannerDecision | None, str]] = {}
                for cid, (cue, prev_dec, _) in list(invalid_cues.items()):
                    rep_dec = repaired_decision_by_id.get(cid)
                    if not rep_dec:
                        still_invalid[cid] = (cue, prev_dec, "Missing decision in repair response")
                        continue
                    try:
                        local_ctx = _build_local_context(
                            timeline_cues,
                            timeline_index_by_id[cid],
                            visual_group_id=rep_dec.visual_group_id,
                            all_decisions=repaired_batch.cues,
                        )
                        vis = _canonical_visual(rep_dec, cue, local_ctx, director=active_director)
                        valid_decisions[cid] = vis
                    except (ValueError, TypeError, ValidationError, PlannerError) as exc:
                        still_invalid[cid] = (cue, rep_dec, str(exc))

                invalid_cues = still_invalid
            except Exception as repair_exc:
                logger.warning(f"Repair attempt failed: {repair_exc}")
                break

        # 4. Fallback ONLY for remaining invalid cues
        batch_decisions: list[VisualCue] = []
        for cue in batch:
            if cue.id in valid_decisions:
                batch_decisions.append(valid_decisions[cue.id])
            else:
                fb = fallback_visual(project, cue, director=active_director)
                batch_decisions.append(fb)

        planned.extend(batch_decisions)

    # 5. Post-Plan Semantic Opportunity Audit
    for idx, cue in enumerate(planned):
        if cue.visual_type == VisualType.broll:
            t_cue = timeline_cues[timeline_index_by_id[cue.id]]
            facts = extract_canonical_numeric_facts(t_cue.narration)
            t_lower = t_cue.narration.lower()
            if len(facts) >= 2 or (len(facts) >= 1 and any(w in t_lower for w in ("cost", "deductible", "limit", "coverage", "repair", "percent", "dollar"))):
                fb_data = fallback_visual(project, t_cue, director=active_director)
                if fb_data.visual_type == VisualType.data:
                    logger.info(f"Post-plan semantic audit upgraded cue {cue.id} from generic BROLL to structured DATA ({fb_data.payload.get('template')})")
                    planned[idx] = fb_data

    diverse = _apply_diversity(project, timeline_cues, planned)
    fps = project.project.fps or 30
    return normalize_visual_cue_boundaries(
        diverse,
        fps=fps,
        total_duration_seconds=total_duration_seconds,
        total_duration_frames=total_duration_frames,
    )


def save_visual_plan(
    project_title: str, cues: list[VisualCue], destination: str | Path
) -> Path:
    plan = VisualPlan(schema_version="1.0", project_title=project_title, cues=cues)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
