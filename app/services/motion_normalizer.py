from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.models.motion import (
    AgeMarkerItem,
    AgeMarkerProps,
    AreaChartProps,
    BarChartItem,
    BarChartProps,
    BeforeAfterProps,
    CalloutProps,
    ComparisonItem,
    ComparisonProps,
    CounterProps,
    GaugeProps,
    LineChartPoint,
    LineChartProps,
    MotionSceneSpec,
    NumberProps,
    PieProps,
    PieSliceItem,
    RankedListItem,
    RankedListProps,
    SemanticDataIntent,
    StackedBarProps,
    StackedBarSegment,
    TextProps,
    ThresholdProps,
    TimelineItem,
    TimelineProps,
    VisualGrammar,
    WaterfallProps,
    WaterfallStep,
)
from app.models.project import ProjectSpec, VisualCue, VisualType
from app.services.data_visualization_director import DataVisualizationDirector
from app.services.kinetic_beat_deriver import derive_kinetic_beats
from app.services.motion_copy_extractor import extract_motion_copy, _truncate_motion_headline



def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        # Remove currency symbols ($ and others like €£¥), commas, spaces
        cleaned = re.sub(r"[\$, €£¥]", "", cleaned).strip()
        if not cleaned:
            return None

        # Check percentage
        if cleaned.endswith("%"):
            num_part = cleaned[:-1].strip()
            try:
                return float(num_part)
            except ValueError:
                return None

        # Check scale suffixes K, M, B (case-insensitive)
        multiplier = 1.0
        upper = cleaned.upper()
        if upper.endswith("B"):
            multiplier = 1_000_000_000.0
            num_part = cleaned[:-1].strip()
        elif upper.endswith("M"):
            multiplier = 1_000_000.0
            num_part = cleaned[:-1].strip()
        elif upper.endswith("K"):
            multiplier = 1_000.0
            num_part = cleaned[:-1].strip()
        else:
            num_part = cleaned

        try:
            return float(num_part) * multiplier
        except ValueError:
            return None
    return None


def _parse_int(val: Any) -> int | None:
    f = _parse_float(val)
    if f is not None:
        return int(round(f))
    return None


def _get_first_present(d: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def normalize_motion_spec(
    cue: VisualCue,
    project: ProjectSpec,
    timing_source: str | None = None,
    director: DataVisualizationDirector | None = None,
) -> MotionSceneSpec:
    """Deterministically normalize a VisualCue (DATA or TEXT) into a typed MotionSceneSpec.

    If a specialized DATA template is missing valid structured props, falls back safely to 'callout'
    without inventing or guessing factual numbers.
    """
    resolved_timing_source = timing_source or getattr(project, "timing_source", "estimated") or "estimated"
    fps = project.project.fps or 30
    width, height = project.project.aspect_ratio.to_resolution()

    start_time = float(cue.start or 0.0)
    end_time = float(cue.end or 0.0)
    start_frame = round(start_time * fps)
    end_frame = round(end_time * fps)
    duration_frames = max(1, end_frame - start_frame)

    raw_payload = cue.payload or {}

    if cue.visual_type == VisualType.text:
        headline = _truncate_motion_headline(str(raw_payload.get("headline") or cue.narration or "Summary").strip())
        subheadline = raw_payload.get("subheadline")
        if subheadline:
            subheadline = str(subheadline).strip()

        text_props = TextProps(
            headline=headline,
            subheadline=subheadline or None,
            style_variant=str(raw_payload.get("style_variant") or "bold"),
        )
        props_dict = text_props.model_dump(mode="json")
        return MotionSceneSpec(
            scene_id=cue.id,
            order=cue.order,
            visual_type="text",
            requested_template="text",
            rendered_template="text",
            fallback_reason=None,
            props=props_dict,
            start_time=start_time,
            end_time=end_time,
            start_frame=start_frame,
            end_frame=end_frame,
            duration_frames=duration_frames,
            fps=fps,
            width=width,
            height=height,
            visual_group_id=cue.visual_group_id,
            animation_plan=derive_kinetic_beats(
                narration=cue.narration or "",
                fps=fps,
                duration_frames=duration_frames,
                timing_source=resolved_timing_source,
                template="text",
                scene_id=cue.id,
                props=props_dict,
            ),
            layout_archetype="kinetic_statement",
            data_intent=SemanticDataIntent.takeaway,
            visual_grammar=VisualGrammar.kinetic_statement,
        )

    # VisualType.data
    requested_template = str(raw_payload.get("template") or "callout").strip().lower()
    headline = _truncate_motion_headline(str(raw_payload.get("headline") or "Key Data").strip())
    data = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else {}

    rendered_template = requested_template
    fallback_reason = None
    props_dict: dict[str, Any] = {}
    data_intent: SemanticDataIntent | None = None
    visual_grammar: VisualGrammar | None = None

    # If payload is generic callout/data or lacks structured fields, resolve via Director
    if (not data or requested_template in ("callout", "data", "")) and cue.narration:
        active_director = director or DataVisualizationDirector()
        spec = active_director.direct_visual_specification(
            narration=cue.narration,
            headline=headline,
            cue_payload=raw_payload,
            source_cue_id=cue.id,
        )
        requested_template = spec.grammar.value
        rendered_template = spec.grammar.value
        props_dict = spec.props
        layout_archetype = spec.variant
        data_intent = spec.intent
        visual_grammar = spec.grammar

    if requested_template == "number":
        val_raw = _get_first_present(data, ["value", "pct", "amount", "num"])
        if val_raw is not None and str(val_raw).strip() != "":
            num_val = _parse_float(val_raw)
            props_dict = NumberProps(
                headline=headline,
                value=str(val_raw).strip(),
                numeric_value=num_val,
                prefix=data.get("prefix"),
                suffix=data.get("suffix"),
                label=data.get("label") or data.get("caption"),
                subtext=data.get("subtext") or data.get("description"),
                eyebrow=None,
                context_label=None,
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.single_metric
            visual_grammar = VisualGrammar.metric
        else:
            rendered_template = "callout"
            fallback_reason = "Missing value for number template"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "counter":
        end_raw = _get_first_present(data, ["end_value", "value", "target", "num"])
        parsed_end = _parse_float(end_raw)
        if parsed_end is not None:
            start_raw = _get_first_present(data, ["start_value"])
            start_val = _parse_float(start_raw) if start_raw is not None else 0.0
            if start_val is None:
                start_val = 0.0
            decimals = int(data.get("decimals") if data.get("decimals") is not None else (1 if "." in str(end_raw) else 0))
            props_dict = CounterProps(
                headline=headline,
                start_value=start_val,
                end_value=parsed_end,
                display_value=str(end_raw).strip() if end_raw is not None else None,
                prefix=data.get("prefix"),
                suffix=data.get("suffix"),
                decimals=decimals,
                label=data.get("label") or data.get("caption"),
                eyebrow=None,
                context_label=None,
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.single_metric
            visual_grammar = VisualGrammar.metric
        else:
            rendered_template = "callout"
            fallback_reason = "Missing numeric end_value for counter template"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template in ("comparison", "breakdown"):
        raw_items = data.get("items") or data.get("options") or data.get("comparison")
        if not raw_items and isinstance(data.get("values"), list) and len(data["values"]) >= 2:
            raw_items = [
                {"label": f"Option {i + 1}" if not isinstance(v, dict) else v.get("label", f"Option {i+1}"),
                 "value": v if not isinstance(v, dict) else v.get("value", "")}
                for i, v in enumerate(data["values"])
            ]
        items: list[ComparisonItem] = []
        if isinstance(raw_items, list) and len(raw_items) >= 2:
            for it in raw_items:
                if isinstance(it, dict) and it.get("label") and it.get("value") is not None:
                    items.append(
                        ComparisonItem(
                            label=str(it["label"]).strip(),
                            value=str(it["value"]).strip(),
                            numeric_value=_parse_float(it.get("numeric_value") if it.get("numeric_value") is not None else it["value"]),
                            highlight=bool(it.get("highlight")),
                        )
                    )
        if len(items) >= 2:
            props_dict = ComparisonProps(
                headline=headline,
                items=items,
                subtext=data.get("subtext"),
            ).model_dump(mode="json")
            if requested_template == "breakdown":
                data_intent = SemanticDataIntent.breakdown
                visual_grammar = VisualGrammar.breakdown
                rendered_template = "breakdown"
            else:
                data_intent = SemanticDataIntent.category_comparison
                visual_grammar = VisualGrammar.comparison
                rendered_template = "comparison"
        else:
            rendered_template = "callout"
            fallback_reason = f"{requested_template.capitalize()} template requires at least 2 valid items"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "timeline":
        raw_milestones = data.get("milestones") or data.get("events") or data.get("timeline")
        if not raw_milestones and isinstance(data.get("values"), list) and len(data["values"]) >= 2:
            raw_milestones = [
                {"time_label": f"Step {i + 1}", "title": str(v)}
                for i, v in enumerate(data["values"])
            ]
        milestones: list[TimelineItem] = []
        if isinstance(raw_milestones, list) and len(raw_milestones) >= 2:
            for m in raw_milestones:
                if isinstance(m, dict) and (m.get("time_label") or m.get("time")) and (m.get("title") or m.get("label")):
                    milestones.append(
                        TimelineItem(
                            time_label=str(m.get("time_label") or m.get("time")).strip(),
                            title=str(m.get("title") or m.get("label")).strip(),
                            description=m.get("description"),
                            is_active=bool(m.get("is_active")),
                        )
                    )
        if len(milestones) >= 2:
            props_dict = TimelineProps(
                headline=headline,
                milestones=milestones,
                highlight_index=data.get("highlight_index"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.sequence
            visual_grammar = VisualGrammar.timeline
        else:
            rendered_template = "callout"
            fallback_reason = "Timeline template requires at least 2 valid milestones"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "bar_chart":
        raw_items = data.get("items") or data.get("bars") or data.get("series")
        if not raw_items and isinstance(data.get("values"), list) and len(data["values"]) >= 2:
            raw_items = [
                {"label": f"Item {i + 1}" if not isinstance(v, dict) else v.get("label", f"Item {i+1}"),
                 "value": v if not isinstance(v, dict) else v.get("value", 0)}
                for i, v in enumerate(data["values"])
            ]
        bar_items: list[BarChartItem] = []
        if isinstance(raw_items, list) and len(raw_items) >= 2:
            for it in raw_items:
                if isinstance(it, dict) and it.get("label") and it.get("value") is not None:
                    val = _parse_float(it["value"])
                    if val is not None:
                        bar_items.append(
                            BarChartItem(
                                label=str(it["label"]).strip(),
                                value=val,
                                display_value=str(it.get("display_value") if it.get("display_value") is not None else it["value"]).strip(),
                                color=it.get("color"),
                            )
                        )
        if len(bar_items) >= 2:
            baseline_val = _parse_float(data.get("baseline"))
            props_dict = BarChartProps(
                headline=headline,
                items=bar_items,
                unit=data.get("unit"),
                baseline=baseline_val if baseline_val is not None else 0.0,
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.category_comparison
            visual_grammar = VisualGrammar.bar
        else:
            rendered_template = "callout"
            fallback_reason = "Bar chart requires at least 2 valid labeled numeric items"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "line_chart":
        raw_points = data.get("points") or data.get("data_points") or data.get("trend")
        points: list[LineChartPoint] = []
        if isinstance(raw_points, list) and len(raw_points) >= 2:
            for p in raw_points:
                if isinstance(p, dict) and (p.get("x_label") or p.get("x")) and (p.get("y_value") is not None or p.get("y") is not None):
                    y_raw = p.get("y_value") if p.get("y_value") is not None else p.get("y")
                    y_val = _parse_float(y_raw)
                    if y_val is not None:
                        points.append(
                            LineChartPoint(
                                x_label=str(p.get("x_label") or p.get("x")).strip(),
                                y_value=y_val,
                                display_value=str(p.get("display_value") if p.get("display_value") is not None else y_val).strip(),
                            )
                        )
        if len(points) >= 2:
            props_dict = LineChartProps(
                headline=headline,
                points=points,
                unit=data.get("unit"),
                show_area=bool(data.get("show_area", True)),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.trend_over_time
            visual_grammar = VisualGrammar.line
        else:
            rendered_template = "callout"
            fallback_reason = "Line chart requires at least 2 valid numeric points"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "threshold":
        curr = _get_first_present(data, ["current_value", "value", "current"])
        thresh = _get_first_present(data, ["threshold_value", "threshold", "limit", "target"])
        curr_val = _parse_float(curr)
        thresh_val = _parse_float(thresh)
        if curr_val is not None and thresh_val is not None:
            props_dict = ThresholdProps(
                headline=headline,
                current_value=curr_val,
                current_display=str(data.get("current_display") if data.get("current_display") is not None else curr).strip(),
                threshold_value=thresh_val,
                threshold_display=str(data.get("threshold_display") if data.get("threshold_display") is not None else thresh).strip(),
                threshold_label=str(data.get("threshold_label") or "Threshold").strip(),
                subtext=data.get("subtext"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.threshold
            visual_grammar = VisualGrammar.threshold
        else:
            rendered_template = "callout"
            fallback_reason = "Threshold template requires numeric current_value and threshold_value"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "age_marker":
        raw_markers = data.get("markers") or data.get("ages")
        markers: list[AgeMarkerItem] = []
        if isinstance(raw_markers, list) and len(raw_markers) >= 1:
            for m in raw_markers:
                if isinstance(m, dict) and m.get("age") is not None:
                    age_val = _parse_int(m["age"])
                    if age_val is not None:
                        markers.append(
                            AgeMarkerItem(
                                age=age_val,
                                label=m.get("label"),
                                highlight=bool(m.get("highlight")),
                            )
                        )
                elif isinstance(m, (int, str)):
                    age_val = _parse_int(m)
                    if age_val is not None:
                        markers.append(AgeMarkerItem(age=age_val))
        elif data.get("age") is not None:
            age_val = _parse_int(data["age"])
            if age_val is not None:
                markers.append(AgeMarkerItem(age=age_val, label=data.get("label"), highlight=True))

        if len(markers) >= 1:
            props_dict = AgeMarkerProps(
                headline=headline,
                markers=markers,
                subtext=data.get("subtext"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.sequence
            visual_grammar = VisualGrammar.timeline
        else:
            rendered_template = "callout"
            fallback_reason = "Age marker template requires at least 1 valid age value"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template in ("pie", "donut"):
        raw_items = data.get("items") or data.get("slices") or data.get("segments")
        pie_items: list[PieSliceItem] = []
        if isinstance(raw_items, list) and len(raw_items) >= 2:
            for it in raw_items:
                if isinstance(it, dict) and it.get("label") and it.get("value") is not None:
                    val = _parse_float(it["value"])
                    if val is not None:
                        pie_items.append(
                            PieSliceItem(
                                label=str(it["label"]).strip(),
                                value=val,
                                display_value=str(it.get("display_value") if it.get("display_value") is not None else it["value"]).strip(),
                                percentage=_parse_float(it.get("percentage")),
                                highlight=bool(it.get("highlight")),
                                color=it.get("color"),
                            )
                        )
        if len(pie_items) >= 2:
            props_dict = PieProps(
                headline=headline,
                items=pie_items,
                total=_parse_float(data.get("total")),
                focus_label=data.get("focus_label"),
                subtext=data.get("subtext"),
                variant=str(data.get("variant") or "donut_center_stat"),
                eyebrow=data.get("eyebrow"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.part_to_whole
            visual_grammar = VisualGrammar.pie if requested_template == "pie" else VisualGrammar.donut
        else:
            rendered_template = "callout"
            fallback_reason = "Pie template requires at least 2 valid slices"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "gauge":
        curr = _get_first_present(data, ["current_value", "value", "current", "progress"])
        curr_val = _parse_float(curr)
        raw_display = str(data.get("display_value") or curr or "").strip()
        unit_val = str(data.get("unit") or "").strip()
        is_pct = "%" in raw_display or unit_val == "%" or "%" in str(curr or "")
        explicit_max = _parse_float(data.get("max_value"))

        if curr_val is not None and (is_pct or explicit_max is not None):
            max_val = explicit_max if explicit_max is not None else 100.0
            min_val = _parse_float(data.get("min_value")) or 0.0
            props_dict = GaugeProps(
                headline=headline,
                current_value=curr_val,
                max_value=max_val,
                min_value=min_val,
                display_value=raw_display or f"{int(curr_val)}%",
                unit="%" if is_pct else (unit_val or None),
                label=data.get("label"),
                subtext=data.get("subtext"),
                variant=str(data.get("variant") or "radial_gauge"),
                eyebrow=data.get("eyebrow"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.progress
            visual_grammar = VisualGrammar.gauge
        elif curr_val is not None:
            # Unbounded scalar like "$6,000" without max bound -> safe fallback to number
            rendered_template = "number"
            props_dict = NumberProps(
                headline=headline,
                value=raw_display or str(curr),
                numeric_value=curr_val,
                prefix=data.get("prefix"),
                suffix=data.get("suffix"),
                label=data.get("label"),
                subtext=data.get("subtext"),
            ).model_dump(mode="json")
            fallback_reason = "Gauge requires percentage or explicit maximum bound"
            data_intent = SemanticDataIntent.single_metric
            visual_grammar = VisualGrammar.metric
        else:
            rendered_template = "callout"
            fallback_reason = "Gauge template requires numeric current_value"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "waterfall":
        raw_steps = data.get("steps")
        steps: list[WaterfallStep] = []
        if isinstance(raw_steps, list) and len(raw_steps) >= 1:
            for s in raw_steps:
                if isinstance(s, dict) and s.get("label") and s.get("delta") is not None:
                    d_val = _parse_float(s["delta"])
                    if d_val is not None:
                        steps.append(
                            WaterfallStep(
                                label=str(s["label"]).strip(),
                                delta=d_val,
                                display_value=str(s.get("display_value") if s.get("display_value") is not None else d_val).strip(),
                                is_total=bool(s.get("is_total")),
                            )
                        )
        start_val = _parse_float(data.get("start_value"))
        end_val = _parse_float(data.get("end_value"))
        if start_val is not None and end_val is not None and len(steps) >= 1:
            props_dict = WaterfallProps(
                headline=headline,
                start_value=start_val,
                start_label=str(data.get("start_label") or "Starting").strip(),
                steps=steps,
                end_value=end_val,
                end_label=str(data.get("end_label") or "Final").strip(),
                unit=data.get("unit"),
                variant=str(data.get("variant") or "waterfall_steps"),
                eyebrow=data.get("eyebrow"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.positive_negative_change
            visual_grammar = VisualGrammar.waterfall
        else:
            rendered_template = "callout"
            fallback_reason = "Waterfall template requires valid start_value, end_value, and steps"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "ranked_list":
        raw_items = data.get("items") or data.get("rankings")
        r_items: list[RankedListItem] = []
        if isinstance(raw_items, list) and len(raw_items) >= 2:
            for idx, it in enumerate(raw_items):
                if isinstance(it, dict) and it.get("label"):
                    r_items.append(
                        RankedListItem(
                            rank=it.get("rank", idx + 1),
                            label=str(it["label"]).strip(),
                            value=_parse_float(it.get("value")),
                            display_value=str(it.get("display_value") or it.get("value") or "").strip() or None,
                            highlight=bool(it.get("highlight")),
                        )
                    )
        if len(r_items) >= 2:
            props_dict = RankedListProps(
                headline=headline,
                items=r_items,
                subtext=data.get("subtext"),
                variant=str(data.get("variant") or "ranked_horizontal_bars"),
                eyebrow=data.get("eyebrow"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.ranked_categories
            visual_grammar = VisualGrammar.ranked_list
        else:
            rendered_template = "callout"
            fallback_reason = "Ranked list template requires at least 2 valid ranked items"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template in ("area", "area_chart"):
        raw_points = data.get("points") or data.get("data_points")
        points: list[LineChartPoint] = []
        if isinstance(raw_points, list) and len(raw_points) >= 2:
            for p in raw_points:
                if isinstance(p, dict) and (p.get("x_label") or p.get("x")) and (p.get("y_value") is not None or p.get("y") is not None):
                    y_raw = p.get("y_value") if p.get("y_value") is not None else p.get("y")
                    y_val = _parse_float(y_raw)
                    if y_val is not None:
                        points.append(
                            LineChartPoint(
                                x_label=str(p.get("x_label") or p.get("x")).strip(),
                                y_value=y_val,
                                display_value=str(p.get("display_value") if p.get("display_value") is not None else y_val).strip(),
                            )
                        )
        if len(points) >= 2:
            props_dict = AreaChartProps(
                headline=headline,
                points=points,
                unit=data.get("unit"),
                variant=str(data.get("variant") or "area_trend"),
                eyebrow=data.get("eyebrow"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.trend_over_time
            visual_grammar = VisualGrammar.area
        else:
            rendered_template = "callout"
            fallback_reason = "Area chart requires at least 2 valid numeric points"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "before_after":
        b_val = data.get("before_value") or data.get("before")
        a_val = data.get("after_value") or data.get("after")
        if b_val and a_val:
            props_dict = BeforeAfterProps(
                headline=headline,
                before_label=str(data.get("before_label") or "Before").strip(),
                before_value=str(b_val).strip(),
                before_numeric=_parse_float(data.get("before_numeric") or b_val),
                after_label=str(data.get("after_label") or "After").strip(),
                after_value=str(a_val).strip(),
                after_numeric=_parse_float(data.get("after_numeric") or a_val),
                delta_display=data.get("delta_display"),
                subtext=data.get("subtext"),
                variant=str(data.get("variant") or "split_screen"),
                eyebrow=data.get("eyebrow"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.before_after
            visual_grammar = VisualGrammar.comparison
        else:
            rendered_template = "callout"
            fallback_reason = "Before/After template requires before_value and after_value"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "stacked_bar":
        raw_segs = data.get("segments") or data.get("parts")
        segs: list[StackedBarSegment] = []
        if isinstance(raw_segs, list) and len(raw_segs) >= 2:
            for s in raw_segs:
                if isinstance(s, dict) and s.get("label") and s.get("value") is not None:
                    val = _parse_float(s["value"])
                    if val is not None:
                        segs.append(
                            StackedBarSegment(
                                label=str(s["label"]).strip(),
                                value=val,
                                display_value=str(s.get("display_value") if s.get("display_value") is not None else val).strip(),
                                highlight=bool(s.get("highlight")),
                                color=s.get("color"),
                            )
                        )
        total_val = _parse_float(data.get("total"))
        # Strict stacked bar safety: require explicit total and matching sum
        if len(segs) >= 2 and total_val is not None and abs(sum(s.value for s in segs) - total_val) <= 2.0:
            props_dict = StackedBarProps(
                headline=headline,
                total=total_val,
                total_display=str(data.get("total_display") if data.get("total_display") is not None else total_val).strip(),
                segments=segs,
                variant=str(data.get("variant") or "stacked_bar_reveal"),
                eyebrow=data.get("eyebrow"),
            ).model_dump(mode="json")
            data_intent = SemanticDataIntent.composition_over_time
            visual_grammar = VisualGrammar.stacked_bar
        elif len(segs) >= 2:
            rendered_template = "bar_chart"
            props_dict = BarChartProps(
                headline=headline,
                items=[BarChartItem(label=s.label, value=s.value, display_value=s.display_value, color=s.color) for s in segs],
                unit=data.get("unit"),
            ).model_dump(mode="json")
            fallback_reason = "Stacked bar without grounded total matches fell back to ordinary bar chart"
            data_intent = SemanticDataIntent.category_comparison
            visual_grammar = VisualGrammar.bar
        else:
            rendered_template = "callout"
            fallback_reason = "Stacked bar requires total and at least 2 valid segments"
            data_intent = SemanticDataIntent.takeaway
            visual_grammar = VisualGrammar.kinetic_statement

    elif requested_template == "callout":
        emphasis = _get_first_present(data, ["emphasis", "highlight", "value", "amount", "pct"])
        props_dict = CalloutProps(
            headline=headline,
            emphasis=str(emphasis).strip() if emphasis is not None else None,
            subtext=str(data.get("subtext") or data.get("description") or "").strip() or None,
        ).model_dump(mode="json")
        data_intent = SemanticDataIntent.takeaway
        visual_grammar = VisualGrammar.kinetic_statement

    else:
        rendered_template = "callout"
        fallback_reason = f"Unknown requested template: {requested_template}"

    if rendered_template == "callout" and not props_dict:
        emphasis = _get_first_present(data, ["emphasis", "highlight", "value", "amount", "pct"])
        props_dict = CalloutProps(
            headline=headline,
            emphasis=str(emphasis).strip() if emphasis is not None else None,
            subtext=str(data.get("subtext") or data.get("description") or "").strip() or None,
        ).model_dump(mode="json")

    mc = extract_motion_copy(cue.narration or "", raw_payload, rendered_template)
    if rendered_template in ("number", "counter") and props_dict:
        props_dict["eyebrow"] = mc.eyebrow
        props_dict["context_label"] = mc.label

    layout_archetype = raw_payload.get("layout_archetype") or props_dict.get("variant")
    if not layout_archetype:
        if rendered_template in ("number", "counter"):
            layout_archetype = "metric_hero"
        elif rendered_template in ("pie", "donut"):
            layout_archetype = "donut_center_stat"
        elif rendered_template == "gauge":
            layout_archetype = "radial_gauge"
        elif rendered_template == "waterfall":
            layout_archetype = "waterfall_steps"
        elif rendered_template == "ranked_list":
            layout_archetype = "ranked_horizontal_bars"
        elif rendered_template in ("area", "area_chart"):
            layout_archetype = "area_trend"
        elif rendered_template == "before_after":
            layout_archetype = "split_screen"
        elif rendered_template == "stacked_bar":
            layout_archetype = "stacked_bar_reveal"
        elif rendered_template == "comparison":
            raw_items = props_dict.get("items", [])
            if len(raw_items) == 3:
                v0 = raw_items[0].get("numeric_value") if isinstance(raw_items[0], dict) else None
                v1 = raw_items[1].get("numeric_value") if isinstance(raw_items[1], dict) else None
                v2 = raw_items[2].get("numeric_value") if isinstance(raw_items[2], dict) else None
                if v0 is not None and v1 is not None and v2 is not None and v0 > 0 and abs(v0 - (v1 + v2)) <= 1.0:
                    layout_archetype = "stacked_breakdown"
                else:
                    layout_archetype = "split_compare"
            else:
                layout_archetype = "split_compare"
        elif rendered_template == "breakdown":
            layout_archetype = "stacked_breakdown"
        elif rendered_template == "bar_chart":
            layout_archetype = "bar_chart_v2"
        elif rendered_template == "line_chart":
            layout_archetype = "line_chart_v2"
        elif rendered_template == "threshold":
            layout_archetype = "threshold_v2"
        elif rendered_template == "timeline":
            layout_archetype = "timeline_v2"
        elif rendered_template == "callout":
            layout_archetype = "statement_reveal"
        else:
            layout_archetype = "default"

    if cue.visual_group_id and "cost_breakdown" in str(cue.visual_group_id).lower():
        layout_archetype = "stacked_breakdown"

    props_dict["layout_archetype"] = layout_archetype

    return MotionSceneSpec(
        scene_id=cue.id,
        order=cue.order,
        visual_type="data",
        requested_template=requested_template,
        rendered_template=rendered_template,
        fallback_reason=fallback_reason,
        props=props_dict,
        start_time=start_time,
        end_time=end_time,
        start_frame=start_frame,
        end_frame=end_frame,
        duration_frames=duration_frames,
        fps=fps,
        width=width,
        height=height,
        visual_group_id=cue.visual_group_id,
        animation_plan=derive_kinetic_beats(
            narration=cue.narration or "",
            fps=fps,
            duration_frames=duration_frames,
            timing_source=resolved_timing_source,
            template=rendered_template,
            scene_id=cue.id,
            props=props_dict,
        ),
        layout_archetype=layout_archetype,
        motion_copy=mc.__dict__,
        data_intent=data_intent or SemanticDataIntent.single_metric,
        visual_grammar=visual_grammar or VisualGrammar.metric,
    )
