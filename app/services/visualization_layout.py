"""Deterministic Editorial Visualization Layout Engine (G18).

Provides Python layout geometry calculations mirroring remotion/src/layout/
for strict bounding box safety verification, collision detection, and testability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ContentZone:
    x: int
    y: int
    width: int
    height: int
    right: int
    bottom: int


@dataclass(frozen=True)
class SafeAreaConfig:
    width: int
    height: int
    left: int
    top: int
    right: int
    bottom: int
    content_width: int
    content_height: int
    is_portrait: bool
    aspect_ratio: str
    title_zone: ContentZone
    chart_zone: ContentZone
    footer_zone: ContentZone


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    width: float
    height: float
    left: float
    right: float
    top: float
    bottom: float


def get_safe_area(width: int, height: int) -> SafeAreaConfig:
    """Computes canonical safe area margins and zone partitions."""
    is_portrait = height > width
    is_square = abs(width - height) < 2
    aspect_ratio = "9:16" if is_portrait else ("1:1" if is_square else "16:9")

    margin_x = round(width * 0.06) if is_portrait else round(width * 0.055)
    margin_y = round(height * 0.065) if is_portrait else round(height * 0.06)

    left = margin_x
    top = margin_y
    right = width - margin_x
    bottom = height - margin_y
    content_width = right - left
    content_height = bottom - top

    title_h = round(content_height * 0.22) if is_portrait else round(content_height * 0.20)
    title_zone = ContentZone(
        x=left,
        y=top,
        width=content_width,
        height=title_h,
        right=right,
        bottom=top + title_h,
    )

    footer_h = round(content_height * 0.15) if is_portrait else round(content_height * 0.12)
    footer_zone = ContentZone(
        x=left,
        y=bottom - footer_h,
        width=content_width,
        height=footer_h,
        right=right,
        bottom=bottom,
    )

    chart_y = top + title_h + round(content_height * 0.02)
    chart_h = footer_zone.y - chart_y - round(content_height * 0.02)
    chart_zone = ContentZone(
        x=left,
        y=chart_y,
        width=content_width,
        height=max(100, chart_h),
        right=right,
        bottom=chart_y + max(100, chart_h),
    )

    return SafeAreaConfig(
        width=width,
        height=height,
        left=left,
        top=top,
        right=right,
        bottom=bottom,
        content_width=content_width,
        content_height=content_height,
        is_portrait=is_portrait,
        aspect_ratio=aspect_ratio,
        title_zone=title_zone,
        chart_zone=chart_zone,
        footer_zone=footer_zone,
    )


CATEGORICAL_PALETTE = [
    "#3B82F6",  # 0: Vibrant Blue
    "#2DD4BF",  # 1: Crisp Teal
    "#FB923C",  # 2: Warm Orange
    "#A78BFA",  # 3: Soft Purple
    "#34D399",  # 4: Emerald Green
    "#FBBF24",  # 5: Golden Amber
    "#F472B6",  # 6: Rose Pink
    "#38BDF8",  # 7: Sky Blue
]

STANDARD_LABEL_COLOR_MAP: dict[str, str] = {
    "PREMIUM": "#3B82F6",
    "STANDARD": "#2DD4BF",
    "BASIC": "#FB923C",
    "ENTERPRISE": "#A78BFA",
    "PRO": "#3B82F6",
    "FREE": "#94A3B8",
    "COMPREHENSIVE": "#3B82F6",
    "COLLISION ONLY": "#2DD4BF",
    "COLLISION": "#2DD4BF",
    "LIABILITY": "#A78BFA",
    "UNINSURED": "#FB923C",
    "PLAN A": "#3B82F6",
    "PLAN B": "#2DD4BF",
    "PLAN C": "#FB923C",
    "PLAN D": "#A78BFA",
}

PALETTE_DISTRIBUTION_MAP: dict[int, list[int]] = {
    2: [0, 2],
    3: [0, 1, 2],
    4: [0, 1, 2, 3],
    5: [0, 1, 5, 3, 4],
}


def resolve_category_color(
    label: str | None = None,
    index: int = 0,
    total_categories: int = 3,
    semantic_role: str | None = None,
) -> str:
    """Deterministically resolves categorical and semantic colors."""
    if semantic_role == "positive":
        return "#10B981"
    if semantic_role == "negative":
        return "#EF4444"
    if semantic_role == "start":
        return "#3B82F6"
    if semantic_role == "final":
        return "#8B5CF6"

    if label:
        norm = label.strip().upper()
        if norm in STANDARD_LABEL_COLOR_MAP:
            return STANDARD_LABEL_COLOR_MAP[norm]

    dist = PALETTE_DISTRIBUTION_MAP.get(total_categories)
    if dist and index < len(dist):
        return CATEGORICAL_PALETTE[dist[index]]

    return CATEGORICAL_PALETTE[index % len(CATEGORICAL_PALETTE)]


@dataclass
class TimelineMilestoneLayout:
    index: int
    node_x: float
    node_y: float
    global_node_x: float
    global_node_y: float
    card_bounds: BoundingBox


@dataclass
class TimelineLayoutGeometry:
    safe_area: SafeAreaConfig
    title_bounds: BoundingBox
    track_bounds: BoundingBox
    milestones: list[TimelineMilestoneLayout]


def compute_timeline_layout(
    width: int,
    height: int,
    headline: str,
    milestones: list[dict[str, Any]],
) -> TimelineLayoutGeometry:
    """Computes exact global bounds for Timeline components."""
    safe = get_safe_area(width, height)
    is_portrait = height > width
    num_items = max(1, len(milestones))

    title_bounds = BoundingBox(
        x=safe.title_zone.x,
        y=safe.title_zone.y,
        width=safe.title_zone.width,
        height=safe.title_zone.height,
        left=safe.title_zone.x,
        right=safe.title_zone.right,
        top=safe.title_zone.y,
        bottom=safe.title_zone.bottom,
    )

    track_w = 6 if is_portrait else min(int(safe.chart_zone.width * 0.90), 1080)
    track_h = min(int(safe.chart_zone.height * 0.80), 800) if is_portrait else 6
    track_left = (
        safe.chart_zone.x + round(safe.chart_zone.width * 0.18)
        if is_portrait
        else safe.chart_zone.x + (safe.chart_zone.width - track_w) // 2
    )
    track_top = (
        safe.chart_zone.y + round(safe.chart_zone.height * 0.08)
        if is_portrait
        else safe.chart_zone.y + round(safe.chart_zone.height * 0.42)
    )

    track_bounds = BoundingBox(
        x=track_left,
        y=track_top,
        width=track_w,
        height=track_h,
        left=track_left,
        right=track_left + track_w,
        top=track_top,
        bottom=track_top + track_h,
    )

    slot_w = track_w if is_portrait else track_w / num_items
    slot_h = track_h / num_items if is_portrait else track_h

    ms_results: list[TimelineMilestoneLayout] = []
    for idx, m in enumerate(milestones):
        node_x = 3.0 if is_portrait else (idx * slot_w) + (slot_w / 2.0)
        node_y = (idx * slot_h) + (slot_h / 2.0) if is_portrait else 3.0
        global_node_x = track_left + node_x
        global_node_y = track_top + node_y

        card_width = (
            safe.chart_zone.width * 0.65
            if is_portrait
            else min(slot_w - 20.0, 320.0)
        )
        card_height = 80.0

        card_left = 32.0 if is_portrait else -card_width / 2.0
        card_top = -card_height / 2.0 if is_portrait else 28.0

        global_x = global_node_x + card_left
        global_y = global_node_y + card_top

        # Safe area clamping
        if global_x < safe.left:
            shift = safe.left - global_x
            global_x = safe.left
            card_left += shift
        elif global_x + card_width > safe.right:
            shift = (global_x + card_width) - safe.right
            global_x = safe.right - card_width
            card_left -= shift

        if global_y < safe.top:
            shift = safe.top - global_y
            global_y = safe.top
            card_top += shift
        elif global_y + card_height > safe.bottom:
            shift = (global_y + card_height) - safe.bottom
            global_y = safe.bottom - card_height
            card_top -= shift

        card_bounds = BoundingBox(
            x=global_x,
            y=global_y,
            width=card_width,
            height=card_height,
            left=global_x,
            right=global_x + card_width,
            top=global_y,
            bottom=global_y + card_height,
        )

        ms_results.append(
            TimelineMilestoneLayout(
                index=idx,
                node_x=node_x,
                node_y=node_y,
                global_node_x=global_node_x,
                global_node_y=global_node_y,
                card_bounds=card_bounds,
            )
        )

    return TimelineLayoutGeometry(
        safe_area=safe,
        title_bounds=title_bounds,
        track_bounds=track_bounds,
        milestones=ms_results,
    )


@dataclass
class WaterfallColumnLayout:
    type: Literal["start", "step", "final"]
    index: int
    label: str
    value: float
    bar_bounds: BoundingBox
    value_bounds: BoundingBox
    label_bounds: BoundingBox
    global_bounds: BoundingBox


@dataclass
class WaterfallLayoutGeometry:
    safe_area: SafeAreaConfig
    title_bounds: BoundingBox
    chart_container_bounds: BoundingBox
    columns: list[WaterfallColumnLayout]


def compute_waterfall_layout(
    width: int,
    height: int,
    headline: str,
    start_value: float,
    start_label: str,
    steps: list[dict[str, Any]],
    end_value: float,
    end_label: str,
) -> WaterfallLayoutGeometry:
    """Computes exact global bounds for Waterfall visualization columns, values, and labels."""
    safe = get_safe_area(width, height)
    is_portrait = height > width

    current_running = start_value
    computed_steps = []
    for s in steps:
        prev = current_running
        delta = float(s.get("delta", 0))
        current_running += delta
        computed_steps.append({"prev": prev, "delta": delta, "new": current_running, "label": s.get("label", "")})

    all_levels = [0.0, start_value, end_value] + [cs["prev"] for cs in computed_steps] + [cs["new"] for cs in computed_steps]
    max_level = max(all_levels + [10.0])
    min_level = min(all_levels + [0.0])
    range_val = max(1.0, max_level - min_level)

    total_cols = 2 + len(computed_steps)

    chart_w = safe.chart_zone.width * 0.94 if is_portrait else min(int(safe.chart_zone.width * 0.88), 960)
    chart_h = safe.chart_zone.height * 0.62 if is_portrait else safe.chart_zone.height * 0.68
    chart_left = safe.chart_zone.x + (safe.chart_zone.width - chart_w) // 2
    chart_top = safe.chart_zone.y + round(safe.chart_zone.height * 0.05)

    chart_container = BoundingBox(
        x=chart_left,
        y=chart_top,
        width=chart_w,
        height=chart_h,
        left=chart_left,
        right=chart_left + chart_w,
        top=chart_top,
        bottom=chart_top + chart_h,
    )

    plot_padding_x = 20 if is_portrait else 36
    plot_padding_bottom = 48 if is_portrait else 58
    plot_padding_top = 32 if is_portrait else 40
    plot_w = chart_w - plot_padding_x * 2
    plot_h = chart_h - plot_padding_bottom - plot_padding_top

    col_w = min(plot_w / (total_cols * 1.35), 60.0 if is_portrait else 100.0)
    col_gap = (plot_w - total_cols * col_w) / max(1, total_cols - 1)

    def level_to_y(level: float) -> float:
        return ((level - min_level) / range_val) * plot_h

    columns: list[WaterfallColumnLayout] = []

    # Start column
    col_left = chart_left + plot_padding_x
    bar_h = level_to_y(start_value)
    bar_top = chart_top + chart_h - plot_padding_bottom - bar_h
    bar_bottom = chart_top + chart_h - plot_padding_bottom

    val_w = col_w * 1.4
    val_h = 20.0
    val_x = col_left + (col_w - val_w) / 2
    val_y = bar_top - val_h - 4

    lbl_w = max(col_w * 1.2, 100.0)
    lbl_h = 24.0
    lbl_x = col_left + (col_w - lbl_w) / 2
    lbl_y = bar_bottom + 8

    bar_bb = BoundingBox(x=col_left, y=bar_top, width=col_w, height=bar_h, left=col_left, right=col_left + col_w, top=bar_top, bottom=bar_bottom)
    val_bb = BoundingBox(x=val_x, y=val_y, width=val_w, height=val_h, left=val_x, right=val_x + val_w, top=val_y, bottom=val_y + val_h)
    lbl_bb = BoundingBox(x=lbl_x, y=lbl_y, width=lbl_w, height=lbl_h, left=lbl_x, right=lbl_x + lbl_w, top=lbl_y, bottom=lbl_y + lbl_h)
    glob_bb = BoundingBox(
        x=min(col_left, val_x, lbl_x),
        y=val_y,
        width=max(col_w, val_w, lbl_w),
        height=(lbl_y + lbl_h) - val_y,
        left=min(col_left, val_x, lbl_x),
        right=max(col_left + col_w, val_x + val_w, lbl_x + lbl_w),
        top=val_y,
        bottom=lbl_y + lbl_h,
    )

    columns.append(WaterfallColumnLayout(
        type="start",
        index=0,
        label=start_label,
        value=start_value,
        bar_bounds=bar_bb,
        value_bounds=val_bb,
        label_bounds=lbl_bb,
        global_bounds=glob_bb,
    ))

    # Delta steps
    for idx, cs in enumerate(computed_steps):
        col_index = idx + 1
        col_left = chart_left + plot_padding_x + col_index * (col_w + col_gap)
        lower_val = min(cs["prev"], cs["new"])
        higher_val = max(cs["prev"], cs["new"])
        delta_h = (abs(cs["delta"]) / range_val) * plot_h
        bar_top = chart_top + chart_h - plot_padding_bottom - level_to_y(higher_val)
        bar_bottom = chart_top + chart_h - plot_padding_bottom - level_to_y(lower_val)

        val_w = col_w * 1.4
        val_h = 20.0
        val_x = col_left + (col_w - val_w) / 2
        val_y = bar_top - val_h - 4

        lbl_w = max(col_w * 1.25, 90.0)
        lbl_h = 24.0
        lbl_x = col_left + (col_w - lbl_w) / 2
        lbl_y = chart_top + chart_h - plot_padding_bottom + 8

        bar_bb = BoundingBox(x=col_left, y=bar_top, width=col_w, height=delta_h, left=col_left, right=col_left + col_w, top=bar_top, bottom=bar_bottom)
        val_bb = BoundingBox(x=val_x, y=val_y, width=val_w, height=val_h, left=val_x, right=val_x + val_w, top=val_y, bottom=val_y + val_h)
        lbl_bb = BoundingBox(x=lbl_x, y=lbl_y, width=lbl_w, height=lbl_h, left=lbl_x, right=lbl_x + lbl_w, top=lbl_y, bottom=lbl_y + lbl_h)
        glob_bb = BoundingBox(
            x=min(col_left, val_x, lbl_x),
            y=val_y,
            width=max(col_w, val_w, lbl_w),
            height=(lbl_y + lbl_h) - val_y,
            left=min(col_left, val_x, lbl_x),
            right=max(col_left + col_w, val_x + val_w, lbl_x + lbl_w),
            top=val_y,
            bottom=lbl_y + lbl_h,
        )

        columns.append(WaterfallColumnLayout(
            type="step",
            index=col_index,
            label=cs["label"],
            value=cs["new"],
            bar_bounds=bar_bb,
            value_bounds=val_bb,
            label_bounds=lbl_bb,
            global_bounds=glob_bb,
        ))

    # Final Total Column
    final_index = total_cols - 1
    col_left = chart_left + plot_padding_x + final_index * (col_w + col_gap)
    bar_h = level_to_y(end_value)
    bar_top = chart_top + chart_h - plot_padding_bottom - bar_h
    bar_bottom = chart_top + chart_h - plot_padding_bottom

    val_w = col_w * 1.4
    val_h = 20.0
    val_x = col_left + (col_w - val_w) / 2
    val_y = bar_top - val_h - 4

    lbl_w = max(col_w * 1.2, 100.0)
    lbl_h = 24.0
    lbl_x = col_left + (col_w - lbl_w) / 2
    lbl_y = bar_bottom + 8

    # Clamping to safe right
    if val_x + val_w > safe.right:
        val_x = safe.right - val_w
    if lbl_x + lbl_w > safe.right:
        lbl_x = safe.right - lbl_w

    bar_bb = BoundingBox(x=col_left, y=bar_top, width=col_w, height=bar_h, left=col_left, right=col_left + col_w, top=bar_top, bottom=bar_bottom)
    val_bb = BoundingBox(x=val_x, y=val_y, width=val_w, height=val_h, left=val_x, right=val_x + val_w, top=val_y, bottom=val_y + val_h)
    lbl_bb = BoundingBox(x=lbl_x, y=lbl_y, width=lbl_w, height=lbl_h, left=lbl_x, right=lbl_x + lbl_w, top=lbl_y, bottom=lbl_y + lbl_h)
    glob_bb = BoundingBox(
        x=min(col_left, val_x, lbl_x),
        y=val_y,
        width=max(col_w, val_w, lbl_w),
        height=(lbl_y + lbl_h) - val_y,
        left=min(col_left, val_x, lbl_x),
        right=max(col_left + col_w, val_x + val_w, lbl_x + lbl_w),
        top=val_y,
        bottom=lbl_y + lbl_h,
    )

    columns.append(WaterfallColumnLayout(
        type="final",
        index=final_index,
        label=end_label,
        value=end_value,
        bar_bounds=bar_bb,
        value_bounds=val_bb,
        label_bounds=lbl_bb,
        global_bounds=glob_bb,
    ))

    title_bounds = BoundingBox(
        x=safe.title_zone.x,
        y=safe.title_zone.y,
        width=safe.title_zone.width,
        height=safe.title_zone.height,
        left=safe.title_zone.x,
        right=safe.title_zone.right,
        top=safe.title_zone.y,
        bottom=safe.title_zone.bottom,
    )

    return WaterfallLayoutGeometry(
        safe_area=safe,
        title_bounds=title_bounds,
        chart_container_bounds=chart_container,
        columns=columns,
    )
