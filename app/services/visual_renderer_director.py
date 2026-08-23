"""Adaptive Visual Renderer Director (G19).

Separates WHAT data means from HOW the story is visually told.
Deterministically decides:
- RendererFamily (standard_remotion, editorial_remotion, d3_remotion, hybrid_broll_data, diagram_remotion)
- StorytellingTechnique (metric_punch, progressive_breakdown, narrative_chart, split_comparison, threshold_story, timeline_story, diagram_reveal, data_grid, hybrid_*, etc.)
- CompositionPattern, MotionPattern, FocusStrategy, BackgroundTreatment, InformationDensity, CameraMotion
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from loguru import logger

from app.models.motion import (
    BackgroundTreatment,
    CompositionPattern,
    FocusStrategy,
    InformationDensity,
    MotionPattern,
    RendererDecision,
    RendererFamily,
    SemanticDataIntent,
    StorytellingTechnique,
    VisualGrammar,
)


class VisualDiversityMemoryV2:
    """Tracks sequence of storytelling techniques, composition patterns, and background treatments."""

    def __init__(self) -> None:
        self.history: list[RendererDecision] = []
        self._bg_cycle = [
            BackgroundTreatment.radial_light,
            BackgroundTreatment.soft_grid,
            BackgroundTreatment.gradient_field,
            BackgroundTreatment.spotlight,
        ]
        self._bg_index = 0

    def record(self, decision: RendererDecision) -> None:
        self.history.append(decision)

    def get_recent_techniques(self, n: int = 3) -> list[StorytellingTechnique]:
        return [d.storytelling_technique for d in self.history[-n:]]

    def get_next_background_treatment(
        self, preferred: BackgroundTreatment = BackgroundTreatment.radial_light
    ) -> BackgroundTreatment:
        if self.history:
            last_bg = self.history[-1].background_treatment
            if preferred != last_bg:
                return preferred
            self._bg_index = (self._bg_index + 1) % len(self._bg_cycle)
            return self._bg_cycle[self._bg_index]
        return preferred

    def reset(self) -> None:
        self.history.clear()
        self._bg_index = 0


class VisualRendererDirector:
    """Deterministic director deciding renderer family and storytelling technique."""

    def __init__(self, diversity_memory: VisualDiversityMemoryV2 | None = None) -> None:
        self.diversity_memory = diversity_memory or VisualDiversityMemoryV2()

    def decide_renderer(
        self,
        data_intent: SemanticDataIntent | None,
        visual_grammar: VisualGrammar | None,
        template: str,
        props: dict[str, Any],
        narration: str = "",
        duration_frames: int = 90,
        fps: int = 30,
        aspect_ratio: str = "16:9",
        broll_candidate_confidence: float = 0.0,
        broll_candidate_path: str | None = None,
        is_grouped: bool = False,
        visual_group_id: str | None = None,
    ) -> RendererDecision:
        """Deterministically map semantic data intent, grammar, and narration to a rich RendererDecision."""
        recent_techniques = self.diversity_memory.get_recent_techniques(2)
        has_strong_broll = bool(broll_candidate_confidence >= 0.70 and broll_candidate_path)

        # 1. PROCESS / SYSTEM FLOW DIAGRAM
        if (
            template == "diagram"
            or visual_grammar == VisualGrammar.diagram
            or data_intent == SemanticDataIntent.sequence
            or ("request" in narration.lower() and "cache" in narration.lower() and "database" in narration.lower())
        ):
            decision = RendererDecision(
                renderer_family=RendererFamily.diagram_remotion,
                storytelling_technique=StorytellingTechnique.diagram_reveal,
                composition_pattern=CompositionPattern.flow_diagram,
                motion_pattern=MotionPattern.progressive_draw,
                focus_strategy=FocusStrategy.sequential_focus,
                background_treatment=BackgroundTreatment.soft_grid,
                density=InformationDensity.medium,
                camera_motion="subtle_push",
                asset_mode="none",
                reason="System process/flow with sequential node dependencies mapped to diagram_reveal",
            )
            self.diversity_memory.record(decision)
            return decision

        # 2. DATA GRID / KPI MATRIX (3 to 6 metrics)
        items_list = props.get("items", [])
        if (
            template == "data_grid"
            or visual_grammar == VisualGrammar.data_grid
            or (
                isinstance(items_list, list)
                and len(items_list) >= 4
                and all(isinstance(x, dict) and "value" in x for x in items_list)
            )
        ):
            decision = RendererDecision(
                renderer_family=RendererFamily.editorial_remotion,
                storytelling_technique=StorytellingTechnique.data_grid,
                composition_pattern=CompositionPattern.data_grid_matrix,
                motion_pattern=MotionPattern.stagger_cascade,
                focus_strategy=FocusStrategy.all_visible,
                background_treatment=BackgroundTreatment.gradient_field,
                density=InformationDensity.high,
                camera_motion="subtle_push",
                asset_mode="none",
                reason="Multi-metric KPI dashboard mapped to structured data_grid",
            )
            self.diversity_memory.record(decision)
            return decision

        # 3. THRESHOLD / LIMIT STORY
        if (
            template == "threshold"
            or visual_grammar == VisualGrammar.threshold
            or data_intent == SemanticDataIntent.threshold
        ):
            decision = RendererDecision(
                renderer_family=RendererFamily.editorial_remotion,
                storytelling_technique=StorytellingTechnique.threshold_story,
                composition_pattern=CompositionPattern.threshold_gauge,
                motion_pattern=MotionPattern.focus_step,
                focus_strategy=FocusStrategy.spotlight_active,
                background_treatment=BackgroundTreatment.radial_light,
                density=InformationDensity.medium,
                camera_motion="subtle_push",
                asset_mode="none",
                reason="Threshold comparison with consequence resolution mapped to threshold_story",
            )
            self.diversity_memory.record(decision)
            return decision

        # 4. PROGRESSIVE BREAKDOWN / STACKED SEGMENTS
        if (
            template == "breakdown"
            or visual_grammar == VisualGrammar.breakdown
            or data_intent == SemanticDataIntent.breakdown
            or (visual_group_id and "cost_breakdown" in visual_group_id.lower())
        ):
            decision = RendererDecision(
                renderer_family=RendererFamily.editorial_remotion,
                storytelling_technique=StorytellingTechnique.progressive_breakdown,
                composition_pattern=CompositionPattern.split_screen,
                motion_pattern=MotionPattern.progressive_draw,
                focus_strategy=FocusStrategy.sequential_focus,
                background_treatment=BackgroundTreatment.radial_light,
                density=InformationDensity.medium,
                camera_motion="subtle_push",
                asset_mode="none",
                reason="Part-to-whole arithmetic breakdown mapped to progressive_breakdown",
            )
            self.diversity_memory.record(decision)
            return decision

        # 5. PART-TO-WHOLE (PIE / DONUT)
        if (
            template in ("pie", "donut")
            or visual_grammar in (VisualGrammar.pie, VisualGrammar.donut)
            or data_intent == SemanticDataIntent.part_to_whole
        ):
            decision = RendererDecision(
                renderer_family=RendererFamily.d3_remotion,
                storytelling_technique=StorytellingTechnique.narrative_chart,
                composition_pattern=CompositionPattern.centered_hero,
                motion_pattern=MotionPattern.focus_step,
                focus_strategy=FocusStrategy.sequential_focus,
                background_treatment=BackgroundTreatment.radial_light,
                density=InformationDensity.medium,
                camera_motion="subtle_push",
                asset_mode="none",
                reason="Part-to-whole distribution mapped to D3 arc narrative_chart",
            )
            self.diversity_memory.record(decision)
            return decision

        # 6. COMPARISON / SPLIT COMPARE
        if (
            template == "comparison"
            or visual_grammar == VisualGrammar.comparison
            or data_intent == SemanticDataIntent.category_comparison
        ):
            if has_strong_broll:
                decision = RendererDecision(
                    renderer_family=RendererFamily.hybrid_broll_data,
                    storytelling_technique=StorytellingTechnique.hybrid_comparison,
                    composition_pattern=CompositionPattern.asset_left_data_right,
                    motion_pattern=MotionPattern.divider_reveal,
                    focus_strategy=FocusStrategy.sequential_focus,
                    background_treatment=BackgroundTreatment.asset_blur,
                    density=InformationDensity.medium,
                    camera_motion="subtle_push",
                    asset_mode="video",
                    asset_path=broll_candidate_path,
                    asset_confidence=broll_candidate_confidence,
                    reason="Strong B-roll available: paired with comparison graphics as hybrid_comparison",
                )
            else:
                decision = RendererDecision(
                    renderer_family=RendererFamily.editorial_remotion,
                    storytelling_technique=StorytellingTechnique.split_comparison,
                    composition_pattern=CompositionPattern.split_screen,
                    motion_pattern=MotionPattern.divider_reveal,
                    focus_strategy=FocusStrategy.sequential_focus,
                    background_treatment=self.diversity_memory.get_next_background_treatment(BackgroundTreatment.soft_grid),
                    density=InformationDensity.medium,
                    camera_motion="subtle_push",
                    asset_mode="none",
                    reason="Two-sided conceptual comparison mapped to split_comparison",
                )
            self.diversity_memory.record(decision)
            return decision

        # 7. TIMELINE / JOURNEY STORY
        if (
            template == "timeline"
            or visual_grammar == VisualGrammar.timeline
            or data_intent in (SemanticDataIntent.trend_over_time, SemanticDataIntent.change_over_time)
        ):
            decision = RendererDecision(
                renderer_family=RendererFamily.editorial_remotion,
                storytelling_technique=StorytellingTechnique.timeline_story,
                composition_pattern=CompositionPattern.timeline_track,
                motion_pattern=MotionPattern.progressive_draw,
                focus_strategy=FocusStrategy.sequential_focus,
                background_treatment=BackgroundTreatment.soft_grid,
                density=InformationDensity.medium,
                camera_motion="subtle_push",
                asset_mode="none",
                reason="Chronological milestones mapped to timeline_story",
            )
            self.diversity_memory.record(decision)
            return decision

        # 8. RANKED LIST
        if (
            template == "ranked_list"
            or visual_grammar == VisualGrammar.ranked_list
            or data_intent == SemanticDataIntent.ranked_categories
        ):
            decision = RendererDecision(
                renderer_family=RendererFamily.editorial_remotion,
                storytelling_technique=StorytellingTechnique.ranked_reveal,
                composition_pattern=CompositionPattern.centered_hero,
                motion_pattern=MotionPattern.stagger_cascade,
                focus_strategy=FocusStrategy.sequential_focus,
                background_treatment=BackgroundTreatment.gradient_field,
                density=InformationDensity.medium,
                camera_motion="subtle_push",
                asset_mode="none",
                reason="Ranked hierarchy mapped to ranked_reveal",
            )
            self.diversity_memory.record(decision)
            return decision

        # 9. CHARTS (BAR / LINE / AREA / WATERFALL / GAUGE)
        if template in ("bar_chart", "line_chart", "area_chart", "gauge", "waterfall"):
            technique = (
                StorytellingTechnique.focus_sequence
                if template == "bar_chart"
                else StorytellingTechnique.narrative_chart
            )
            decision = RendererDecision(
                renderer_family=RendererFamily.d3_remotion,
                storytelling_technique=technique,
                composition_pattern=CompositionPattern.centered_hero,
                motion_pattern=MotionPattern.progressive_draw,
                focus_strategy=FocusStrategy.sequential_focus,
                background_treatment=BackgroundTreatment.radial_light,
                density=InformationDensity.medium,
                camera_motion="subtle_push",
                asset_mode="none",
                reason=f"Data series {template} mapped to D3 {technique.value}",
            )
            self.diversity_memory.record(decision)
            return decision

        # 10. SINGLE METRIC OR HYBRID B-ROLL DATA
        resolved_candidate_path = broll_candidate_path or props.get("asset_path")
        has_valid_file = bool(resolved_candidate_path and Path(resolved_candidate_path).exists())
        is_user_provided = bool(props.get("asset_origin") == "user_provided" or props.get("is_user_provided") is True)
        is_trusted_user_media = is_user_provided and has_valid_file
        has_confident_stock = bool(broll_candidate_confidence >= 0.70 and has_valid_file)

        if is_trusted_user_media or has_confident_stock:
            decision = RendererDecision(
                renderer_family=RendererFamily.hybrid_broll_data,
                storytelling_technique=StorytellingTechnique.hybrid_metric,
                composition_pattern=CompositionPattern.asset_left_data_right,
                motion_pattern=MotionPattern.camera_push,
                focus_strategy=FocusStrategy.all_visible,
                background_treatment=BackgroundTreatment.asset_blur,
                density=InformationDensity.low,
                camera_motion="subtle_push",
                asset_mode="video",
                asset_path=resolved_candidate_path,
                asset_confidence=None if is_trusted_user_media else broll_candidate_confidence,
                asset_origin="user_provided" if is_trusted_user_media else "stock_search",
                asset_score_source="not_scored_user_provided" if is_trusted_user_media else "stock_search",
                reason="User-provided local asset paired with data hero" if is_trusted_user_media else f"Stock footage (confidence={broll_candidate_confidence:.2f}) paired with metric hero as hybrid_metric",
            )
        else:
            # Diversity check for metric presentations (metric_delta requires grounded change semantics)
            delta_keywords = bool(re.search(r"\b(?:grew|grown|grow|grows|growing|increase|increased|increases|increasing|rose|risen|rise|rises|rising|jumped|jumps|jumping|surged|surges|surging|climb|climbed|climbs|climbing|fell|fall|falls|falling|dropped|drop|drops|dropping|decrease|decreased|decreases|decreasing|decline|declined|declines|declining|down from|up from|from\s+\$?\d+.*to\s+\$?\d+)\b", narration, re.I))
            if delta_keywords or props.get("delta_direction"):
                technique = StorytellingTechnique.metric_delta
                pattern = CompositionPattern.split_screen
            elif recent_techniques and recent_techniques[-1] == StorytellingTechnique.metric_punch:
                technique = StorytellingTechnique.metric_context
                pattern = CompositionPattern.centered_hero
            else:
                technique = StorytellingTechnique.metric_punch
                pattern = CompositionPattern.centered_hero

            bg = self.diversity_memory.get_next_background_treatment(
                BackgroundTreatment.radial_light if technique == StorytellingTechnique.metric_punch else BackgroundTreatment.soft_grid
            )

            decision = RendererDecision(
                renderer_family=RendererFamily.editorial_remotion,
                storytelling_technique=technique,
                composition_pattern=pattern,
                motion_pattern=MotionPattern.punch_in if technique == StorytellingTechnique.metric_punch else MotionPattern.camera_push,
                focus_strategy=FocusStrategy.all_visible,
                background_treatment=bg,
                density=InformationDensity.low,
                camera_motion="subtle_push",
                asset_mode="none",
                reason=f"Single grounded metric mapped to {technique.value} with {bg.value} background",
            )

        self.diversity_memory.record(decision)
        return decision
