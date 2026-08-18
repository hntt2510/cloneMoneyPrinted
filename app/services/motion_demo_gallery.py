"""Motion Demo Gallery Renderer (G17).

Renders the 15 canonical visual grammar MP4 demos into storage/demo/g17/
for visual developer QA and inspection.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from app.models.motion import (
    KineticBeat,
    KineticBeatKind,
    MotionAnimationPlan,
    MotionGroupSpec,
    MotionSceneSpec,
)
from app.services.remotion import render_group_motion, render_scene_motion


def render_all_g17_demos(output_dir: str | Path = "storage/demo/g17") -> list[str]:
    """Renders all 15 visual grammar demos into the specified output directory."""
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered_files: list[str] = []

    logger.info("Starting G17 Motion Demo Gallery render -> {}", out_dir)

    demos: list[tuple[str, MotionSceneSpec | MotionGroupSpec]] = []

    # 1. 01_metric_hero
    demos.append((
        "01_metric_hero.mp4",
        MotionSceneSpec(
            scene_id="DEMO_01",
            order=1,
            visual_type="data",
            requested_template="number",
            rendered_template="number",
            layout_archetype="metric_hero",
            props={
                "headline": "REPAIR COST",
                "value": "$6,000",
                "numeric_value": 6000,
                "prefix": "$",
                "eyebrow": "CLAIM ESTIMATE",
                "context_label": "Average Collision Repair",
                "layout_archetype": "metric_hero",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 2. 02_donut
    demos.append((
        "02_donut.mp4",
        MotionSceneSpec(
            scene_id="DEMO_02",
            order=2,
            visual_type="data",
            requested_template="pie",
            rendered_template="pie",
            layout_archetype="donut_center_stat",
            props={
                "headline": "Customer Plan Selection",
                "eyebrow": "PORTFOLIO DISTRIBUTION",
                "variant": "donut_center_stat",
                "layout_archetype": "donut_center_stat",
                "items": [
                    {"label": "PREMIUM", "value": 40, "percentage": 40, "display_value": "40%", "highlight": True},
                    {"label": "STANDARD", "value": 35, "percentage": 35, "display_value": "35%", "highlight": False},
                    {"label": "BASIC", "value": 25, "percentage": 25, "display_value": "25%", "highlight": False},
                ],
                "focus_label": "PREMIUM",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 3. 03_pie_focus
    demos.append((
        "03_pie_focus.mp4",
        MotionSceneSpec(
            scene_id="DEMO_03",
            order=3,
            visual_type="data",
            requested_template="pie",
            rendered_template="pie",
            layout_archetype="pie_focus",
            props={
                "headline": "Tier Coverage Share",
                "eyebrow": "TIER ALLOCATION",
                "variant": "pie_focus",
                "layout_archetype": "pie_focus",
                "items": [
                    {"label": "COMPREHENSIVE", "value": 55, "percentage": 55, "display_value": "55%", "highlight": True},
                    {"label": "COLLISION ONLY", "value": 30, "percentage": 30, "display_value": "30%", "highlight": False},
                    {"label": "LIABILITY", "value": 15, "percentage": 15, "display_value": "15%", "highlight": False},
                ],
                "focus_label": "COMPREHENSIVE",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 4. 04_ranked_bars
    demos.append((
        "04_ranked_bars.mp4",
        MotionSceneSpec(
            scene_id="DEMO_04",
            order=4,
            visual_type="data",
            requested_template="ranked_list",
            rendered_template="ranked_list",
            layout_archetype="ranked_horizontal_bars",
            props={
                "headline": "Top 4 Collision Claim Causes",
                "eyebrow": "CLAIMS RANKING",
                "variant": "ranked_horizontal_bars",
                "layout_archetype": "ranked_horizontal_bars",
                "items": [
                    {"rank": 1, "label": "Rear-End Collisions", "value": 38, "display_value": "38%", "highlight": True},
                    {"rank": 2, "label": "Intersection T-Bones", "value": 27, "display_value": "27%", "highlight": False},
                    {"rank": 3, "label": "Single-Vehicle Runoff", "value": 21, "display_value": "21%", "highlight": False},
                    {"rank": 4, "label": "Parking Lot Scrapes", "value": 14, "display_value": "14%", "highlight": False},
                ],
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 5. 05_stacked_bar
    demos.append((
        "05_stacked_bar.mp4",
        MotionSceneSpec(
            scene_id="DEMO_05",
            order=5,
            visual_type="data",
            requested_template="stacked_bar",
            rendered_template="stacked_bar",
            layout_archetype="stacked_bar_reveal",
            props={
                "headline": "Annual Premium Allocation",
                "eyebrow": "FEE BREAKDOWN",
                "total": 1200,
                "total_display": "$1,200 Total",
                "variant": "stacked_bar_reveal",
                "layout_archetype": "stacked_bar_reveal",
                "segments": [
                    {"label": "Base Coverage", "value": 720, "display_value": "$720 (60%)", "highlight": True},
                    {"label": "Collision Rider", "value": 300, "display_value": "$300 (25%)", "highlight": False},
                    {"label": "Roadside Assistance", "value": 180, "display_value": "$180 (15%)", "highlight": False},
                ],
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 6. 06_line
    demos.append((
        "06_line.mp4",
        MotionSceneSpec(
            scene_id="DEMO_06",
            order=6,
            visual_type="data",
            requested_template="line_chart",
            rendered_template="line_chart",
            layout_archetype="line_chart_v2",
            props={
                "headline": "Average Annual Premium Growth",
                "eyebrow": "5-YEAR TREND",
                "unit": "$",
                "show_area": True,
                "layout_archetype": "line_chart_v2",
                "points": [
                    {"x_label": "2022", "y_value": 1200, "display_value": "$1,200"},
                    {"x_label": "2023", "y_value": 1340, "display_value": "$1,340"},
                    {"x_label": "2024", "y_value": 1510, "display_value": "$1,510"},
                    {"x_label": "2025", "y_value": 1690, "display_value": "$1,690"},
                    {"x_label": "2026", "y_value": 1850, "display_value": "$1,850"},
                ],
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 7. 07_area
    demos.append((
        "07_area.mp4",
        MotionSceneSpec(
            scene_id="DEMO_07",
            order=7,
            visual_type="data",
            requested_template="area",
            rendered_template="area",
            layout_archetype="area_trend",
            props={
                "headline": "Cumulative Policy Reserves",
                "eyebrow": "CAPITAL GROWTH",
                "unit": "$M",
                "variant": "area_trend",
                "layout_archetype": "area_trend",
                "points": [
                    {"x_label": "Q1", "y_value": 12, "display_value": "$12M"},
                    {"x_label": "Q2", "y_value": 18, "display_value": "$18M"},
                    {"x_label": "Q3", "y_value": 27, "display_value": "$27M"},
                    {"x_label": "Q4", "y_value": 38, "display_value": "$38M"},
                ],
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 8. 08_threshold
    demos.append((
        "08_threshold.mp4",
        MotionSceneSpec(
            scene_id="DEMO_08",
            order=8,
            visual_type="data",
            requested_template="threshold",
            rendered_template="threshold",
            layout_archetype="threshold_v2",
            props={
                "headline": "Accident Damage vs Coverage Limit",
                "eyebrow": "POLICY CEILING",
                "threshold_label": "Coverage Cap",
                "threshold_value": 25000,
                "threshold_display": "$25,000",
                "current_value": 40000,
                "current_display": "$40,000",
                "layout_archetype": "threshold_v2",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 9. 09_gauge
    demos.append((
        "09_gauge.mp4",
        MotionSceneSpec(
            scene_id="DEMO_09",
            order=9,
            visual_type="data",
            requested_template="gauge",
            rendered_template="gauge",
            layout_archetype="radial_gauge",
            props={
                "headline": "Underwriting Process Completion",
                "eyebrow": "VERIFICATION QUOTA",
                "current_value": 75,
                "max_value": 100,
                "min_value": 0,
                "display_value": "75%",
                "unit": "%",
                "label": "Audit Passed",
                "variant": "radial_gauge",
                "layout_archetype": "radial_gauge",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 10. 10_waterfall
    demos.append((
        "10_waterfall.mp4",
        MotionSceneSpec(
            scene_id="DEMO_10",
            order=10,
            visual_type="data",
            requested_template="waterfall",
            rendered_template="waterfall",
            layout_archetype="waterfall_steps",
            props={
                "headline": "Premium Price Adjustments",
                "eyebrow": "RATE ADJUSTMENT",
                "start_value": 100,
                "start_label": "Base Quote",
                "steps": [
                    {"label": "State Filing Fee", "delta": 30, "display_value": "+$30"},
                    {"label": "Safe Driver Discount", "delta": -20, "display_value": "-$20"},
                ],
                "end_value": 110,
                "end_label": "Final Premium",
                "variant": "waterfall_steps",
                "layout_archetype": "waterfall_steps",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 11. 11_timeline
    demos.append((
        "11_timeline.mp4",
        MotionSceneSpec(
            scene_id="DEMO_11",
            order=11,
            visual_type="data",
            requested_template="timeline",
            rendered_template="timeline",
            layout_archetype="timeline_v2",
            props={
                "headline": "Collision Claim Resolution Lifecycle",
                "eyebrow": "CLAIM TIMELINE",
                "layout_archetype": "timeline_v2",
                "milestones": [
                    {"time_label": "DAY 1", "title": "Incident Filed", "description": "Police report & photos uploaded", "is_active": False},
                    {"time_label": "DAY 3", "title": "Adjuster Assessment", "description": "Physical repair estimate certified", "is_active": False},
                    {"time_label": "DAY 7", "title": "Payment Disbursed", "description": "Settlement check issued to shop", "is_active": True},
                ],
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 12. 12_comparison
    demos.append((
        "12_comparison.mp4",
        MotionSceneSpec(
            scene_id="DEMO_12",
            order=12,
            visual_type="data",
            requested_template="comparison",
            rendered_template="comparison",
            layout_archetype="split_compare",
            props={
                "headline": "Standard vs Comprehensive Deductibles",
                "eyebrow": "POLICY COMPARISON",
                "layout_archetype": "split_compare",
                "items": [
                    {"label": "BASIC TIER", "value": "$1,000", "numeric_value": 1000, "highlight": False},
                    {"label": "PREMIUM TIER", "value": "$250", "numeric_value": 250, "highlight": True},
                ],
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 13. 13_breakdown (Group Master)
    demos.append((
        "13_breakdown.mp4",
        MotionGroupSpec(
            group_id="demo_breakdown_group",
            scene_ids=["DEMO_13A", "DEMO_13B", "DEMO_13C"],
            start_frame=0,
            end_frame=180,
            duration_frames=180,
            fps=30,
            width=1280,
            height=720,
            scenes=[
                MotionSceneSpec(
                    scene_id="DEMO_13A",
                    order=1,
                    visual_type="data",
                    requested_template="comparison",
                    rendered_template="comparison",
                    layout_archetype="stacked_breakdown",
                    props={
                        "headline": "TOTAL REPAIR COST",
                        "value": "$8,000",
                        "numeric_value": 8000,
                        "eyebrow": "REPAIR COST",
                        "layout_archetype": "stacked_breakdown",
                        "total": {"label": "TOTAL REPAIR", "value": "$8,000", "numeric_value": 8000},
                        "parts": [
                            {"label": "YOU PAY", "value": "$2,000", "numeric_value": 2000, "highlight": True},
                            {"label": "INSURANCE", "value": "$6,000", "numeric_value": 6000, "highlight": False},
                        ],
                    },
                    start_time=0.0,
                    end_time=2.0,
                    start_frame=0,
                    end_frame=60,
                    duration_frames=60,
                    fps=30,
                    width=1280,
                    height=720,
                    visual_group_id="demo_breakdown_group",
                ),
                MotionSceneSpec(
                    scene_id="DEMO_13B",
                    order=2,
                    visual_type="data",
                    requested_template="comparison",
                    rendered_template="comparison",
                    layout_archetype="stacked_breakdown",
                    props={
                        "headline": "YOUR DEDUCTIBLE",
                        "value": "$2,000",
                        "numeric_value": 2000,
                        "eyebrow": "DEDUCTIBLE",
                        "layout_archetype": "stacked_breakdown",
                        "total": {"label": "TOTAL REPAIR", "value": "$8,000", "numeric_value": 8000},
                        "parts": [
                            {"label": "YOU PAY", "value": "$2,000", "numeric_value": 2000, "highlight": True},
                            {"label": "INSURANCE", "value": "$6,000", "numeric_value": 6000, "highlight": False},
                        ],
                    },
                    start_time=2.0,
                    end_time=4.0,
                    start_frame=60,
                    end_frame=120,
                    duration_frames=60,
                    fps=30,
                    width=1280,
                    height=720,
                    visual_group_id="demo_breakdown_group",
                ),
                MotionSceneSpec(
                    scene_id="DEMO_13C",
                    order=3,
                    visual_type="data",
                    requested_template="comparison",
                    rendered_template="comparison",
                    layout_archetype="stacked_breakdown",
                    props={
                        "headline": "INSURANCE COVERS",
                        "value": "$6,000",
                        "numeric_value": 6000,
                        "eyebrow": "INSURANCE",
                        "layout_archetype": "stacked_breakdown",
                        "total": {"label": "TOTAL REPAIR", "value": "$8,000", "numeric_value": 8000},
                        "parts": [
                            {"label": "YOU PAY", "value": "$2,000", "numeric_value": 2000, "highlight": True},
                            {"label": "INSURANCE", "value": "$6,000", "numeric_value": 6000, "highlight": False},
                        ],
                    },
                    start_time=4.0,
                    end_time=6.0,
                    start_frame=120,
                    end_frame=180,
                    duration_frames=60,
                    fps=30,
                    width=1280,
                    height=720,
                    visual_group_id="demo_breakdown_group",
                ),
            ],
        ),
    ))

    # 14. 14_before_after
    demos.append((
        "14_before_after.mp4",
        MotionSceneSpec(
            scene_id="DEMO_14",
            order=14,
            visual_type="data",
            requested_template="before_after",
            rendered_template="before_after",
            layout_archetype="split_screen",
            props={
                "headline": "Policy Rate Renewal Shift",
                "eyebrow": "ANNUAL RENEWAL",
                "before_label": "Prior Year Rate",
                "before_value": "$140/mo",
                "after_label": "Updated Quote",
                "after_value": "$95/mo",
                "delta_display": "-$45/mo Savings",
                "variant": "split_screen",
                "layout_archetype": "split_screen",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # 15. 15_kinetic_statement
    demos.append((
        "15_kinetic_statement.mp4",
        MotionSceneSpec(
            scene_id="DEMO_15",
            order=15,
            visual_type="text",
            requested_template="text",
            rendered_template="text",
            layout_archetype="kinetic_statement",
            props={
                "headline": "CHEAPEST IS NOT AUTOMATICALLY BEST",
                "subheadline": "Prioritize high liability limits over low deductibles",
                "layout_archetype": "kinetic_statement",
            },
            start_time=0.0,
            end_time=3.0,
            start_frame=0,
            end_frame=90,
            duration_frames=90,
            fps=30,
            width=1280,
            height=720,
        ),
    ))

    # Execute renders
    for filename, spec in demos:
        target_path = out_dir / filename
        logger.info("Rendering demo clip: {}", filename)
        if isinstance(spec, MotionGroupSpec):
            assets = render_group_motion(spec, str(out_dir))
            master_file = out_dir / "motion" / "groups" / spec.group_id / "master.mp4"
            if master_file.exists():
                import shutil
                shutil.copyfile(str(master_file), str(target_path))
                rendered_files.append(str(target_path))
        else:
            asset = render_scene_motion(spec, str(out_dir))
            src_file = Path(asset.output_file)
            if src_file.exists():
                import shutil
                shutil.copyfile(str(src_file), str(target_path))
                rendered_files.append(str(target_path))

    logger.success("Completed rendering {} demo clips into {}", len(rendered_files), out_dir)
    print(f"\n=======================================================")
    print(f"G17 DEMO GALLERY PERSISTED TO: {out_dir}")
    print(f"Total Clips Rendered: {len(rendered_files)}")
    for f in rendered_files:
        print(f"  - {os.path.basename(f)} ({os.path.getsize(f):,} bytes)")
    print(f"=======================================================\n")
    return rendered_files
