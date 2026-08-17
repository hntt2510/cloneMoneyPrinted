import logging
import re
from typing import Any

from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan
from app.services.numeric_parser import extract_canonical_numeric_facts
from app.services.timeline import _split_clauses, _text_weight

logger = logging.getLogger(__name__)


def validate_animation_plan_quality(
    plan: MotionAnimationPlan,
    duration_frames: int,
) -> list[str]:
    """Validate kinetic animation plan against static-plateau and timing quality heuristics."""
    warnings: list[str] = []
    if not plan.beats:
        return warnings

    # If active narration scene is >= 30 frames, but all scheduled beats end before 15% of duration
    if duration_frames >= 30:
        last_end = plan.beats[-1].end_frame
        if last_end < duration_frames * 0.15:
            warnings.append(
                f"Scene {plan.scene_id} animation plateau: all beats end at frame {last_end} "
                f"(< 15% of total {duration_frames} frames)"
            )

    return warnings


def derive_kinetic_beats(
    narration: str,
    fps: int,
    duration_frames: int,
    timing_source: str = "estimated",
    template: str = "callout",
    scene_id: str = "S001",
    props: dict[str, Any] | None = None,
) -> MotionAnimationPlan:
    """Derive deterministic, template-aware kinetic beats from narration and structured props.

    Priority order:
    1. Template semantics dictate the structural beat kinds (comparison_item, chart_item, milestone, threshold).
    2. Structured props (e.g. comparison items, bar chart bars, line chart points, milestones) map to beats.
    3. Canonical spoken numbers and keyword semantics enrich beat timing and data references.
    4. Duration is allocated proportionally by text weight with a reserve for final hold.
    """
    props = props or {}
    clauses = _split_clauses(narration) if narration else []
    total_weight = sum(_text_weight(c) for c in clauses)

    final_hold_frames = min(36, max(12, duration_frames // 6)) if duration_frames >= 24 else max(0, duration_frames // 4)
    available_frames = max(1, duration_frames - final_hold_frames)

    # Determine provenance string
    if timing_source in ("user_srt", "tts", "whisper"):
        kinetic_provenance = f"{timing_source}_cue_exact+intra_cue_estimated"
    else:
        kinetic_provenance = "intra_cue_estimated"

    if not clauses or total_weight == 0:
        return MotionAnimationPlan(
            scene_id=scene_id,
            beats=[],
            final_hold_frames=final_hold_frames,
            timing_source=timing_source,
            kinetic_timing_source=kinetic_provenance,
        )

    # Compute base frame slices for clauses
    clause_slices: list[tuple[int, int]] = []
    current_f = 0
    for i, clause in enumerate(clauses):
        weight = _text_weight(clause)
        if i == len(clauses) - 1:
            frames = max(1, available_frames - current_f)
        else:
            frames = max(1, round(available_frames * (weight / total_weight)))
        start_f = current_f
        end_f = current_f + frames
        current_f = end_f
        clause_slices.append((start_f, end_f))

    beats: list[KineticBeat] = []

    # -------------------------------------------------------------------------
    # 1. COMPARISON TEMPLATE
    # -------------------------------------------------------------------------
    if template == "comparison":
        items = props.get("items", [])
        num_items = len(items)

        if num_items >= 2:
            # If we have multiple structured items, ensure each item gets a comparison_item beat
            if len(clauses) >= num_items:
                # Try matching clauses to items via numeric facts first
                matched_clause_to_item: dict[int, int] = {}
                used_items: set[int] = set()

                for c_idx, clause in enumerate(clauses):
                    c_facts = extract_canonical_numeric_facts(clause)
                    for item_idx, item in enumerate(items):
                        if item_idx in used_items:
                            continue
                        item_val = item.get("numeric_value")
                        if item_val is not None and any(abs(f.value - item_val) < 1e-3 for f in c_facts):
                            matched_clause_to_item[c_idx] = item_idx
                            used_items.add(item_idx)
                            break

                # For remaining unassigned clauses, try label matching or sequential assignment
                unassigned_items = [idx for idx in range(num_items) if idx not in used_items]
                for c_idx, clause in enumerate(clauses):
                    if c_idx not in matched_clause_to_item:
                        c_lower = clause.lower()
                        # Try label match
                        matched = False
                        for item_idx in list(unassigned_items):
                            label = str(items[item_idx].get("label", "")).lower()
                            if label and label in c_lower:
                                matched_clause_to_item[c_idx] = item_idx
                                unassigned_items.remove(item_idx)
                                matched = True
                                break
                        if not matched and unassigned_items:
                            matched_clause_to_item[c_idx] = unassigned_items.pop(0)

                for c_idx, clause in enumerate(clauses):
                    start_f, end_f = clause_slices[c_idx]
                    if c_idx in matched_clause_to_item:
                        item_idx = matched_clause_to_item[c_idx]
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{c_idx}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.comparison_item,
                                text=clause,
                                emphasis=bool(items[item_idx].get("highlight")),
                                data_ref=f"item_{item_idx}",
                            )
                        )
                    else:
                        is_last = c_idx == len(clauses) - 1
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{c_idx}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.takeaway if is_last else KineticBeatKind.phrase,
                                text=clause,
                                emphasis=is_last,
                                data_ref=None,
                            )
                        )
            else:
                # Fewer clauses than items (e.g. 1 sentence covering 2 or 3 items):
                # Subdivide available frames among the structured items
                for item_idx in range(num_items):
                    sub_start = round(available_frames * (item_idx / num_items))
                    sub_end = round(available_frames * ((item_idx + 1) / num_items))
                    item_label = str(items[item_idx].get("label", f"Item {item_idx + 1}"))
                    item_val = str(items[item_idx].get("value", ""))
                    beats.append(
                        KineticBeat(
                            id=f"{scene_id}_b{item_idx}",
                            start_frame=sub_start,
                            end_frame=sub_end,
                            kind=KineticBeatKind.comparison_item,
                            text=f"{item_label}: {item_val}".strip(),
                            emphasis=bool(items[item_idx].get("highlight")),
                            data_ref=f"item_{item_idx}",
                        )
                    )
        else:
            # Generic comparison without explicit items
            for i, clause in enumerate(clauses):
                start_f, end_f = clause_slices[i]
                beats.append(
                    KineticBeat(
                        id=f"{scene_id}_b{i}",
                        start_frame=start_f,
                        end_frame=end_f,
                        kind=KineticBeatKind.comparison_item,
                        text=clause,
                        emphasis=False,
                        data_ref=f"item_{i}",
                    )
                )

    # -------------------------------------------------------------------------
    # 2. BAR CHART TEMPLATE
    # -------------------------------------------------------------------------
    elif template == "bar_chart":
        items = props.get("items", [])
        num_items = len(items)

        if num_items >= 2:
            if len(clauses) >= num_items:
                # Match or sequentially map clauses to bars
                for i, clause in enumerate(clauses):
                    start_f, end_f = clause_slices[i]
                    if i < num_items:
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{i}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.chart_item,
                                text=clause,
                                emphasis=False,
                                data_ref=f"bar_{i}",
                            )
                        )
                    else:
                        is_last = i == len(clauses) - 1
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{i}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.takeaway if is_last else KineticBeatKind.phrase,
                                text=clause,
                                emphasis=is_last,
                                data_ref=None,
                            )
                        )
            else:
                # Fewer clauses than bars: subdivide among the bars
                for bar_idx in range(num_items):
                    sub_start = round(available_frames * (bar_idx / num_items))
                    sub_end = round(available_frames * ((bar_idx + 1) / num_items))
                    bar_label = str(items[bar_idx].get("label", f"Bar {bar_idx + 1}"))
                    beats.append(
                        KineticBeat(
                            id=f"{scene_id}_b{bar_idx}",
                            start_frame=sub_start,
                            end_frame=sub_end,
                            kind=KineticBeatKind.chart_item,
                            text=bar_label,
                            emphasis=False,
                            data_ref=f"bar_{bar_idx}",
                        )
                    )
        else:
            for i, clause in enumerate(clauses):
                start_f, end_f = clause_slices[i]
                beats.append(
                    KineticBeat(
                        id=f"{scene_id}_b{i}",
                        start_frame=start_f,
                        end_frame=end_f,
                        kind=KineticBeatKind.chart_item,
                        text=clause,
                        emphasis=False,
                        data_ref=f"bar_{i}",
                    )
                )

    # -------------------------------------------------------------------------
    # 3. LINE CHART TEMPLATE
    # -------------------------------------------------------------------------
    elif template == "line_chart":
        points = props.get("points", [])
        num_points = len(points)

        if num_points >= 2:
            if len(clauses) >= num_points:
                for i, clause in enumerate(clauses):
                    start_f, end_f = clause_slices[i]
                    if i < num_points:
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{i}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.chart_item,
                                text=clause,
                                emphasis=False,
                                data_ref=f"point_{i}",
                            )
                        )
                    else:
                        is_last = i == len(clauses) - 1
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{i}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.takeaway if is_last else KineticBeatKind.phrase,
                                text=clause,
                                emphasis=is_last,
                                data_ref=None,
                            )
                        )
            else:
                for pt_idx in range(num_points):
                    sub_start = round(available_frames * (pt_idx / num_points))
                    sub_end = round(available_frames * ((pt_idx + 1) / num_points))
                    pt_label = str(points[pt_idx].get("x_label", f"Point {pt_idx + 1}"))
                    beats.append(
                        KineticBeat(
                            id=f"{scene_id}_b{pt_idx}",
                            start_frame=sub_start,
                            end_frame=sub_end,
                            kind=KineticBeatKind.chart_item,
                            text=pt_label,
                            emphasis=False,
                            data_ref=f"point_{pt_idx}",
                        )
                    )
        else:
            for i, clause in enumerate(clauses):
                start_f, end_f = clause_slices[i]
                beats.append(
                    KineticBeat(
                        id=f"{scene_id}_b{i}",
                        start_frame=start_f,
                        end_frame=end_f,
                        kind=KineticBeatKind.chart_item,
                        text=clause,
                        emphasis=False,
                        data_ref=f"point_{i}",
                    )
                )

    # -------------------------------------------------------------------------
    # 4. TIMELINE TEMPLATE
    # -------------------------------------------------------------------------
    elif template == "timeline":
        milestones = props.get("milestones", [])
        num_m = len(milestones)

        if num_m >= 2:
            if len(clauses) >= num_m:
                for i, clause in enumerate(clauses):
                    start_f, end_f = clause_slices[i]
                    if i < num_m:
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{i}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.milestone,
                                text=clause,
                                emphasis=bool(milestones[i].get("is_active")),
                                data_ref=f"m_{i}",
                            )
                        )
                    else:
                        is_last = i == len(clauses) - 1
                        beats.append(
                            KineticBeat(
                                id=f"{scene_id}_b{i}",
                                start_frame=start_f,
                                end_frame=end_f,
                                kind=KineticBeatKind.takeaway if is_last else KineticBeatKind.phrase,
                                text=clause,
                                emphasis=is_last,
                                data_ref=None,
                            )
                        )
            else:
                for m_idx in range(num_m):
                    sub_start = round(available_frames * (m_idx / num_m))
                    sub_end = round(available_frames * ((m_idx + 1) / num_m))
                    m_title = str(milestones[m_idx].get("title", f"Milestone {m_idx + 1}"))
                    beats.append(
                        KineticBeat(
                            id=f"{scene_id}_b{m_idx}",
                            start_frame=sub_start,
                            end_frame=sub_end,
                            kind=KineticBeatKind.milestone,
                            text=m_title,
                            emphasis=bool(milestones[m_idx].get("is_active")),
                            data_ref=f"m_{m_idx}",
                        )
                    )
        else:
            for i, clause in enumerate(clauses):
                start_f, end_f = clause_slices[i]
                beats.append(
                    KineticBeat(
                        id=f"{scene_id}_b{i}",
                        start_frame=start_f,
                        end_frame=end_f,
                        kind=KineticBeatKind.milestone,
                        text=clause,
                        emphasis=False,
                        data_ref=f"m_{i}",
                    )
                )

    # -------------------------------------------------------------------------
    # 5. THRESHOLD TEMPLATE
    # -------------------------------------------------------------------------
    elif template == "threshold":
        thresh_val = props.get("threshold_value")
        curr_val = props.get("current_value")

        if len(clauses) >= 2:
            # Check if clauses mention threshold and current/damage values
            thresh_clause_idx = 0
            curr_clause_idx = 1

            for c_idx, clause in enumerate(clauses):
                c_facts = extract_canonical_numeric_facts(clause)
                if thresh_val is not None and any(abs(f.value - thresh_val) < 1e-3 for f in c_facts):
                    thresh_clause_idx = c_idx
                elif curr_val is not None and any(abs(f.value - curr_val) < 1e-3 for f in c_facts):
                    curr_clause_idx = c_idx

            for i, clause in enumerate(clauses):
                start_f, end_f = clause_slices[i]
                if i == thresh_clause_idx:
                    beats.append(
                        KineticBeat(
                            id=f"{scene_id}_b{i}",
                            start_frame=start_f,
                            end_frame=end_f,
                            kind=KineticBeatKind.threshold,
                            text=clause,
                            emphasis=False,
                            data_ref="threshold",
                        )
                    )
                elif i == curr_clause_idx:
                    beats.append(
                        KineticBeat(
                            id=f"{scene_id}_b{i}",
                            start_frame=start_f,
                            end_frame=end_f,
                            kind=KineticBeatKind.number,
                            text=clause,
                            emphasis=True,
                            data_ref="current_value",
                        )
                    )
                else:
                    is_last = i == len(clauses) - 1
                    beats.append(
                        KineticBeat(
                            id=f"{scene_id}_b{i}",
                            start_frame=start_f,
                            end_frame=end_f,
                            kind=KineticBeatKind.takeaway if is_last else KineticBeatKind.phrase,
                            text=clause,
                            emphasis=is_last,
                            data_ref=None,
                        )
                    )
        else:
            # 1 clause: split into Phase 1 (Threshold intro) and Phase 2 (Growth & crossing)
            half_f = max(1, available_frames // 2)
            beats.append(
                KineticBeat(
                    id=f"{scene_id}_b0",
                    start_frame=0,
                    end_frame=half_f,
                    kind=KineticBeatKind.threshold,
                    text=f"{props.get('threshold_label', 'Threshold')}: {props.get('threshold_display', thresh_val or '')}".strip(),
                    emphasis=False,
                    data_ref="threshold",
                )
            )
            beats.append(
                KineticBeat(
                    id=f"{scene_id}_b1",
                    start_frame=half_f,
                    end_frame=available_frames,
                    kind=KineticBeatKind.number,
                    text=f"Current: {props.get('current_display', curr_val or '')}".strip(),
                    emphasis=True,
                    data_ref="current_value",
                )
            )

    # -------------------------------------------------------------------------
    # 6. NUMBER & COUNTER TEMPLATES
    # -------------------------------------------------------------------------
    elif template in ("number", "counter"):
        target_val = props.get("numeric_value") if template == "number" else props.get("end_value")
        num_clause_idx = 0

        # Find clause that mentions the target value
        if target_val is not None:
            for c_idx, clause in enumerate(clauses):
                c_facts = extract_canonical_numeric_facts(clause)
                if any(abs(f.value - target_val) < 1e-3 for f in c_facts):
                    num_clause_idx = c_idx
                    break
        else:
            for c_idx, clause in enumerate(clauses):
                if extract_canonical_numeric_facts(clause):
                    num_clause_idx = c_idx
                    break

        for i, clause in enumerate(clauses):
            start_f, end_f = clause_slices[i]
            if i == num_clause_idx:
                beats.append(
                    KineticBeat(
                        id=f"{scene_id}_b{i}",
                        start_frame=start_f,
                        end_frame=end_f,
                        kind=KineticBeatKind.number,
                        text=clause,
                        emphasis=True,
                        data_ref="number",
                    )
                )
            elif i > num_clause_idx and any(kw in clause.lower() for kw in ["best", "worst", "remember", "key", "important", "recommend"]):
                beats.append(
                    KineticBeat(
                        id=f"{scene_id}_b{i}",
                        start_frame=start_f,
                        end_frame=end_f,
                        kind=KineticBeatKind.takeaway,
                        text=clause,
                        emphasis=True,
                        data_ref=None,
                    )
                )
            else:
                beats.append(
                    KineticBeat(
                        id=f"{scene_id}_b{i}",
                        start_frame=start_f,
                        end_frame=end_f,
                        kind=KineticBeatKind.phrase,
                        text=clause,
                        emphasis=False,
                        data_ref=None,
                    )
                )

    # -------------------------------------------------------------------------
    # 7. TEXT, CALLOUT, & OTHER TEMPLATES
    # -------------------------------------------------------------------------
    else:
        for i, clause in enumerate(clauses):
            start_f, end_f = clause_slices[i]
            is_last = i == len(clauses) - 1
            lower = clause.lower()
            is_takeaway = is_last and any(kw in lower for kw in ["best", "worst", "remember", "key", "important", "recommend", "conclusion"])

            beats.append(
                KineticBeat(
                    id=f"{scene_id}_b{i}",
                    start_frame=start_f,
                    end_frame=end_f,
                    kind=KineticBeatKind.takeaway if is_takeaway else KineticBeatKind.phrase,
                    text=clause,
                    emphasis=is_takeaway,
                    data_ref=None,
                )
            )

    plan = MotionAnimationPlan(
        scene_id=scene_id,
        beats=beats,
        final_hold_frames=final_hold_frames,
        timing_source=timing_source,
        kinetic_timing_source=kinetic_provenance,
    )

    quality_warnings = validate_animation_plan_quality(plan, duration_frames)
    for q_warn in quality_warnings:
        logger.warning(q_warn)

    return plan
