import argparse
import json
import re
import sys
from pathlib import Path
from typing import Sequence

from loguru import logger

from app.models.schema import MaterialInfo, SUPPORTED_VIDEO_SOURCES, VideoParams
from app.services import task as tm
from app.services.project_runner import ProjectRunError, run_project
from app.services.project_timeline_runner import run_project_plan
from app.services.project_spec import (
    ProjectSpecError,
    load_project_spec,
    preflight_project,
)
from app.utils import utils


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"value must be >= 1, got {parsed}")
    return parsed


def _paragraph_count(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 10:
        raise argparse.ArgumentTypeError(
            f"paragraph-number must be between 1 and 10, got {parsed}"
        )
    return parsed


def _reference_image_count(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 20:
        raise argparse.ArgumentTypeError(
            f"reference-image-count must be between 1 and 20, got {parsed}"
        )
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"value must be >= 0, got {parsed}")
    return parsed


def _percent_position(value: str) -> float:
    parsed = float(value)
    if parsed < 0 or parsed > 100:
        raise argparse.ArgumentTypeError(
            f"custom-position must be between 0 and 100, got {parsed}"
        )
    return parsed


def _hex_color(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError(
            f"color must use #RRGGBB format, got {value!r}"
        )
    return value


_TRANSITION_MODE_VALUES = {
    "none": None,
    "shuffle": "Shuffle",
    "fade-in": "FadeIn",
    "fade-out": "FadeOut",
    "slide-in": "SlideIn",
    "slide-out": "SlideOut",
}


def _transition_mode(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized not in _TRANSITION_MODE_VALUES:
        allowed = ", ".join(_TRANSITION_MODE_VALUES)
        raise argparse.ArgumentTypeError(
            f"video-transition-mode must be one of: {allowed}"
        )
    return _TRANSITION_MODE_VALUES[normalized]


def _bgm_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "none":
        return ""
    if normalized in {"", "random", "custom"}:
        return normalized
    raise argparse.ArgumentTypeError("bgm-type must be one of: none, random, custom")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Video Research & Asset Builder command line video generation"
    )
    parser.add_argument("--project", default=None, help="project JSON file")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate a project file without running the video pipeline",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="generate narration timeline and visual plan without acquiring assets or rendering",
    )
    parser.add_argument(
        "--acquire-broll-only",
        action="store_true",
        help="acquire and render clean scene clips for B-roll cues without full assembly",
    )
    parser.add_argument(
        "--render-motion-only",
        action="store_true",
        help="render motion graphics scene assets for DATA and TEXT cues without full assembly",
    )
    parser.add_argument(
        "--render-motion-demo",
        action="store_true",
        help="render the canonical G18 editorial motion graphics demo clips into storage/demo/g18/",
    )
    parser.add_argument(
        "--acquire-evidence-only",
        action="store_true",
        help="acquire and render clean scene clips for DOCUMENT cues without full assembly",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="run end-to-end autonomous research and asset generation pipeline without human checkpoint or video assembly",
    )
    parser.add_argument(
        "--export-editor-package",
        action="store_true",
        help="export deterministic editor-ready package for NLE manual editing",
    )
    parser.add_argument(
        "--assemble-final",
        action="store_true",
        help="assemble final MP4 video from editor package with QC validation",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="custom destination directory for editor package export",
    )
    parser.add_argument("--video-subject", required=False, help="video subject")
    parser.add_argument("--video-script", default="", help="custom script")
    parser.add_argument("--video-terms", default=None, help="comma-separated terms")
    parser.add_argument(
        "--video-language",
        default=None,
        help="script generation language code (default: auto detect)",
    )
    parser.add_argument(
        "--paragraph-number",
        type=_paragraph_count,
        default=None,
        help="script paragraph count, 1-10",
    )
    parser.add_argument(
        "--video-script-prompt",
        default=None,
        help="custom script requirements prompt",
    )
    parser.add_argument(
        "--custom-system-prompt",
        default=None,
        help="custom system prompt for script generation",
    )
    parser.add_argument(
        "--video-source",
        default="pexels",
        choices=SUPPORTED_VIDEO_SOURCES,
        help="video material source",
    )
    parser.add_argument(
        "--video-materials",
        default="",
        help="comma-separated local material paths",
    )
    parser.add_argument(
        "--stop-at",
        default="video",
        choices=["script", "terms", "audio", "subtitle", "materials", "video"],
        help="pipeline stop stage",
    )
    parser.add_argument(
        "--video-count", type=_positive_int, default=1, help="output video count (>=1)"
    )
    parser.add_argument("--video-aspect", default="9:16", help="video aspect ratio")
    parser.add_argument(
        "--video-concat-mode",
        choices=["random", "sequential"],
        default=None,
        help="video concatenation mode",
    )
    parser.add_argument(
        "--video-transition-mode",
        type=_transition_mode,
        default=None,
        metavar="{none,shuffle,fade-in,fade-out,slide-in,slide-out}",
        help="video transition mode",
    )
    parser.add_argument(
        "--video-clip-duration",
        type=_positive_int,
        default=None,
        help="maximum duration of each source clip in seconds",
    )
    parser.add_argument(
        "--match-materials-to-script",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="match generated/search materials to script order",
    )
    parser.add_argument(
        "--match-local-clips-to-script-timing",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="trim ordered local clips using estimated script/audio timing",
    )
    parser.add_argument(
        "--video-style-preset",
        default=None,
        choices=[
            "auto",
            "stock_clean",
            "cinematic_vlog",
            "real_life_documentary",
            "minimal_business",
            "shorts_fast",
        ],
        help="style preset used to refine search terms and normalize clips",
    )
    parser.add_argument(
        "--reference-mode-enabled",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="overlay script-matched reference images on the generated video",
    )
    parser.add_argument(
        "--reference-image-sources",
        default=None,
        help="comma-separated reference image sources, e.g. pexels,pixabay,wikimedia",
    )
    parser.add_argument(
        "--reference-image-count",
        type=_reference_image_count,
        default=None,
        help="maximum reference image count, 1-20",
    )
    parser.add_argument(
        "--reference-effect-preset",
        default=None,
        choices=["old_paper_explained"],
        help="reference overlay effect preset",
    )
    parser.add_argument("--voice-name", default="", help="tts voice name")
    parser.add_argument(
        "--voice-volume",
        type=_non_negative_float,
        default=None,
        help="speech volume multiplier",
    )
    parser.add_argument(
        "--voice-rate",
        type=_non_negative_float,
        default=None,
        help="speech rate multiplier",
    )
    parser.add_argument(
        "--bgm-type",
        type=_bgm_type,
        default=None,
        metavar="{none,random,custom}",
        help="background music mode",
    )
    parser.add_argument("--bgm-file", default=None, help="custom background music file")
    parser.add_argument(
        "--bgm-volume",
        type=_non_negative_float,
        default=None,
        help="background music volume multiplier",
    )
    parser.add_argument(
        "--subtitle-enabled",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="enable subtitles (default: enabled, use --no-subtitle-enabled to disable)",
    )
    parser.add_argument("--font-name", default=None, help="subtitle font file name")
    parser.add_argument(
        "--subtitle-position",
        choices=["top", "center", "bottom", "custom"],
        default=None,
        help="subtitle position",
    )
    parser.add_argument(
        "--custom-position",
        type=_percent_position,
        default=None,
        help="custom subtitle position as percent from top, 0-100",
    )
    parser.add_argument(
        "--text-fore-color",
        type=_hex_color,
        default=None,
        help="subtitle text color in #RRGGBB format",
    )
    parser.add_argument(
        "--font-size", type=_positive_int, default=None, help="subtitle font size"
    )
    parser.add_argument(
        "--stroke-color",
        type=_hex_color,
        default=None,
        help="subtitle outline color in #RRGGBB format",
    )
    parser.add_argument(
        "--stroke-width",
        type=_non_negative_float,
        default=None,
        help="subtitle outline width",
    )
    parser.add_argument(
        "--subtitle-background-enabled",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="enable subtitle background",
    )
    parser.add_argument(
        "--subtitle-background-color",
        type=_hex_color,
        default=None,
        help="subtitle background color in #RRGGBB format",
    )
    parser.add_argument(
        "--rounded-subtitle-background",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="enable rounded translucent subtitle background",
    )
    parser.add_argument("--task-id", default="", help="custom task id")
    argv_list = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv_list)

    if args.project:
        provided_options = {
            token.split("=", 1)[0]
            for token in argv_list
            if token.startswith("--")
        }
        allowed_destinations = {
            "project",
            "validate_only",
            "plan_only",
            "acquire_broll_only",
            "render_motion_only",
            "acquire_evidence_only",
            "run_all",
            "export_editor_package",
            "assemble_final",
            "output_dir",
            "task_id",
            "stop_at",
        }
        for action in parser._actions:
            if action.dest in allowed_destinations or not action.option_strings:
                continue
            if any(option in provided_options for option in action.option_strings):
                parser.error(
                    f"{next(option for option in action.option_strings if option in provided_options)} "
                    "cannot be used together with --project"
                )
        if args.validate_only and args.plan_only:
            parser.error("--validate-only cannot be combined with --plan-only")
        if args.validate_only and args.acquire_broll_only:
            parser.error("--validate-only cannot be combined with --acquire-broll-only")
        if args.validate_only and args.render_motion_only:
            parser.error("--validate-only cannot be combined with --render-motion-only")
        if args.validate_only and args.acquire_evidence_only:
            parser.error("--validate-only cannot be combined with --acquire-evidence-only")
        if args.validate_only and args.run_all:
            parser.error("--validate-only cannot be combined with --run-all")
        if args.validate_only and args.export_editor_package:
            parser.error("--validate-only cannot be combined with --export-editor-package")
        if args.validate_only and args.assemble_final:
            parser.error("--validate-only cannot be combined with --assemble-final")
        if args.plan_only and args.acquire_broll_only:
            parser.error("--plan-only cannot be combined with --acquire-broll-only")
        if args.plan_only and args.render_motion_only:
            parser.error("--plan-only cannot be combined with --render-motion-only")
        if args.plan_only and args.acquire_evidence_only:
            parser.error("--plan-only cannot be combined with --acquire-evidence-only")
        if args.plan_only and args.run_all:
            parser.error("--plan-only cannot be combined with --run-all")
        if args.plan_only and args.export_editor_package:
            parser.error("--plan-only cannot be combined with --export-editor-package")
        if args.plan_only and args.assemble_final:
            parser.error("--plan-only cannot be combined with --assemble-final")
        if args.acquire_broll_only and args.render_motion_only:
            parser.error("--acquire-broll-only cannot be combined with --render-motion-only")
        if args.acquire_broll_only and args.acquire_evidence_only:
            parser.error("--acquire-broll-only cannot be combined with --acquire-evidence-only")
        if args.acquire_broll_only and args.run_all:
            parser.error("--acquire-broll-only cannot be combined with --run-all")
        if args.acquire_broll_only and args.export_editor_package:
            parser.error("--acquire-broll-only cannot be combined with --export-editor-package")
        if args.acquire_broll_only and args.assemble_final:
            parser.error("--acquire-broll-only cannot be combined with --assemble-final")
        if args.render_motion_only and args.acquire_evidence_only:
            parser.error("--render-motion-only cannot be combined with --acquire-evidence-only")
        if args.render_motion_only and args.run_all:
            parser.error("--render-motion-only cannot be combined with --run-all")
        if args.render_motion_only and args.export_editor_package:
            parser.error("--render-motion-only cannot be combined with --export-editor-package")
        if args.render_motion_only and args.assemble_final:
            parser.error("--render-motion-only cannot be combined with --assemble-final")
        if args.acquire_evidence_only and args.run_all:
            parser.error("--acquire-evidence-only cannot be combined with --run-all")
        if args.acquire_evidence_only and args.export_editor_package:
            parser.error("--acquire-evidence-only cannot be combined with --export-editor-package")
        if args.acquire_evidence_only and args.assemble_final:
            parser.error("--acquire-evidence-only cannot be combined with --assemble-final")
        if args.output_dir and not (args.export_editor_package or args.assemble_final):
            parser.error("--output-dir requires --export-editor-package or --assemble-final")
        if args.plan_only and "--stop-at" in provided_options:
            parser.error("--stop-at cannot be used together with --plan-only")
        if args.acquire_broll_only and "--stop-at" in provided_options:
            parser.error("--stop-at cannot be used together with --acquire-broll-only")
        if args.render_motion_only and "--stop-at" in provided_options:
            parser.error("--stop-at cannot be used together with --render-motion-only")
        if args.acquire_evidence_only and "--stop-at" in provided_options:
            parser.error("--stop-at cannot be used together with --acquire-evidence-only")
        if args.run_all and "--stop-at" in provided_options:
            parser.error("--stop-at cannot be used together with --run-all")
        if args.export_editor_package and not args.run_all and "--stop-at" in provided_options:
            parser.error("--stop-at cannot be used together with --export-editor-package")
        if args.assemble_final and not args.run_all and "--stop-at" in provided_options:
            parser.error("--stop-at cannot be used together with --assemble-final")
    elif args.validate_only:
        parser.error("--validate-only requires --project")
    elif args.plan_only:
        parser.error("--plan-only requires --project")
    elif args.acquire_broll_only:
        parser.error("--acquire-broll-only requires --project")
    elif args.render_motion_only:
        parser.error("--render-motion-only requires --project")
    elif args.acquire_evidence_only:
        parser.error("--acquire-evidence-only requires --project")
    elif args.run_all:
        parser.error("--run-all requires --project")
    elif args.export_editor_package:
        parser.error("--export-editor-package requires --project")
    elif args.assemble_final:
        parser.error("--assemble-final requires --project")
    elif args.output_dir:
        parser.error("--output-dir requires --project and --export-editor-package")
    elif args.render_motion_demo:
        return args
    elif not args.video_subject:
        parser.error("--video-subject is required unless --project is provided")

    if not args.project and args.video_source == "local" and not (args.video_materials or "").strip():
        parser.error("--video-materials is required when --video-source is local")

    if not args.project and args.video_source == "local" and args.stop_at == "terms":
        parser.error(
            "--stop-at terms has no effect with --video-source local "
            "(search terms are not generated for local sources)"
        )

    return args


def build_video_params(args: argparse.Namespace) -> VideoParams:
    video_terms = args.video_terms
    if video_terms:
        video_terms = [term.strip() for term in video_terms.split(",") if term.strip()]

    video_materials = None
    materials_arg = args.video_materials or ""
    if materials_arg.strip():
        video_materials = [
            # Actual duration will be detected during video processing; use 0 as placeholder.
            MaterialInfo(provider="local", url=item.strip(), duration=0)
            for item in materials_arg.split(",")
            if item.strip()
        ]

    params_kwargs = {
        "video_subject": args.video_subject,
        "video_script": args.video_script,
        "video_terms": video_terms,
        "video_source": args.video_source,
        "video_materials": video_materials,
        "video_count": args.video_count,
        "video_aspect": args.video_aspect,
        "voice_name": args.voice_name,
        "subtitle_enabled": args.subtitle_enabled,
    }

    optional_arg_names = [
        "video_language",
        "paragraph_number",
        "video_script_prompt",
        "custom_system_prompt",
        "video_concat_mode",
        "video_transition_mode",
        "video_clip_duration",
        "match_materials_to_script",
        "match_local_clips_to_script_timing",
        "video_style_preset",
        "reference_mode_enabled",
        "reference_image_sources",
        "reference_image_count",
        "reference_effect_preset",
        "voice_volume",
        "voice_rate",
        "bgm_type",
        "bgm_file",
        "bgm_volume",
        "font_name",
        "subtitle_position",
        "custom_position",
        "text_fore_color",
        "font_size",
        "stroke_color",
        "stroke_width",
        "rounded_subtitle_background",
    ]
    for name in optional_arg_names:
        value = getattr(args, name)
        if value is not None:
            params_kwargs[name] = value

    if args.subtitle_background_enabled is False:
        params_kwargs["text_background_color"] = False
        params_kwargs["rounded_subtitle_background"] = False
    elif args.subtitle_background_color is not None:
        params_kwargs["text_background_color"] = args.subtitle_background_color
    elif args.subtitle_background_enabled is True:
        params_kwargs["text_background_color"] = True

    return VideoParams(**params_kwargs)


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.render_motion_demo:
        from app.services.motion_demo_gallery import render_all_g18_demos
        rendered = render_all_g18_demos(output_dir=args.output_dir or "storage/demo/g18")
        print(json.dumps({"rendered_demos": rendered, "total": len(rendered)}, ensure_ascii=False))
        return 0

    if args.project:
        try:
            project = load_project_spec(args.project)
            preflight_project(project, str(Path(args.project).expanduser().resolve().parent))
            if args.validate_only:
                print(
                    json.dumps(
                        {
                            "valid": True,
                            "schema_version": project.schema_version,
                            "title": project.project.title,
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            if args.plan_only:
                result = run_project_plan(
                    args.project,
                    task_id=args.task_id or None,
                )
                print(json.dumps(result, ensure_ascii=False))
                return 0
            if args.acquire_broll_only:
                from app.services.broll_runner import run_broll_acquisition

                result = run_broll_acquisition(
                    args.project,
                    task_id=args.task_id or None,
                )
                print(json.dumps(result, ensure_ascii=False))
                return 0
            if args.render_motion_only:
                from app.services.motion_runner import run_motion_render

                result = run_motion_render(
                    args.project,
                    task_id=args.task_id or None,
                )
                print(json.dumps(result, ensure_ascii=False))
                return 0
            if args.acquire_evidence_only:
                from app.services.evidence_runner import run_evidence_acquisition

                result = run_evidence_acquisition(
                    args.project,
                    task_id=args.task_id or None,
                )
                print(json.dumps(result, ensure_ascii=False))
                return 0
            if args.run_all and args.export_editor_package and args.assemble_final:
                from app.services.scene_orchestrator import run_all_project
                from app.services.export_runner import export_editor_package
                from app.services.assembly_runner import assemble_final_video

                run_res = run_all_project(
                    args.project,
                    task_id=args.task_id or None,
                )
                if run_res.get("status") != "complete":
                    print(json.dumps(run_res, ensure_ascii=False))
                    return 1
                export_res = export_editor_package(
                    args.project,
                    task_id=run_res.get("task_id") or args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                if export_res.status not in ("complete", "partial"):
                    print(json.dumps(export_res.model_dump(mode="json"), ensure_ascii=False))
                    return 1
                asm_res = assemble_final_video(
                    args.project,
                    task_id=run_res.get("task_id") or args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                print(json.dumps(asm_res.model_dump(mode="json"), ensure_ascii=False))
                return 0 if asm_res.status == "complete" else 1

            if args.run_all and args.assemble_final:
                from app.services.scene_orchestrator import run_all_project
                from app.services.assembly_runner import assemble_final_video

                run_res = run_all_project(
                    args.project,
                    task_id=args.task_id or None,
                )
                if run_res.get("status") != "complete":
                    print(json.dumps(run_res, ensure_ascii=False))
                    return 1
                asm_res = assemble_final_video(
                    args.project,
                    task_id=run_res.get("task_id") or args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                print(json.dumps(asm_res.model_dump(mode="json"), ensure_ascii=False))
                return 0 if asm_res.status == "complete" else 1

            if args.export_editor_package and args.assemble_final:
                from app.services.export_runner import export_editor_package
                from app.services.assembly_runner import assemble_final_video

                export_res = export_editor_package(
                    args.project,
                    task_id=args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                if export_res.status not in ("complete", "partial"):
                    print(json.dumps(export_res.model_dump(mode="json"), ensure_ascii=False))
                    return 1
                asm_res = assemble_final_video(
                    args.project,
                    task_id=args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                print(json.dumps(asm_res.model_dump(mode="json"), ensure_ascii=False))
                return 0 if asm_res.status == "complete" else 1

            if args.assemble_final:
                from app.services.assembly_runner import assemble_final_video

                asm_res = assemble_final_video(
                    args.project,
                    task_id=args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                print(json.dumps(asm_res.model_dump(mode="json"), ensure_ascii=False))
                return 0 if asm_res.status == "complete" else 1

            if args.run_all and args.export_editor_package:
                from app.services.scene_orchestrator import run_all_project
                from app.services.export_runner import export_editor_package

                run_res = run_all_project(
                    args.project,
                    task_id=args.task_id or None,
                )
                if run_res.get("status") != "complete":
                    print(json.dumps(run_res, ensure_ascii=False))
                    return 1
                export_res = export_editor_package(
                    args.project,
                    task_id=run_res.get("task_id") or args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                print(json.dumps(export_res.model_dump(mode="json"), ensure_ascii=False))
                return 0 if export_res.status in ("complete", "partial") else 1

            if args.run_all:
                from app.services.scene_orchestrator import run_all_project

                result = run_all_project(
                    args.project,
                    task_id=args.task_id or None,
                )
                print(json.dumps(result, ensure_ascii=False))
                return 0 if result.get("status") == "complete" else 1

            if args.export_editor_package:
                from app.services.export_runner import export_editor_package

                export_res = export_editor_package(
                    args.project,
                    task_id=args.task_id or None,
                    output_dir=args.output_dir or None,
                )
                print(json.dumps(export_res.model_dump(mode="json"), ensure_ascii=False))
                return 0 if export_res.status in ("complete", "partial") else 1
            result = run_project(
                args.project,
                task_id=args.task_id or None,
                stop_at=args.stop_at,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except ProjectSpecError as exc:
            logger.error(f"Invalid project file: {exc}")
            return 2
        except ProjectRunError as exc:
            logger.error(str(exc))
            return 1

    params = build_video_params(args)
    task_id = args.task_id or utils.get_uuid()
    logger.info(f"start cli task: {task_id}, stop_at: {args.stop_at}")
    result = tm.start(task_id=task_id, params=params, stop_at=args.stop_at)
    if not result:
        logger.error("video generation failed")
        return 1

    print(json.dumps({"task_id": task_id, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
