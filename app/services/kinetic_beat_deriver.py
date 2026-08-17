import logging
from app.models.motion import KineticBeat, KineticBeatKind, MotionAnimationPlan
from app.services.numeric_parser import extract_canonical_numeric_facts
from app.services.timeline import _split_clauses, _text_weight

logger = logging.getLogger(__name__)

def derive_kinetic_beats(
    narration: str,
    fps: int,
    duration_frames: int,
    timing_source: str,
    template: str,
    scene_id: str
) -> MotionAnimationPlan:
    """Derive deterministic kinetic beats from a narration string.
    
    Divides the duration over the clauses of the text by word weight, leaving a final hold.
    Classifies beats by template-specific kinds and assigns data references.
    """
    clauses = _split_clauses(narration)
    total_weight = sum(_text_weight(c) for c in clauses)
    if total_weight == 0:
        # Fallback if no valid text
        final_hold_frames = min(36, max(12, duration_frames // 6))
        return MotionAnimationPlan(
            scene_id=scene_id,
            beats=[],
            final_hold_frames=final_hold_frames,
            timing_source=timing_source,
            kinetic_timing_source="auto"
        )

    # Compute final hold frames
    final_hold_frames = min(36, max(12, duration_frames // 6))
    available_frames = duration_frames - final_hold_frames
    if available_frames <= 0:
        available_frames = duration_frames
        final_hold_frames = 0
        
    beats = []
    current_frame = 0
    
    # Trackers for data_ref
    comp_idx = 0
    chart_idx = 0
    milestone_idx = 0
    
    for i, clause in enumerate(clauses):
        weight = _text_weight(clause)
        frames = max(1, round(available_frames * (weight / total_weight)))
        
        # If it's the last clause, eat any remaining rounding error
        if i == len(clauses) - 1:
            frames = available_frames - current_frame
            
        start_f = current_frame
        end_f = current_frame + frames
        current_frame = end_f
        
        kind = KineticBeatKind.phrase
        data_ref = None
        emphasis = False
        
        # Determine kind based on template and content
        lower_clause = clause.lower()
        if extract_canonical_numeric_facts(clause):
            kind = KineticBeatKind.number
        elif any(kw in lower_clause for kw in ["vs", "versus", "compared to", "against"]):
            kind = KineticBeatKind.comparison_item
            data_ref = f"item_{comp_idx}"
            comp_idx += 1
        elif template == "threshold" and i == 0:
            kind = KineticBeatKind.threshold
        elif template == "timeline":
            kind = KineticBeatKind.milestone
            data_ref = f"m_{milestone_idx}"
            milestone_idx += 1
        elif template in ("bar_chart", "line_chart"):
            kind = KineticBeatKind.chart_item
            data_ref = f"bar_{chart_idx}"
            chart_idx += 1
        elif i == len(clauses) - 1 and any(kw in lower_clause for kw in ["best", "worst", "remember", "key", "important"]):
            kind = KineticBeatKind.takeaway
            emphasis = True
            
        beats.append(
            KineticBeat(
                id=f"{scene_id}_b{i}",
                start_frame=start_f,
                end_frame=end_f,
                kind=kind,
                text=clause,
                emphasis=emphasis,
                data_ref=data_ref
            )
        )
        
    plan = MotionAnimationPlan(
        scene_id=scene_id,
        beats=beats,
        final_hold_frames=final_hold_frames,
        timing_source=timing_source,
        kinetic_timing_source="auto"
    )
    
    # Anti-plateau: warn if all beats finish before 15% of duration_frames
    if beats and beats[-1].end_frame < duration_frames * 0.15:
        logger.warning(f"Kinetic derivation warning for {scene_id}: all beats end before 15% of duration")
        
    return plan
