from __future__ import annotations

from loguru import logger

from app.models.motion import MotionGroupSpec, MotionSceneSpec


def _can_continue_group(prev: MotionSceneSpec, next_spec: MotionSceneSpec) -> bool:
    """Check if next_spec can continuously extend the group starting with prev."""
    if not (prev.visual_group_id and next_spec.visual_group_id):
        return False
    if prev.visual_group_id != next_spec.visual_group_id:
        return False
    # Exact frame adjacency: no gaps, no overlaps
    if prev.end_frame != next_spec.start_frame:
        logger.warning(
            f"Visual group {prev.visual_group_id} has timing gap/overlap between scene {prev.scene_id} "
            f"({prev.start_frame}-{prev.end_frame}) and {next_spec.scene_id} "
            f"({next_spec.start_frame}-{next_spec.end_frame}); splitting group."
        )
        return False
    # Consistent rendering properties
    if prev.fps != next_spec.fps or prev.width != next_spec.width or prev.height != next_spec.height:
        logger.warning(
            f"Visual group {prev.visual_group_id} has mismatched fps/resolution between scene {prev.scene_id} "
            f"({prev.fps}fps, {prev.width}x{prev.height}) and {next_spec.scene_id} "
            f"({next_spec.fps}fps, {next_spec.width}x{next_spec.height}); splitting group."
        )
        return False
    return True


def form_motion_groups(
    scene_specs: list[MotionSceneSpec],
) -> list[MotionGroupSpec | MotionSceneSpec]:
    """Group contiguous visual scenes sharing the same visual_group_id into MotionGroupSpecs.

    A MotionGroupSpec may only contain scenes where every boundary satisfies:
    previous.end_frame == next.start_frame with matching fps, width, and height.

    Any gap, overlap, or dimension/fps mismatch splits into separate render items/groups.
    Non-grouped or isolated scenes remain individual MotionSceneSpecs.
    """
    if not scene_specs:
        return []

    sorted_specs = sorted(scene_specs, key=lambda s: s.order)
    result: list[MotionGroupSpec | MotionSceneSpec] = []
    current_group_scenes: list[MotionSceneSpec] = []

    def _flush_current_group() -> None:
        nonlocal current_group_scenes
        if not current_group_scenes:
            return
        if len(current_group_scenes) > 1:
            result.append(_create_group_spec(current_group_scenes[0].visual_group_id or "group", current_group_scenes))
        else:
            result.append(current_group_scenes[0])
        current_group_scenes = []

    for spec in sorted_specs:
        if not spec.visual_group_id:
            _flush_current_group()
            result.append(spec)
            continue

        if not current_group_scenes:
            current_group_scenes.append(spec)
        else:
            if _can_continue_group(current_group_scenes[-1], spec):
                current_group_scenes.append(spec)
            else:
                _flush_current_group()
                current_group_scenes.append(spec)

    _flush_current_group()
    return result


def _create_group_spec(group_id: str, scenes: list[MotionSceneSpec]) -> MotionGroupSpec:
    start_frame = scenes[0].start_frame
    end_frame = scenes[-1].end_frame
    duration_frames = max(1, end_frame - start_frame)
    fps = scenes[0].fps
    width = scenes[0].width
    height = scenes[0].height

    return MotionGroupSpec(
        group_id=group_id,
        scene_ids=[s.scene_id for s in scenes],
        start_frame=start_frame,
        end_frame=end_frame,
        duration_frames=duration_frames,
        fps=fps,
        width=width,
        height=height,
        scenes=scenes,
    )
