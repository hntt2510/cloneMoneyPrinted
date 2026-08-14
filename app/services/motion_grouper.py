from __future__ import annotations

from loguru import logger

from app.models.motion import MotionGroupSpec, MotionSceneSpec


def form_motion_groups(
    scene_specs: list[MotionSceneSpec],
) -> list[MotionGroupSpec | MotionSceneSpec]:
    """Group contiguous visual scenes sharing the same visual_group_id into MotionGroupSpecs.

    Non-grouped or isolated scenes remain individual MotionSceneSpecs.
    """
    if not scene_specs:
        return []

    sorted_specs = sorted(scene_specs, key=lambda s: s.order)
    result: list[MotionGroupSpec | MotionSceneSpec] = []

    current_group_id: str | None = None
    current_group_scenes: list[MotionSceneSpec] = []

    for spec in sorted_specs:
        gid = spec.visual_group_id

        if gid:
            if current_group_id == gid:
                # Contiguous member of current group
                current_group_scenes.append(spec)
            else:
                # Flush previous group or item
                if current_group_scenes and current_group_id:
                    if len(current_group_scenes) > 1:
                        result.append(_create_group_spec(current_group_id, current_group_scenes))
                    else:
                        result.append(current_group_scenes[0])
                current_group_id = gid
                current_group_scenes = [spec]
        else:
            # Non-grouped scene
            if current_group_scenes and current_group_id:
                if len(current_group_scenes) > 1:
                    result.append(_create_group_spec(current_group_id, current_group_scenes))
                else:
                    result.append(current_group_scenes[0])
                current_group_id = None
                current_group_scenes = []
            result.append(spec)

    # Flush any remaining group
    if current_group_scenes and current_group_id:
        if len(current_group_scenes) > 1:
            result.append(_create_group_spec(current_group_id, current_group_scenes))
        else:
            result.append(current_group_scenes[0])

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
