from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.models.motion import (
    AgeMarkerItem,
    AgeMarkerProps,
    BarChartItem,
    BarChartProps,
    CalloutProps,
    ComparisonItem,
    ComparisonProps,
    CounterProps,
    LineChartPoint,
    LineChartProps,
    MotionSceneSpec,
    NumberProps,
    TextProps,
    ThresholdProps,
    TimelineItem,
    TimelineProps,
)
from app.models.project import ProjectSpec, VisualCue, VisualType
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
        )

    # VisualType.data
    requested_template = str(raw_payload.get("template") or "callout").strip().lower()
    headline = _truncate_motion_headline(str(raw_payload.get("headline") or "Key Data").strip())
    data = raw_payload.get("data") if isinstance(raw_payload.get("data"), dict) else {}

    rendered_template = requested_template
    fallback_reason = None
    props_dict: dict[str, Any] = {}

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
        else:
            rendered_template = "callout"
            fallback_reason = "Missing value for number template"

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
        else:
            rendered_template = "callout"
            fallback_reason = "Missing numeric end_value for counter template"

    elif requested_template == "comparison":
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
        else:
            rendered_template = "callout"
            fallback_reason = "Comparison template requires at least 2 valid comparison items"

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
        else:
            rendered_template = "callout"
            fallback_reason = "Timeline template requires at least 2 valid milestones"

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
        else:
            rendered_template = "callout"
            fallback_reason = "Bar chart requires at least 2 valid labeled numeric items"

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
        else:
            rendered_template = "callout"
            fallback_reason = "Line chart requires at least 2 valid numeric points"

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
        else:
            rendered_template = "callout"
            fallback_reason = "Threshold template requires numeric current_value and threshold_value"

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
        else:
            rendered_template = "callout"
            fallback_reason = "Age marker template requires at least 1 valid age value"

    elif requested_template == "callout":
        emphasis = _get_first_present(data, ["emphasis", "highlight", "value", "amount", "pct"])
        props_dict = CalloutProps(
            headline=headline,
            emphasis=str(emphasis).strip() if emphasis is not None else None,
            subtext=str(data.get("subtext") or data.get("description") or "").strip() or None,
        ).model_dump(mode="json")

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

    layout_archetype = "default"
    if rendered_template in ("number", "counter"):
        layout_archetype = "metric_hero"
    elif rendered_template == "comparison":
        raw_items = props_dict.get("items", [])
        if len(raw_items) == 3:
            layout_archetype = "stacked_breakdown"
        elif len(raw_items) == 2:
            # Check if it's a cost breakdown pair or comparison
            narr_lower = (cue.narration or "").lower()
            if any(k in narr_lower for k in ("breakdown", "deductible", "insurance covers", "repair cost")):
                layout_archetype = "stacked_breakdown"
            else:
                layout_archetype = "split_compare"
        else:
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

    if cue.visual_group_id and any(k in (cue.narration or "").lower() for k in ("repair", "deductible", "insurance", "breakdown")):
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
    )
