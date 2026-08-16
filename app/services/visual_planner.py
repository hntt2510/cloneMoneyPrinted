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


from dataclasses import dataclass


@dataclass(frozen=True)
class NumericFact:
    value: float
    is_percent: bool = False


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


def _parse_single_numeric_fact(raw: str) -> NumericFact | None:
    """Parse a single numeric token into a canonical NumericFact."""
    text = raw.strip()
    if not text:
        return None
    is_percent = "%" in text
    clean = re.sub(r"[\$\%,]", "", text).strip()
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
        return NumericFact(value=val, is_percent=is_percent)
    except ValueError:
        return None


def _extract_numeric_facts(value: Any) -> set[NumericFact]:
    """Recursively extract all canonical NumericFact items from any value."""
    facts: set[NumericFact] = set()
    if isinstance(value, bool):
        return facts
    if isinstance(value, (int, float)):
        facts.add(NumericFact(value=float(value), is_percent=False))
    elif isinstance(value, str):
        for match in _NUMBER_RE.finditer(value):
            fact = _parse_single_numeric_fact(match.group(0))
            if fact is not None:
                facts.add(fact)
    elif isinstance(value, dict):
        for item in value.values():
            facts.update(_extract_numeric_facts(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            facts.update(_extract_numeric_facts(item))
    return facts


def _validate_numeric_grounding(
    facts_to_check: set[NumericFact],
    allowed_facts: set[NumericFact],
    cue_id: str,
    payload_type: str,
) -> None:
    """Validate that all numeric facts in facts_to_check are present in allowed_facts."""
    ungrounded = facts_to_check - allowed_facts
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
) -> str:
    """Build grounding context limited to current cue + immediately adjacent cues.

    Allowed grounding context:
    - current cue narration
    - immediately previous cue narration (if present)
    - immediately next cue narration (if present)

    The full project script is NOT included to prevent numeric values from
    distant scenes from being used as grounding for the current cue.
    """
    parts: list[str] = []
    if current_index > 0:
        parts.append(timeline_cues[current_index - 1].narration)
    parts.append(timeline_cues[current_index].narration)
    if current_index < len(timeline_cues) - 1:
        parts.append(timeline_cues[current_index + 1].narration)
    return " ".join(parts)


def _validate_grounded_data(
    decision: PlannerDecision,
    timeline_cue: TimelineCue,
    local_context: str,
) -> None:
    """Validate DATA visual: all numeric tokens in headline AND data must be grounded
    in the local context (current + adjacent cues only) using exact canonical fact comparison.

    Rejects any numeric value absent from the local grounding window.
    """
    if decision.visual_type != VisualType.data:
        return
    payload = DataPayload.model_validate(decision.payload)
    allowed_facts = _extract_numeric_facts(local_context)

    # Validate headline numeric facts
    headline_facts = _extract_numeric_facts(payload.headline)
    _validate_numeric_grounding(
        headline_facts, allowed_facts, timeline_cue.id, "DATA headline"
    )

    # Validate all data payload facts recursively
    data_facts = _extract_numeric_facts(payload.data)
    _validate_numeric_grounding(
        data_facts, allowed_facts, timeline_cue.id, "DATA payload"
    )

    if payload.template in {DataTemplate.bar_chart, DataTemplate.line_chart}:
        values = payload.data.get("values")
        if not isinstance(values, list) or len(values) < 2:
            raise PlannerError("chart templates require at least two grounded values")


def _validate_grounded_text(
    decision: PlannerDecision,
    timeline_cue: TimelineCue,
    local_context: str,
) -> None:
    """Validate TEXT visual: headline/subheadline must not introduce new numeric claims
    absent from the local context (current + adjacent cues only) using exact canonical fact comparison.
    """
    if decision.visual_type != VisualType.text:
        return
    payload = TextPayload.model_validate(decision.payload)
    allowed_facts = _extract_numeric_facts(local_context)

    text_facts = _extract_numeric_facts(payload.headline)
    if payload.subheadline is not None:
        text_facts.update(_extract_numeric_facts(payload.subheadline))
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
        }
        for cue in previous[-3:]
    ]
    prompt = (
        "You are an autonomous visual planning service.\n"
        "Return only strict JSON with a top-level `cues` array and exactly one decision for every requested timeline cue.\n"
        "Choose only broll, data, document, or text. Do not return timestamps, narration, URLs, citations, files, or invented facts.\n"
        "Broll payload requires search_query, fallback_queries, avoid, and source_priority using only pexels, pixabay, coverr.\n"
        "Data payload requires template, headline, and only numeric values grounded in the supplied narration context.\n"
        "Document payload requires search_query, source_hint, highlight_target, and evidence_required.\n"
        "Text payload requires a short headline and optional subheadline.\n"
        "Use visual_group_id only for adjacent cues that represent one evolving visual concept.\n"
        f"\nProject title: {project.project.title}"
        f"\nProject subject: {project.script.subject}"
        f"\nLanguage: {project.project.language}"
        f"\nStyle preset: {project.production.video_style_preset}"
        f"\nRecent decisions: {json.dumps(recent, ensure_ascii=False)}"
        f"\nRequested cues: {json.dumps(context, ensure_ascii=False)}"
    )
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
        # Fallback text payload uses narration text directly - always grounded
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
    base = " ".join(re.findall(r"[A-Za-z0-9]+", f"{project.script.subject} {text}"))
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
    local_context: str,
) -> VisualCue:
    """Validate and canonicalize a planner decision against local grounding context.

    local_context must be limited to current + adjacent cues (NOT the full script).
    """
    _validate_grounded_data(decision, timeline_cue, local_context)
    _validate_grounded_text(decision, timeline_cue, local_context)
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
        while (
            end < len(cues)
            and raw_group
            and cues[end].visual_group_id == raw_group
            and cues[end].visual_type == current.visual_type
        ):
            end += 1
        if end - index > 1:
            group_number += 1
            group_id = f"VG{group_number:03d}"
            result.extend(
                cue.model_copy(update={"visual_group_id": group_id}) for cue in cues[index:end]
            )
        else:
            result.append(current.model_copy(update={"visual_group_id": None}))
        index = end
    return result


def _apply_diversity(
    project: ProjectSpec,
    timeline: list[TimelineCue],
    planned: list[VisualCue],
) -> list[VisualCue]:
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
            elif broll_streak > 2 and classify_narration(timeline_cue.narration) in {
                VisualType.data,
                VisualType.document,
            }:
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
            and (
                _COMPARISON_RE.search(current.narration)
                or _COMPARISON_RE.search(following.narration)
            )
        ):
            result[index] = current.model_copy(update={"visual_group_id": "auto-data"})
            result[index + 1] = following.model_copy(update={"visual_group_id": "auto-data"})
    return _normalize_groups(result)


def normalize_visual_cue_boundaries(
    cues: list[VisualCue],
    fps: int = 30,
    total_duration_seconds: float | None = None,
    total_duration_frames: int | None = None,
) -> list[VisualCue]:
    """Normalize visual cue boundaries to guarantee full, contiguous frame coverage.

    Invariants enforced:
    1. First cue starts at frame 0 (cue[0].start_frame == 0, cue[0].start == 0.0).
    2. Adjacent cues are contiguous without gaps or overlaps (cue[i].end_frame == cue[i+1].start_frame).
    3. Last cue extends through canonical timeline end (cue[-1].end_frame == timeline_end_frame).
    4. Every cue has duration_frames >= 1.
    5. Float start/end times are derived directly from canonical frames (start = start_frame / fps, end = end_frame / fps).
    6. Narration text, payload, purpose, visual_type, and cue order are strictly preserved.
    """
    if not cues:
        return []

    fps = max(1, fps)
    n = len(cues)

    # 1. Determine target end frame
    if total_duration_frames is not None and total_duration_frames > 0:
        target_end_frame = total_duration_frames
    elif total_duration_seconds is not None and total_duration_seconds > 0:
        target_end_frame = max(n, round(total_duration_seconds * fps))
    else:
        raw_last_end = cues[-1].end if cues[-1].end is not None else 0.0
        target_end_frame = max(n, round(raw_last_end * fps))

    target_end_frame = max(n, target_end_frame)

    # 2. Extract raw start frames
    raw_starts = [round((c.start or 0.0) * fps) for c in cues]

    # 3. Deterministically assign contiguous frame boundaries
    start_frames: list[int] = [0] * n
    end_frames: list[int] = [0] * n

    start_frames[0] = 0
    for i in range(1, n):
        # min allowed to guarantee cue[i-1] has duration >= 1
        min_allowed = start_frames[i - 1] + 1
        # max allowed to guarantee remaining cues i..n-1 have duration >= 1
        max_allowed = max(min_allowed, target_end_frame - (n - i))
        desired = raw_starts[i]
        start_frames[i] = max(min_allowed, min(desired, max_allowed))
        end_frames[i - 1] = start_frames[i]

    end_frames[n - 1] = max(start_frames[n - 1] + 1, target_end_frame)

    # 4. Construct normalized visual cues
    normalized: list[VisualCue] = []
    for i, cue in enumerate(cues):
        s_frame = start_frames[i]
        e_frame = end_frames[i]
        s_time = round(s_frame / fps, 4)
        e_time = round(e_frame / fps, 4)

        normalized.append(
            cue.model_copy(
                update={
                    "start": s_time,
                    "end": e_time,
                }
            )
        )

    return normalized


def validate_scene_timeline_coverage(
    scenes: list[Any],
    expected_duration_frames: int | None = None,
    fps: int = 30,
) -> tuple[bool, list[str]]:
    """Validate that scenes form an unbroken, contiguous timeline covering all frames.

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors: list[str] = []
    if not scenes:
        return False, ["No scenes provided in timeline"]

    fps = max(1, fps)

    # Check ordering and duplicate orders
    seen_orders: set[int] = set()
    for sc in scenes:
        order = getattr(sc, "order", None)
        if order is not None:
            if order in seen_orders:
                errors.append(f"Duplicate scene order {order} found in timeline")
            seen_orders.add(order)

    # First scene must start at frame 0
    first_sc = scenes[0]
    first_start = getattr(first_sc, "start_frame", None)
    if first_start is None:
        first_start = round((getattr(first_sc, "start", 0.0) or 0.0) * fps)

    if first_start != 0:
        s_id = getattr(first_sc, "scene_id", getattr(first_sc, "id", "first"))
        errors.append(f"First scene {s_id} does not start at frame 0 (starts at frame {first_start})")

    # Contiguity check across adjacent scenes
    total_frames = 0
    for i in range(len(scenes)):
        curr_sc = scenes[i]
        curr_id = getattr(curr_sc, "scene_id", getattr(curr_sc, "id", f"S{i+1:03d}"))
        curr_start = getattr(curr_sc, "start_frame", None)
        if curr_start is None:
            curr_start = round((getattr(curr_sc, "start", 0.0) or 0.0) * fps)
        curr_end = getattr(curr_sc, "end_frame", None)
        if curr_end is None:
            curr_end = round((getattr(curr_sc, "end", 0.0) or 0.0) * fps)
        curr_dur = getattr(curr_sc, "duration_frames", None)
        if curr_dur is None:
            curr_dur = curr_end - curr_start

        if curr_dur < 1:
            errors.append(f"Scene {curr_id} has invalid duration of {curr_dur} frames (must be >= 1)")

        if curr_end - curr_start != curr_dur:
            errors.append(f"Scene {curr_id} duration_frames ({curr_dur}) does not match end_frame - start_frame ({curr_end - curr_start})")

        total_frames += curr_dur

        if i < len(scenes) - 1:
            next_sc = scenes[i + 1]
            next_id = getattr(next_sc, "scene_id", getattr(next_sc, "id", f"S{i+2:03d}"))
            next_start = getattr(next_sc, "start_frame", None)
            if next_start is None:
                next_start = round((getattr(next_sc, "start", 0.0) or 0.0) * fps)

            if curr_end != next_start:
                if next_start > curr_end:
                    gap = next_start - curr_end
                    errors.append(
                        f"Timeline gap of {gap} frames between scene {curr_id} (ends at frame {curr_end}) and scene {next_id} (starts at frame {next_start})"
                    )
                else:
                    overlap = curr_end - next_start
                    errors.append(
                        f"Timeline overlap of {overlap} frames between scene {curr_id} (ends at frame {curr_end}) and scene {next_id} (starts at frame {next_start})"
                    )

    # Check last scene end frame and total duration match
    if expected_duration_frames is not None and expected_duration_frames > 0:
        last_sc = scenes[-1]
        last_id = getattr(last_sc, "scene_id", getattr(last_sc, "id", "last"))
        last_end = getattr(last_sc, "end_frame", None)
        if last_end is None:
            last_end = round((getattr(last_sc, "end", 0.0) or 0.0) * fps)

        if last_end != expected_duration_frames:
            errors.append(
                f"Last scene {last_id} ends at frame {last_end}, expected timeline end frame {expected_duration_frames}"
            )

        if total_frames != expected_duration_frames:
            missing = expected_duration_frames - total_frames
            if missing > 0:
                errors.append(
                    f"Editor scene timeline contains {missing} uncovered frames (scene frames sum to {total_frames}, expected {expected_duration_frames})"
                )
            else:
                errors.append(
                    f"Editor scene timeline contains {-missing} excess frames (scene frames sum to {total_frames}, expected {expected_duration_frames})"
                )

    return (len(errors) == 0, errors)


def plan_visuals(
    project: ProjectSpec,
    timeline_cues: list[TimelineCue],
    *,
    response_fn: Callable[[str], str] | None = None,
    batch_size: int = BATCH_SIZE,
    total_duration_seconds: float | None = None,
    total_duration_frames: int | None = None,
) -> list[VisualCue]:
    response_fn = response_fn or llm.generate_response
    planned: list[VisualCue] = []
    # Pre-compute index positions for O(1) adjacency lookup
    timeline_index_by_id = {cue.id: idx for idx, cue in enumerate(timeline_cues)}
    for start in range(0, len(timeline_cues), batch_size):
        batch = timeline_cues[start : start + batch_size]
        previous = planned[-3:]
        decisions: list[PlannerDecision] | None = None
        error = None
        for _attempt in range(REPAIR_ATTEMPTS + 1):
            try:
                parsed = _parse_batch_response(
                    response_fn(_build_prompt(project, batch, previous, error))
                )
                expected = {(cue.id, cue.order) for cue in batch}
                actual = {(cue.id, cue.order) for cue in parsed.cues}
                if actual != expected or len(parsed.cues) != len(batch):
                    raise PlannerError(
                        "planner must return exactly one decision per requested cue"
                    )
                # Build decisions with LOCAL grounding context per cue.
                # Context is limited to current + immediately adjacent cues only.
                # The full project script is NOT included to prevent values from
                # distant scenes being treated as valid grounding here.
                cue_by_id = {cue.id: cue for cue in batch}
                decisions = [
                    _canonical_visual(
                        decision,
                        cue_by_id[decision.id],
                        _build_local_context(
                            timeline_cues,
                            timeline_index_by_id[decision.id],
                        ),
                    )
                    for decision in parsed.cues
                ]
                break
            except (ValueError, TypeError, ValidationError, PlannerError) as exc:
                error = str(exc)
        if decisions is None:
            decisions = [fallback_visual(project, cue) for cue in batch]
        planned.extend(decisions)
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
