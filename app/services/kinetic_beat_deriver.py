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

        if num_items == 2:
            item_0_end = round(available_frames * 0.35)
            divider_end = round(available_frames * 0.50)
            item_1_end = round(available_frames * 0.82)
            takeaway_end = round(available_frames * 0.92)

            beats = [
                KineticBeat(id=f"{scene_id}_item0", start_frame=0, end_frame=item_0_end,
                            kind=KineticBeatKind.comparison_item, text=items[0].get("label",""), 
                            emphasis=bool(items[0].get("highlight")), data_ref="item_0"),
                KineticBeat(id=f"{scene_id}_divider", start_frame=item_0_end, end_frame=divider_end,
                            kind=KineticBeatKind.split, text="divider",
                            emphasis=False, data_ref="divider"),
                KineticBeat(id=f"{scene_id}_item1", start_frame=divider_end, end_frame=item_1_end,
                            kind=KineticBeatKind.comparison_item, text=items[1].get("label",""),
                            emphasis=bool(items[1].get("highlight")), data_ref="item_1"),
                KineticBeat(id=f"{scene_id}_takeaway", start_frame=item_1_end, end_frame=takeaway_end,
                            kind=KineticBeatKind.takeaway, text="relationship", 
                            emphasis=True, data_ref=None),
            ]
        elif num_items > 2:
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
        if len(clauses) >= 2:
            clause_0_end = clause_slices[0][1]
            limit_end = max(6, round(clause_0_end * 0.45))
            grow_start = max(limit_end, round(clause_0_end * 0.85))
            cross_frame = min(available_frames - 10, round(clause_slices[1][0] + (clause_slices[1][1] - clause_slices[1][0]) * 0.40))
            resolve_frame = min(available_frames - 5, round(clause_slices[1][0] + (clause_slices[1][1] - clause_slices[1][0]) * 0.75))
        else:
            limit_end = max(6, round(available_frames * 0.20))
            grow_start = max(limit_end + 2, round(available_frames * 0.25))
            cross_frame = max(grow_start + 10, round(available_frames * 0.70))
            resolve_frame = max(cross_frame + 5, round(available_frames * 0.82))

        beats = [
            KineticBeat(id=f"{scene_id}_limit", start_frame=0, end_frame=limit_end,
                        kind=KineticBeatKind.threshold, text=f"{props.get('threshold_label','Limit')}: {props.get('threshold_display','')}",
                        emphasis=False, data_ref="threshold"),
            KineticBeat(id=f"{scene_id}_grow", start_frame=grow_start, end_frame=cross_frame,
                        kind=KineticBeatKind.number, text=f"Current: {props.get('current_display','')}",
                        emphasis=True, data_ref="current_value"),
            KineticBeat(id=f"{scene_id}_cross", start_frame=cross_frame, end_frame=resolve_frame,
                        kind=KineticBeatKind.highlight, text="crossing",
                        emphasis=True, data_ref="current_value"),
            KineticBeat(id=f"{scene_id}_resolve", start_frame=resolve_frame, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text="OVER LIMIT",
                        emphasis=True, data_ref="resolve"),
        ]

    # -------------------------------------------------------------------------
    # 6. NUMBER & COUNTER TEMPLATES
    # -------------------------------------------------------------------------
    elif template in ("number", "counter"):
        target_val = props.get("numeric_value") if template == "number" else props.get("end_value")
        headline = str(props.get("headline", ""))
        setup_end = max(3, round(available_frames * 0.15))
        reveal_end = max(setup_end + 2, round(available_frames * 0.20))
        count_end = max(reveal_end + 5, round(available_frames * 0.75))
        highlight_end = max(count_end + 2, round(available_frames * 0.83))
        context_end = max(highlight_end + 2, round(available_frames * 0.90))

        beats = [
            KineticBeat(id=f"{scene_id}_setup", start_frame=0, end_frame=setup_end, 
                        kind=KineticBeatKind.setup, text=props.get("eyebrow") or "Label", emphasis=False, data_ref="eyebrow"),
            KineticBeat(id=f"{scene_id}_reveal", start_frame=setup_end, end_frame=reveal_end,
                        kind=KineticBeatKind.reveal, text=headline, emphasis=False, data_ref="headline"),
            KineticBeat(id=f"{scene_id}_number", start_frame=reveal_end, end_frame=count_end,
                        kind=KineticBeatKind.number, text=str(target_val or ""), emphasis=True, data_ref="number"),
            KineticBeat(id=f"{scene_id}_highlight", start_frame=count_end, end_frame=highlight_end,
                        kind=KineticBeatKind.highlight, text="settle", emphasis=True, data_ref="number"),
            KineticBeat(id=f"{scene_id}_context", start_frame=highlight_end, end_frame=context_end,
                        kind=KineticBeatKind.phrase, text=props.get("context_label") or props.get("label") or "", 
                        emphasis=False, data_ref="context"),
        ]

    # -------------------------------------------------------------------------
    # 7. PIE & DONUT TEMPLATES
    # -------------------------------------------------------------------------
    elif template in ("pie", "donut"):
        items = props.get("items", [])
        num_items = max(2, len(items))
        setup_end = max(3, round(available_frames * 0.15))
        slices_span = round(available_frames * 0.70) - setup_end
        per_slice_f = max(2, slices_span // num_items)

        beats = [
            KineticBeat(id=f"{scene_id}_setup", start_frame=0, end_frame=setup_end,
                        kind=KineticBeatKind.setup, text=props.get("eyebrow") or "Distribution",
                        emphasis=False, data_ref="track"),
        ]
        curr_f = setup_end
        for idx in range(num_items):
            nxt_f = min(round(available_frames * 0.70), curr_f + per_slice_f)
            lbl = items[idx].get("label", f"Part {idx + 1}") if idx < len(items) else f"Part {idx + 1}"
            beats.append(
                KineticBeat(id=f"{scene_id}_seg{idx}", start_frame=curr_f, end_frame=nxt_f,
                            kind=KineticBeatKind.segment, text=lbl,
                            emphasis=bool(items[idx].get("highlight")) if idx < len(items) else False,
                            data_ref=f"segment_{idx}")
            )
            curr_f = nxt_f

        highlight_end = min(round(available_frames * 0.85), curr_f + 8)
        beats.append(
            KineticBeat(id=f"{scene_id}_highlight", start_frame=curr_f, end_frame=highlight_end,
                        kind=KineticBeatKind.highlight, text=props.get("focus_label") or "Focus",
                        emphasis=True, data_ref="focus")
        )
        beats.append(
            KineticBeat(id=f"{scene_id}_resolve", start_frame=highlight_end, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text=props.get("headline", ""),
                        emphasis=True, data_ref="resolve")
        )

    # -------------------------------------------------------------------------
    # 8. GAUGE & PROGRESS TEMPLATES
    # -------------------------------------------------------------------------
    elif template == "gauge":
        setup_end = max(3, round(available_frames * 0.15))
        arc_end = round(available_frames * 0.65)
        num_end = round(available_frames * 0.80)

        beats = [
            KineticBeat(id=f"{scene_id}_setup", start_frame=0, end_frame=setup_end,
                        kind=KineticBeatKind.setup, text=props.get("eyebrow") or "Goal",
                        emphasis=False, data_ref="track"),
            KineticBeat(id=f"{scene_id}_arc", start_frame=setup_end, end_frame=arc_end,
                        kind=KineticBeatKind.arc, text="Fill",
                        emphasis=True, data_ref="arc"),
            KineticBeat(id=f"{scene_id}_num", start_frame=arc_end, end_frame=num_end,
                        kind=KineticBeatKind.number, text=props.get("display_value", ""),
                        emphasis=True, data_ref="number"),
            KineticBeat(id=f"{scene_id}_resolve", start_frame=num_end, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text=props.get("label", ""),
                        emphasis=False, data_ref="resolve"),
        ]

    # -------------------------------------------------------------------------
    # 9. WATERFALL TEMPLATE
    # -------------------------------------------------------------------------
    elif template == "waterfall":
        steps = props.get("steps", [])
        num_steps = max(1, len(steps))
        setup_end = max(4, round(available_frames * 0.20))
        step_span = round(available_frames * 0.75) - setup_end
        per_step_f = max(3, step_span // num_steps)

        beats = [
            KineticBeat(id=f"{scene_id}_start", start_frame=0, end_frame=setup_end,
                        kind=KineticBeatKind.setup, text=f"Start: {props.get('start_value', '')}",
                        emphasis=False, data_ref="start"),
        ]
        curr_f = setup_end
        for idx, stp in enumerate(steps):
            nxt_f = min(round(available_frames * 0.75), curr_f + per_step_f)
            beats.append(
                KineticBeat(id=f"{scene_id}_step{idx}", start_frame=curr_f, end_frame=nxt_f,
                            kind=KineticBeatKind.step, text=stp.get("label", f"Step {idx + 1}"),
                            emphasis=True, data_ref=f"step_{idx}")
            )
            curr_f = nxt_f

        beats.append(
            KineticBeat(id=f"{scene_id}_end", start_frame=curr_f, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text=f"Final: {props.get('end_value', '')}",
                        emphasis=True, data_ref="end")
        )

    # -------------------------------------------------------------------------
    # 10. RANKED LIST TEMPLATE
    # -------------------------------------------------------------------------
    elif template == "ranked_list":
        items = props.get("items", [])
        num_items = max(2, len(items))
        setup_end = max(3, round(available_frames * 0.15))
        ranks_span = round(available_frames * 0.75) - setup_end
        per_rank_f = max(3, ranks_span // num_items)

        beats = [
            KineticBeat(id=f"{scene_id}_setup", start_frame=0, end_frame=setup_end,
                        kind=KineticBeatKind.setup, text=props.get("eyebrow") or "Rankings",
                        emphasis=False, data_ref="header"),
        ]
        curr_f = setup_end
        for idx in range(num_items):
            nxt_f = min(round(available_frames * 0.75), curr_f + per_rank_f)
            lbl = items[idx].get("label", f"Rank #{idx + 1}") if idx < len(items) else f"Rank #{idx + 1}"
            beats.append(
                KineticBeat(id=f"{scene_id}_rank{idx}", start_frame=curr_f, end_frame=nxt_f,
                            kind=KineticBeatKind.rank, text=lbl,
                            emphasis=(idx == 0), data_ref=f"rank_{idx}")
            )
            curr_f = nxt_f

        beats.append(
            KineticBeat(id=f"{scene_id}_resolve", start_frame=curr_f, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text="Top Rank",
                        emphasis=True, data_ref="top_rank")
        )

    # -------------------------------------------------------------------------
    # 11. AREA & STACKED BAR & BEFORE/AFTER TEMPLATES
    # -------------------------------------------------------------------------
    elif template in ("area", "area_chart"):
        setup_end = max(3, round(available_frames * 0.20))
        draw_end = round(available_frames * 0.70)
        points_end = round(available_frames * 0.85)

        beats = [
            KineticBeat(id=f"{scene_id}_axes", start_frame=0, end_frame=setup_end,
                        kind=KineticBeatKind.setup, text="Axes", emphasis=False, data_ref="axes"),
            KineticBeat(id=f"{scene_id}_draw", start_frame=setup_end, end_frame=draw_end,
                        kind=KineticBeatKind.draw, text="Area Fill", emphasis=True, data_ref="area"),
            KineticBeat(id=f"{scene_id}_points", start_frame=draw_end, end_frame=points_end,
                        kind=KineticBeatKind.chart_item, text="Points", emphasis=False, data_ref="points"),
            KineticBeat(id=f"{scene_id}_resolve", start_frame=points_end, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text="Takeaway", emphasis=True, data_ref="resolve"),
        ]

    elif template == "before_after":
        setup_end = max(3, round(available_frames * 0.15))
        before_end = round(available_frames * 0.45)
        after_end = round(available_frames * 0.75)

        beats = [
            KineticBeat(id=f"{scene_id}_setup", start_frame=0, end_frame=setup_end,
                        kind=KineticBeatKind.setup, text="Comparison", emphasis=False, data_ref="divider"),
            KineticBeat(id=f"{scene_id}_before", start_frame=setup_end, end_frame=before_end,
                        kind=KineticBeatKind.before, text=props.get("before_label", "Before"),
                        emphasis=False, data_ref="before"),
            KineticBeat(id=f"{scene_id}_after", start_frame=before_end, end_frame=after_end,
                        kind=KineticBeatKind.after, text=props.get("after_label", "After"),
                        emphasis=True, data_ref="after"),
            KineticBeat(id=f"{scene_id}_resolve", start_frame=after_end, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text=props.get("delta_display", "Delta"),
                        emphasis=True, data_ref="delta"),
        ]

    elif template == "stacked_bar":
        segs = props.get("segments", [])
        num_segs = max(2, len(segs))
        setup_end = max(3, round(available_frames * 0.15))
        seg_span = round(available_frames * 0.75) - setup_end
        per_seg_f = max(3, seg_span // num_segs)

        beats = [
            KineticBeat(id=f"{scene_id}_setup", start_frame=0, end_frame=setup_end,
                        kind=KineticBeatKind.setup, text=props.get("headline", ""),
                        emphasis=False, data_ref="total"),
        ]
        curr_f = setup_end
        for idx in range(num_segs):
            nxt_f = min(round(available_frames * 0.75), curr_f + per_seg_f)
            beats.append(
                KineticBeat(id=f"{scene_id}_seg{idx}", start_frame=curr_f, end_frame=nxt_f,
                            kind=KineticBeatKind.segment, text=segs[idx].get("label", f"Segment {idx + 1}") if idx < len(segs) else f"Segment {idx + 1}",
                            emphasis=bool(segs[idx].get("highlight")) if idx < len(segs) else False,
                            data_ref=f"segment_{idx}")
            )
            curr_f = nxt_f

        beats.append(
            KineticBeat(id=f"{scene_id}_resolve", start_frame=curr_f, end_frame=available_frames,
                        kind=KineticBeatKind.resolve, text="Total", emphasis=True, data_ref="resolve")
        )

    # -------------------------------------------------------------------------
    # 12. TEXT, CALLOUT, & OTHER TEMPLATES
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


def resolve_progressive_copy(
    text: str,
    start_frame: int,
    end_frame: int,
    frame: int,
    mode: str = "word",
) -> list[str]:
    """Deterministically resolve the list of currently visible units for a given frame.

    Mirrors the Remotion ProgressiveText component behavior:
    - Splits text into words or phrases.
    - Computes each unit's start frame across [start_frame, end_frame].
    - Returns all units whose start_frame <= frame.
    """
    if not text or not text.strip():
        return []

    if mode == "phrase":
        raw_units = [u.strip() for u in re.split(r"([,;:]|\s+-\s+)", text) if u.strip()]
    else:
        raw_units = [w.strip() for w in text.split() if w.strip()]

    if not raw_units:
        return []

    num_units = len(raw_units)
    total_frames = max(1, end_frame - start_frame)
    step_frames = total_frames / num_units if num_units > 1 else total_frames

    visible_units: list[str] = []
    for idx, unit in enumerate(raw_units):
        unit_start = start_frame + round(idx * step_frames)
        if frame >= unit_start:
            visible_units.append(unit)

    return visible_units


def resolve_threshold_copy_state(
    headline: str,
    eyebrow: str | None,
    threshold_label: str,
    threshold_value: float,
    current_value: float,
    frame: int,
    duration_frames: int,
    animation_plan: MotionAnimationPlan | None = None,
) -> dict[str, Any]:
    """Deterministically compute the exact visible copy state for a threshold scene at `frame`."""
    has_overflow = current_value > threshold_value

    limit_beat = next(
        (b for b in (animation_plan.beats if animation_plan else []) if b.kind == KineticBeatKind.threshold or "limit" in b.id),
        None,
    )
    grow_beat = next(
        (b for b in (animation_plan.beats if animation_plan else []) if "grow" in b.id or b.kind == KineticBeatKind.number),
        None,
    )
    cross_beat = next(
        (b for b in (animation_plan.beats if animation_plan else []) if "cross" in b.id or b.kind == KineticBeatKind.highlight),
        None,
    )
    resolve_beat = next(
        (b for b in (animation_plan.beats if animation_plan else []) if "resolve" in b.id or b.kind == KineticBeatKind.resolve),
        None,
    )

    phase1_setup = 0
    phase2_limit = (
        max(0, limit_beat.start_frame + round((limit_beat.end_frame - limit_beat.start_frame) * 0.35))
        if limit_beat
        else round(duration_frames * 0.12)
    )
    phase3_grow_start = grow_beat.start_frame if grow_beat else round(duration_frames * 0.25)
    phase4_cross = cross_beat.start_frame if cross_beat else round(duration_frames * 0.72)
    phase5_resolve = resolve_beat.start_frame if resolve_beat else round(duration_frames * 0.82)

    is_conclusion = bool(
        re.search(r"\b(?:exceeds?|exceeded|over\s+limit|above\s+limit|beyond\s+limit)\b", headline, re.I)
    )
    neutral_subject = headline
    if is_conclusion:
        neutral_subject = re.sub(
            r"\b(?:damage\s+exceeds\s+limit|exceeds?\s+(?:policy\s+)?limit|exceeded)\b", "", headline, flags=re.I
        ).strip()
        if not neutral_subject or len(neutral_subject) < 2:
            neutral_subject = (
                eyebrow
                if eyebrow
                else (
                    threshold_label.upper()
                    if threshold_label.upper().endswith("LIMIT")
                    else f"{threshold_label.upper()} LIMIT"
                )
            )

    show_conclusion = has_overflow and frame >= phase4_cross

    if show_conclusion:
        active_headline_words = resolve_progressive_copy(headline, phase4_cross, phase5_resolve, frame, mode="word")
        active_eyebrow = "LIMIT EXCEEDED"
    else:
        active_headline_words = resolve_progressive_copy(neutral_subject, phase1_setup, phase2_limit, frame, mode="word")
        active_eyebrow = eyebrow if (eyebrow and eyebrow != neutral_subject) else threshold_label.upper()

    consequence_visible = has_overflow and frame >= phase5_resolve

    return {
        "frame": frame,
        "phase": (
            "resolve"
            if frame >= phase5_resolve
            else "crossing"
            if frame >= phase4_cross
            else "growing"
            if frame >= phase3_grow_start
            else "limit_reveal"
            if frame >= phase2_limit
            else "setup"
        ),
        "headline_words": active_headline_words,
        "headline_text": " ".join(active_headline_words),
        "eyebrow": active_eyebrow,
        "show_conclusion": show_conclusion,
        "consequence_visible": consequence_visible,
        "is_full_conclusion_visible": active_headline_words == [w for w in headline.split() if w],
    }


def resolve_threshold_group_state(
    scenes: list[dict[str, Any]],
    duration_frames: int,
    frame: int,
) -> dict[str, Any]:
    """Deterministically resolve the multi-cue ThresholdGroupMaster visual & copy state at `frame`."""
    s0 = scenes[0].get("props", {}) if scenes else {}
    s1 = scenes[1].get("props", {}) if len(scenes) > 1 else s0

    cur_val = float(s1.get("current_value") if s1.get("current_value") is not None else s0.get("current_value", 0.0))
    thres_val = float(s0.get("threshold_value") if s0.get("threshold_value") is not None else s1.get("threshold_value", 0.0))
    has_overflow = cur_val > thres_val

    s0_dur = scenes[0].get("duration_frames", round(duration_frames / 2)) if scenes else round(duration_frames / 2)
    s1_dur = scenes[1].get("duration_frames", duration_frames - s0_dur) if len(scenes) > 1 else (duration_frames - s0_dur)
    s1_offset = s0_dur

    plan0 = scenes[0].get("animation_plan") or s0.get("animation_plan") or {}
    plan1 = (scenes[1].get("animation_plan") or s1.get("animation_plan") or {}) if len(scenes) > 1 else plan0

    beats0 = plan0.get("beats", []) if isinstance(plan0, dict) else (plan0.beats if hasattr(plan0, "beats") else [])
    beats1 = plan1.get("beats", []) if isinstance(plan1, dict) else (plan1.beats if hasattr(plan1, "beats") else [])

    def _get_kind(b: Any) -> str:
        k = getattr(b, "kind", None) or (b.get("kind") if isinstance(b, dict) else "")
        return str(getattr(k, "value", k))

    def _get_id(b: Any) -> str:
        return str(getattr(b, "id", None) or (b.get("id") if isinstance(b, dict) else ""))

    def _get_start(b: Any) -> int:
        return int(getattr(b, "start_frame", None) if getattr(b, "start_frame", None) is not None else (b.get("start_frame", 0) if isinstance(b, dict) else 0))

    def _get_end(b: Any) -> int:
        return int(getattr(b, "end_frame", None) if getattr(b, "end_frame", None) is not None else (b.get("end_frame", 0) if isinstance(b, dict) else 0))

    limit_beat = next((b for b in beats0 if _get_kind(b) == "threshold" or "limit" in _get_id(b)), None)
    grow_beat = next((b for b in beats1 if "grow" in _get_id(b) or _get_kind(b) == "number"), None)
    cross_beat = next((b for b in beats1 if "cross" in _get_id(b) or _get_kind(b) == "highlight"), None)
    resolve_beat = next((b for b in beats1 if "resolve" in _get_id(b) or _get_kind(b) == "resolve"), None)

    phase1_setup = 0
    phase2_limit = (
        max(0, _get_start(limit_beat) + round((_get_end(limit_beat) - _get_start(limit_beat)) * 0.35))
        if limit_beat
        else round(s0_dur * 0.12)
    )
    phase3_grow_start = s1_offset + _get_start(grow_beat) if grow_beat else s1_offset + round(s1_dur * 0.25)
    phase3_grow_end = s1_offset + _get_end(grow_beat) if grow_beat else s1_offset + round(s1_dur * 0.70)
    phase4_cross = s1_offset + _get_start(cross_beat) if cross_beat else phase3_grow_end + 3
    phase5_resolve = s1_offset + _get_start(resolve_beat) if resolve_beat else s1_offset + round(s1_dur * 0.82)

    limit_marker_visible = frame >= phase1_setup
    limit_value_visible = frame >= phase2_limit
    track_visible = True

    if frame < phase3_grow_start:
        base_progress = 0.0
    elif frame >= phase3_grow_end:
        base_progress = 1.0
    else:
        base_progress = (frame - phase3_grow_start) / max(1, (phase3_grow_end - phase3_grow_start))

    headline0 = str(s0.get("headline") or "THRESHOLD")
    headline1 = str(s1.get("headline") or headline0)

    show_conclusion = has_overflow and frame >= phase4_cross

    if show_conclusion:
        active_headline_words = resolve_progressive_copy(headline1, phase4_cross, phase5_resolve, frame, mode="word")
    else:
        active_headline_words = resolve_progressive_copy(headline0, phase1_setup, phase2_limit, frame, mode="word")

    consequence_visible = has_overflow and frame >= phase5_resolve

    return {
        "frame": frame,
        "limitMarkerVisible": limit_marker_visible,
        "limitValueVisible": limit_value_visible,
        "trackVisible": track_visible,
        "baseProgress": base_progress,
        "headlineSubject": " ".join(active_headline_words),
        "headline_words": active_headline_words,
        "showConclusion": show_conclusion,
        "consequenceVisible": consequence_visible,
    }
