from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from pydantic import BaseModel, ConfigDict, ValidationError

from app.models.project import (
    BrollPayload,
    DataPayload,
    DataTemplate,
    DocumentPayload,
    ProjectSpec,
    TimelineCue,
    TextPayload,
    VisualCue,
    VisualPlan,
    VisualPurpose,
    VisualType,
)
from app.services import llm

BATCH_SIZE = 10
REPAIR_ATTEMPTS = 2
_NUMBER_RE = re.compile(r"(?<!\w)(?:\$\s*)?\d[\d,.]*(?:\s*[KMB])?\s*%?", re.IGNORECASE)
_DOCUMENT_RE = re.compile(
    r"\b(?:irs|ssa|form|report|research|study|official|law|regulation|rule|source|medicare official)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"\b(?:vs\.?|versus|more|less|higher|lower|difference|gap|from|until|between|threshold)\b",
    re.IGNORECASE,
)


class PlannerError(ValueError):
    """A planner response cannot be made into a valid visual plan."""


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


def _numeric_tokens(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [token for item in value.values() for token in _numeric_tokens(item)]
    if isinstance(value, (list, tuple)):
        return [token for item in value for token in _numeric_tokens(item)]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, str):
        return _NUMBER_RE.findall(value)
    return []


def _validate_grounded_data(
    decision: PlannerDecision,
    timeline_cue: TimelineCue,
    context: str,
) -> None:
    if decision.visual_type != VisualType.data:
        return
    payload = DataPayload.model_validate(decision.payload)
    normalized_context = re.sub(r"\s+", "", context).lower()
    for token in _numeric_tokens(payload.data):
        if re.sub(r"\s+", "", token).lower() not in normalized_context:
            raise PlannerError(
                f"ungrounded numeric value {token!r} for timeline cue {timeline_cue.id}"
            )
    if payload.template in {DataTemplate.bar_chart, DataTemplate.line_chart}:
        values = payload.data.get("values")
        if not isinstance(values, list) or len(values) < 2:
            raise PlannerError("chart templates require at least two grounded values")


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
        }
        for cue in previous[-3:]
    ]
    prompt = f"""You are an autonomous visual planning service.
Return only strict JSON with a top-level `cues` array and exactly one decision for every requested timeline cue.
Choose only broll, data, document, or text. Do not return timestamps, narration, URLs, citations, files, or invented facts.
Broll payload requires search_query, fallback_queries, avoid, and source_priority using only pexels, pixabay, coverr.
Data payload requires template, headline, and only numeric values grounded in the supplied narration context.
Document payload requires search_query, source_hint, highlight_target, and evidence_required.
Text payload requires a short headline and optional subheadline.
Use visual_group_id only for adjacent cues that represent one evolving visual concept.

Project title: {project.project.title}
Project subject: {project.script.subject}
Language: {project.project.language}
Style preset: {project.production.video_style_preset}
Recent decisions: {json.dumps(recent, ensure_ascii=False)}
Requested cues: {json.dumps(context, ensure_ascii=False)}
""".strip()
    if repair_error:
        prompt += f"\nRepair the previous response using these validation errors:\n{repair_error}"
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
    if text.isupper() or (
        len(text.split()) <= 3
        and not _NUMBER_RE.search(text)
        and not _COMPARISON_RE.search(text)
    ):
        return VisualType.text
    if _NUMBER_RE.search(text) or _COMPARISON_RE.search(text):
        return VisualType.data
    return VisualType.broll


def _fallback_payload(kind: VisualType, project: ProjectSpec, cue: TimelineCue) -> dict[str, Any]:
    text = cue.narration.strip()
    if kind == VisualType.document:
        return DocumentPayload(
            search_query=text,
            source_hint="official evidence source",
            highlight_target=None,
            evidence_required=True,
        ).model_dump(mode="json")
    if kind == VisualType.text:
        return TextPayload(headline=text[:120]).model_dump(mode="json")
    if kind == VisualType.data:
        tokens = _NUMBER_RE.findall(text)
        template = DataTemplate.comparison if _COMPARISON_RE.search(text) else DataTemplate.number
        if re.search(r"\bage\b", text, re.IGNORECASE):
            template = DataTemplate.age_marker
        elif re.search(r"\b(?:from|until|between|gap)\b", text, re.IGNORECASE):
            template = DataTemplate.timeline
        return DataPayload(
            template=template,
            headline=text[:120],
            data={"values": tokens} if tokens else {},
        ).model_dump(mode="json")
    words = re.findall(r"[A-Za-z0-9]+", f"{project.script.subject} {text}")
    words = [word for word in words if word.lower() not in {"local", "douyin", "bilibili", "xiaohongshu"}]
    base = " ".join(words)
    query = " ".join(base.split()[:14]) or "real world context"
    return BrollPayload(
        search_query=query,
        fallback_queries=[f"{query} daily life", f"{query} close up"],
        avoid=["animation", "text overlay", "vertical social video"],
    ).model_dump(mode="json")


def fallback_visual(project: ProjectSpec, cue: TimelineCue) -> VisualCue:
    kind = classify_narration(cue.narration)
    return VisualCue(
        id=cue.id,
        order=cue.order,
        start=cue.start,
        end=cue.end,
        narration=cue.narration,
        visual_type=kind,
        purpose=_purpose_for(kind, cue.narration),
        payload=_fallback_payload(kind, project, cue),
    )


def _canonical_visual(
    decision: PlannerDecision,
    timeline_cue: TimelineCue,
    context: str,
) -> VisualCue:
    _validate_grounded_data(decision, timeline_cue, context)
    return VisualCue(
        id=timeline_cue.id,
        order=timeline_cue.order,
        start=timeline_cue.start,
        end=timeline_cue.end,
        narration=timeline_cue.narration,
        visual_type=decision.visual_type,
        purpose=decision.purpose,
        payload=decision.payload,
        visual_group_id=decision.visual_group_id,
    )


def _normalize_groups(cues: list[VisualCue]) -> list[VisualCue]:
    result: list[VisualCue] = []
    group_number = 0
    index = 0
    while index < len(cues):
        current = cues[index]
        raw_group = current.visual_group_id
        end = index + 1
        while end < len(cues) and raw_group and cues[end].visual_group_id == raw_group and cues[end].visual_type == current.visual_type:
            end += 1
        if end - index > 1:
            group_number += 1
            group_id = f"VG{group_number:03d}"
            result.extend(cue.model_copy(update={"visual_group_id": group_id}) for cue in cues[index:end])
        else:
            result.append(current.model_copy(update={"visual_group_id": None}))
        index = end
    return result


def _apply_diversity(project: ProjectSpec, timeline: list[TimelineCue], planned: list[VisualCue]) -> list[VisualCue]:
    result: list[VisualCue] = []
    recent_queries: set[str] = set()
    broll_streak = 0
    for timeline_cue, visual in zip(timeline, planned):
        replacement = visual
        if visual.visual_type == VisualType.broll:
            broll_streak += 1
            query = str(visual.payload.get("search_query", "")).lower()
            if query in recent_queries:
                replacement = fallback_visual(project, timeline_cue)
            elif broll_streak > 2 and classify_narration(timeline_cue.narration) in {VisualType.data, VisualType.document}:
                replacement = fallback_visual(project, timeline_cue)
            recent_queries.add(query)
        else:
            broll_streak = 0
        result.append(replacement)
    for index in range(len(result) - 1):
        current = result[index]
        following = result[index + 1]
        if (
            (current.visual_group_id is None or current.visual_group_id == "auto-data")
            and (following.visual_group_id is None or following.visual_group_id == "auto-data")
            and current.visual_type == VisualType.data
            and following.visual_type == VisualType.data
            and (_COMPARISON_RE.search(current.narration) or _COMPARISON_RE.search(following.narration))
        ):
            result[index] = current.model_copy(update={"visual_group_id": "auto-data"})
            result[index + 1] = following.model_copy(update={"visual_group_id": "auto-data"})
    return _normalize_groups(result)


def plan_visuals(
    project: ProjectSpec,
    timeline_cues: list[TimelineCue],
    *,
    response_fn: Callable[[str], str] | None = None,
    batch_size: int = BATCH_SIZE,
) -> list[VisualCue]:
    response_fn = response_fn or llm.generate_response
    planned: list[VisualCue] = []
    for start in range(0, len(timeline_cues), batch_size):
        batch = timeline_cues[start : start + batch_size]
        previous = planned[-3:]
        decisions: list[PlannerDecision] | None = None
        error = None
        for attempt in range(REPAIR_ATTEMPTS + 1):
            try:
                parsed = _parse_batch_response(
                    response_fn(_build_prompt(project, batch, previous, error))
                )
                expected = {(cue.id, cue.order) for cue in batch}
                actual = {(cue.id, cue.order) for cue in parsed.cues}
                if actual != expected or len(parsed.cues) != len(batch):
                    raise PlannerError("planner must return exactly one decision per requested cue")
                context = " ".join(
                    cue.narration for cue in timeline_cues[max(0, start - 1) : min(len(timeline_cues), start + len(batch) + 1)]
                ) + " " + project.script.script
                decisions = [
                    _canonical_visual(
                        decision,
                        next(cue for cue in batch if cue.id == decision.id),
                        context,
                    )
                    for decision in parsed.cues
                ]
                break
            except (ValueError, TypeError, ValidationError, PlannerError) as exc:
                error = str(exc)
        if decisions is None:
            decisions = [fallback_visual(project, cue) for cue in batch]
        planned.extend(decisions)
    return _apply_diversity(project, timeline_cues, planned)


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
