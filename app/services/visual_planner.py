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
    r"\b(versus|vs|compare|compared|more than|less than|higher than|lower than|increase|decrease|growth|decline|cost breakdown|premium vs|deductible vs|limit vs)\b",
    re.IGNORECASE,
)


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
    in the local context using canonical fact comparison, and structured props must satisfy the template contract.
    """
    if decision.visual_type != VisualType.data:
        return
    payload = DataPayload.model_validate(decision.payload)
    allowed_facts = extract_canonical_numeric_facts(local_context)

    # Validate headline numeric facts
    headline_facts = extract_canonical_numeric_facts(payload.headline)
    _validate_numeric_grounding(
        headline_facts, allowed_facts, timeline_cue.id, "DATA headline"
    )

    # Validate all data payload facts recursively
    data_facts = extract_canonical_numeric_facts(payload.data)
    _validate_numeric_grounding(
        data_facts, allowed_facts, timeline_cue.id, "DATA payload"
    )

    # Template-specific structured data validation
    if payload.template in {DataTemplate.bar_chart, DataTemplate.line_chart}:
        items = payload.data.get("items") or payload.data.get("points") or payload.data.get("values")
        if not isinstance(items, list) or len(items) < 2:
            raise PlannerError(
                f"{payload.template.value} template requires at least two items/points in data"
            )

    elif payload.template == DataTemplate.comparison:
        items = payload.data.get("items") or payload.data.get("options") or payload.data.get("values")
        if not isinstance(items, list) or len(items) < 2:
            raise PlannerError(
                "comparison template requires an 'items' list with at least two comparison entries"
            )

    elif payload.template == DataTemplate.timeline:
        milestones = payload.data.get("milestones") or payload.data.get("events")
        if not isinstance(milestones, list) or len(milestones) < 2:
            raise PlannerError(
                "timeline template requires a 'milestones' list with at least two milestone entries"
            )

    elif payload.template == DataTemplate.threshold:
        curr = payload.data.get("current_value") if payload.data.get("current_value") is not None else payload.data.get("value")
        thresh = payload.data.get("threshold_value") if payload.data.get("threshold_value") is not None else payload.data.get("threshold") or payload.data.get("limit")
        if curr is None or thresh is None:
            raise PlannerError(
                "threshold template requires numeric current_value and threshold_value in data"
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
        "   - DATA: Use when numbers, comparisons, cost breakdowns, thresholds/limits, or timelines are discussed. Provide structured props.\n"
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
        "3. Structured DATA Templates:\n"
        "   - Never output unstructured numbers or empty callouts when structured data is grounded.\n"
        "   - `number`: headline, data: {\"value\": \"$6,000\", \"numeric_value\": 6000, \"label\": \"...\", \"prefix\": \"$\"}\n"
        "   - `counter`: headline, data: {\"start_value\": 0, \"end_value\": 5000, \"label\": \"...\"}\n"
        "   - `comparison`: headline, data: {\"items\": [{\"label\": \"...\", \"value\": \"...\", \"numeric_value\": ...}, {\"label\": \"...\", \"value\": \"...\", \"highlight\": true}]}\n"
        "   - `timeline`: headline, data: {\"milestones\": [{\"time_label\": \"Step 1\", \"title\": \"...\"}, {\"time_label\": \"Step 2\", \"title\": \"...\"}]}\n"
        "   - `bar_chart`: headline, data: {\"items\": [{\"label\": \"...\", \"value\": 1000, \"display_value\": \"$1,000\"}, {\"label\": \"...\", \"value\": 5000, \"display_value\": \"$5,000\"}]}\n"
        "   - `line_chart`: headline, data: {\"points\": [{\"x_label\": \"...\", \"y_value\": ...}, {\"x_label\": \"...\", \"y_value\": ...}]}\n"
        "   - `threshold`: headline, data: {\"current_value\": 40000, \"current_display\": \"$40K\", \"threshold_value\": 25000, \"threshold_display\": \"$25K\", \"threshold_label\": \"Coverage Limit\", \"subtext\": \"Above Policy Limit\"}\n"
        "   - `age_marker`: headline, data: {\"markers\": [{\"age\": 67, \"label\": \"Full Retirement\", \"highlight\": true}]}\n"
        "   - `callout`: headline, data: {\"emphasis\": \"...\", \"subtext\": \"...\"} (use ONLY when no richer structured template applies)\n"
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


def _fallback_payload(kind: VisualType, narration: str, project: ProjectSpec) -> dict[str, Any]:
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
        facts = extract_canonical_numeric_facts(text)
        t_lower = text.lower()

        # 1. Threshold / Limit Detection (e.g. $25K limit vs $40K damage)
        if (
            re.search(r"\b(?:limit|threshold|exceed|exceeds|exceeded|exceeding|above limit|policy limit|coverage limit|cap|capped)\b", t_lower)
            and len(facts) >= 2
        ):
            n1 = facts[0]
            n2 = facts[1]
            thresh_val = min(n1.value, n2.value)
            curr_val = max(n1.value, n2.value)
            thresh_disp = n1.display if n1.value <= n2.value else n2.display
            curr_disp = n2.display if n1.value <= n2.value else n1.display
            return DataPayload(
                template=DataTemplate.threshold,
                headline=text[:120],
                data={
                    "current_value": curr_val,
                    "current_display": curr_disp,
                    "threshold_value": thresh_val,
                    "threshold_display": thresh_disp,
                    "threshold_label": "Coverage Limit",
                    "subtext": "Above Policy Limit",
                },
            ).model_dump(mode="json")

        # 2. Comparison / Cost Breakdown (e.g. $1,000 deductible vs $5,000 insurance)
        if len(facts) >= 2 or _COMPARISON_RE.search(text):
            items = []
            for i, fact in enumerate(facts[:4]):
                tok = fact.display
                label = f"Item {i + 1}"
                if "deductible" in t_lower and ("1000" in tok or (len(facts) == 3 and i == 1)):
                    label = "Deductible"
                elif ("insurance" in t_lower or "insurer" in t_lower or "cover" in t_lower) and ("5000" in tok or (len(facts) == 3 and i == 2)):
                    label = "Insurance Portion"
                elif ("repair" in t_lower or "cost" in t_lower) and ("6000" in tok or (len(facts) == 3 and i == 0)):
                    label = "Repair Cost"
                elif "deductible" in t_lower and i == 0:
                    label = "Deductible"
                elif "insurance" in t_lower or "insurer" in t_lower:
                    label = "Insurance Portion" if i == 1 else f"Item {i + 1}"
                elif "repair" in t_lower or "cost" in t_lower:
                    label = "Repair Cost" if i == 0 else f"Item {i + 1}"
                elif "limit" in t_lower:
                    label = "Coverage Limit" if i == 0 else "Damage Amount"

                items.append(
                    {
                        "label": label,
                        "value": tok,
                        "numeric_value": fact.value,
                        "highlight": (i == 1 or i == 2),
                    }
                )
            if len(items) >= 2:
                return DataPayload(
                    template=DataTemplate.comparison,
                    headline=text[:120],
                    data={"items": items},
                ).model_dump(mode="json")

        # 3. Single Number
        if len(facts) >= 1:
            fact = facts[0]
            label = "Key Metric"
            if "repair" in t_lower or "cost" in t_lower:
                label = "Repair Cost"
            elif "deductible" in t_lower:
                label = "Deductible"
            elif "limit" in t_lower or "coverage" in t_lower:
                label = "Coverage Limit"
            elif "insurance" in t_lower or "cover" in t_lower:
                label = "Insurance Coverage"

            return DataPayload(
                template=DataTemplate.number,
                headline=text[:120],
                data={
                    "value": fact.display,
                    "numeric_value": fact.value,
                    "label": label,
                    "prefix": "$" if fact.is_currency and not fact.display.startswith("$") else "",
                    "suffix": "%" if fact.is_percent and not fact.display.endswith("%") else "",
                },
            ).model_dump(mode="json")

        # 4. Conceptual comparison without numbers (e.g. Premium vs Deductible)
        if "premium" in t_lower and "deductible" in t_lower:
            return DataPayload(
                template=DataTemplate.comparison,
                headline="Insurance Premium vs. Deductible",
                data={
                    "items": [
                        {"label": "Premium", "value": "Recurring Cost to Maintain Policy", "highlight": False},
                        {"label": "Deductible", "value": "Out-of-Pocket Cost When Claiming", "highlight": True},
                    ]
                },
            ).model_dump(mode="json")

        return DataPayload(
            template=DataTemplate.callout,
            headline=text[:120],
            data={"text": text[:180], "style": "card"},
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


def fallback_visual(project: ProjectSpec, cue: TimelineCue) -> VisualCue:
    kind = classify_narration(cue.narration)
    return VisualCue(
        id=cue.id,
        order=cue.order,
        visual_type=kind,
        purpose=_purpose_for(kind, cue.narration),
        start=cue.start,
        end=cue.end,
        narration=cue.narration,
        payload=_fallback_payload(kind, cue.narration, project),
        visual_group_id=None,
    )


def _canonical_visual(
    decision: PlannerDecision,
    cue: TimelineCue,
    local_context: str,
) -> VisualCue:
    if decision.id != cue.id or decision.order != cue.order:
        raise PlannerError(
            f"decision id/order mismatch: got ({decision.id}, {decision.order}), expected ({cue.id}, {cue.order})"
        )
    _validate_grounded_data(decision, cue, local_context)
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


def _apply_diversity(
    project: ProjectSpec,
    cues: list[TimelineCue],
    decisions: list[VisualCue],
) -> list[VisualCue]:
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
) -> list[VisualCue]:
    """Autonomous Visual Director planner with independent per-cue validation and targeted repair."""
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
                    vis = _canonical_visual(dec, cue, local_ctx)
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
                        vis = _canonical_visual(rep_dec, cue, local_ctx)
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
                fb = fallback_visual(project, cue)
                batch_decisions.append(fb)

        planned.extend(batch_decisions)

    # 5. Post-Plan Semantic Opportunity Audit
    for idx, cue in enumerate(planned):
        if cue.visual_type == VisualType.broll:
            t_cue = timeline_cues[timeline_index_by_id[cue.id]]
            facts = extract_canonical_numeric_facts(t_cue.narration)
            t_lower = t_cue.narration.lower()
            if len(facts) >= 2 or (len(facts) >= 1 and any(w in t_lower for w in ("cost", "deductible", "limit", "coverage", "repair", "percent", "dollar"))):
                fb_data = fallback_visual(project, t_cue)
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
