from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import streamlit as st
from loguru import logger

from app.config import config
from app.models.project import ProjectSpec
from app.models.schema import VideoAspect, VideoConcatMode, VideoSource, VideoTransitionMode
from app.services.assembly_runner import assemble_final_video
from app.services.export_runner import export_editor_package
from app.services.production_workflow import ProductionWorkflowResult, run_production_workflow
from app.services.project_builder import build_project_spec_from_ui
from app.services.project_spec import load_project_spec, save_project_spec
from app.services.scene_orchestrator import sanitize_error_message
from app.utils import utils


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def get_recent_tasks(limit: int = 15) -> list[dict[str, Any]]:
    """Discover recent task directories and summarize their status."""
    tasks_dir = Path(utils.task_dir()).resolve()
    if not tasks_dir.exists() or not tasks_dir.is_dir():
        return []

    discovered: list[dict[str, Any]] = []

    try:
        entries = list(tasks_dir.iterdir())
    except Exception as exc:
        logger.warning(f"Failed to list tasks directory: {exc}")
        return []

    for entry in entries:
        if not entry.is_dir():
            continue

        task_id = entry.name
        # Safe UUID / task directory detection
        is_valid_id = False
        try:
            uuid.UUID(task_id)
            is_valid_id = True
        except ValueError:
            if task_id.startswith("task_") or len(task_id) >= 8:
                is_valid_id = True

        if not is_valid_id:
            continue

        exec_manifest_file = entry / "execution_manifest.json"
        executed_proj_file = entry / "project.executed.json"
        project_json_file = entry / "project.json"

        title = "Untitled Project"
        status = "unknown"
        total_scenes = 0
        ready_scenes = 0
        failed_scenes = 0
        updated_at = entry.stat().st_mtime

        if exec_manifest_file.exists():
            try:
                data = json.loads(exec_manifest_file.read_text(encoding="utf-8-sig"))
                title = data.get("project_title") or title
                status = data.get("status") or status
                scenes = data.get("scenes") or []
                total_scenes = len(scenes)
                ready_scenes = sum(1 for s in scenes if s.get("status") == "ready")
                failed_scenes = sum(1 for s in scenes if s.get("status") == "failed")
                if "created_at" in data:
                    try:
                        updated_at = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")).timestamp()
                    except Exception:
                        pass
            except Exception:
                pass
        elif executed_proj_file.exists():
            try:
                data = json.loads(executed_proj_file.read_text(encoding="utf-8-sig"))
                title = data.get("project", {}).get("title") or title
                total_scenes = len(data.get("visual_cues", []))
                status = "planned"
            except Exception:
                pass
        elif project_json_file.exists():
            try:
                data = json.loads(project_json_file.read_text(encoding="utf-8-sig"))
                title = data.get("project", {}).get("title") or title
                status = "configured"
            except Exception:
                pass
        else:
            # Empty task dir
            continue

        discovered.append({
            "task_id": task_id,
            "title": title,
            "status": status,
            "total_scenes": total_scenes,
            "ready_scenes": ready_scenes,
            "failed_scenes": failed_scenes,
            "updated_at": updated_at,
            "path": str(entry),
        })

    # Sort descending by updated timestamp
    discovered.sort(key=lambda x: x["updated_at"], reverse=True)
    return discovered[:limit]


# ---------------------------------------------------------------------------
# Task Project Path Resolver
# ---------------------------------------------------------------------------

ALLOWED_STORAGE_ROOTS: list[str] = []

def _get_allowed_storage_roots() -> list[Path]:
    """Return the list of allowed storage root directories."""
    roots = [
        Path(utils.storage_dir("tasks", create=False)).resolve(),
        Path(utils.storage_dir("project_inputs", create=False)).resolve(),
    ]
    return [r for r in roots if r.exists()]


def resolve_task_project_path(task_id: str) -> tuple[Path | None, str | None]:
    """
    Resolve the canonical project.json path for a given task ID.

    Searches in priority order:
    1. storage/project_inputs/<task_id>/project.json
    2. storage/tasks/<task_id>/project.json
    3. storage/tasks/<task_id>/project.executed.json (fallback)

    Returns (resolved_path, error_message). If successful, error is None.
    Validates that task_id is a valid UUID or task identifier and that the
    resolved path remains strictly under allowed storage roots.
    """
    # --- Task ID validation ---
    if not task_id or not isinstance(task_id, str):
        return None, "Task ID is empty or invalid."

    task_id_clean = task_id.strip()
    is_valid = False
    try:
        uuid.UUID(task_id_clean)
        is_valid = True
    except ValueError:
        if (task_id_clean.startswith("task_") or len(task_id_clean) >= 8) and ".." not in task_id_clean:
            is_valid = True

    if not is_valid or "/" in task_id_clean or "\\" in task_id_clean or ".." in task_id_clean:
        return None, f"Task ID validation failed: '{task_id}'"

    # --- Candidate resolution ---
    candidates: list[Path] = [
        Path(utils.storage_dir("project_inputs", create=False)) / task_id_clean / "project.json",
        Path(utils.task_dir(task_id_clean)) / "project.json",
        Path(utils.task_dir(task_id_clean)) / "project.executed.json",
    ]

    allowed_roots = _get_allowed_storage_roots()

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue

        if not resolved.exists():
            continue

        # --- Security: must remain under an allowed storage root ---
        is_safe = any(
            str(resolved).startswith(str(root))
            for root in allowed_roots
        ) if allowed_roots else True  # If roots not found yet, relax for init

        if not is_safe:
            return None, f"Path traversal guard triggered for task '{task_id}': {resolved}"

        # --- Try loading the spec to verify it's valid ---
        try:
            load_project_spec(resolved)
        except Exception as exc:
            continue  # Try next candidate

        return resolved, None

    return None, f"No valid project specification found for task '{task_id}'."


def create_editor_package_zip(export_dir: Path | str, destination_zip: Path | str | None = None) -> Path:
    """Create a zip archive of the editor package with relative paths and path traversal protection."""
    src_dir = Path(export_dir).resolve()
    if not src_dir.exists() or not src_dir.is_dir():
        raise FileNotFoundError(f"Export directory not found: {src_dir}")

    if destination_zip:
        dest_zip = Path(destination_zip).resolve()
    else:
        dest_zip = src_dir.parent / f"{src_dir.name}.zip"

    dest_zip.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(src_dir):
            for file in files:
                file_path = Path(root) / file
                rel_path = file_path.relative_to(src_dir)
                rel_str = str(rel_path).replace("\\", "/")

                # Path traversal guard
                if rel_str.startswith("..") or Path(rel_str).is_absolute():
                    raise ValueError(f"Unsafe path in editor package: {rel_str}")

                zipf.write(file_path, arcname=rel_str)

    return dest_zip


def save_uploaded_file(uploaded_file: Any, target_dir: Path | str, allowed_extensions: set[str] | None = None) -> Path:
    """Safely save a Streamlit uploaded file into the target directory with strict filename sanitization."""
    raw_name = getattr(uploaded_file, "name", "uploaded_file")
    # Normalize backslashes (Windows) to forward slashes so basename works consistently across platforms
    clean_name = str(raw_name).replace("\\", "/")
    safe_name = Path(clean_name).name
    safe_name = os.path.basename(safe_name)

    if not safe_name or safe_name in (".", ".."):
        raise ValueError(f"Invalid file name: {raw_name}")

    if allowed_extensions:
        suffix = Path(safe_name).suffix.lower()
        normalized_allowed = {
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in allowed_extensions
        }
        if suffix not in normalized_allowed:
            raise ValueError(f"Extension '{suffix}' is not permitted. Allowed: {allowed_extensions}")

    target_dir_path = Path(target_dir).resolve()
    target_dir_path.mkdir(parents=True, exist_ok=True)

    dest_path = (target_dir_path / safe_name).resolve()

    # Traversal security check
    try:
        dest_path.relative_to(target_dir_path)
    except ValueError:
        raise ValueError(f"Path traversal detected for file: {raw_name}")

    if hasattr(uploaded_file, "getbuffer"):
        content = bytes(uploaded_file.getbuffer())
    elif hasattr(uploaded_file, "read"):
        content = uploaded_file.read()
        if isinstance(content, str):
            content = content.encode("utf-8")
    elif isinstance(uploaded_file, (bytes, bytearray)):
        content = bytes(uploaded_file)
    else:
        content = b""

    dest_path.write_bytes(content)
    return dest_path


def check_providers_readiness() -> dict[str, dict[str, Any]]:
    """Inspect configured external services, media providers, and local tools."""
    app_cfg = getattr(config, "app", {})

    # 1. LLM
    llm_provider = app_cfg.get("llm_provider", "openai")
    has_llm_key = bool(
        app_cfg.get("openai_api_key")
        or app_cfg.get("moonshot_api_key")
        or app_cfg.get("deepseek_api_key")
        or app_cfg.get("ollama_base_url")
        or os.getenv("OPENAI_API_KEY")
    )
    llm_ready = has_llm_key or bool(app_cfg.get("llm_provider") == "ollama")
    llm_label = f"Configured ({llm_provider})" if llm_ready else "Not Configured"

    # 2. TTS
    tts_provider = app_cfg.get("tts_provider", "edge")
    tts_ready = True  # Edge-TTS works out of the box
    tts_label = f"Ready ({tts_provider})"

    # 3. Pexels
    pexels_keys = app_cfg.get("pexels_api_keys", [])
    pexels_ready = bool(pexels_keys or os.getenv("PEXELS_API_KEY"))
    pexels_label = "API Key Active" if pexels_ready else "No API Key (Mock / Demo)"

    # 4. Pixabay
    pixabay_keys = app_cfg.get("pixabay_api_keys", [])
    pixabay_ready = bool(pixabay_keys or os.getenv("PIXABAY_API_KEY"))
    pixabay_label = "API Key Active" if pixabay_ready else "No API Key"

    # 5. Coverr
    coverr_keys = app_cfg.get("coverr_api_keys", [])
    coverr_ready = bool(coverr_keys or os.getenv("COVERR_API_KEY"))
    coverr_label = "API Key Active" if coverr_ready else "No API Key"

    # 6. FFmpeg
    try:
        ffmpeg_bin = utils.get_ffmpeg_binary()
        ffmpeg_ready = bool(ffmpeg_bin and os.path.exists(ffmpeg_bin))
    except Exception:
        ffmpeg_ready = bool(shutil.which("ffmpeg"))
    ffmpeg_label = "FFmpeg Detected" if ffmpeg_ready else "FFmpeg Missing"

    # 7. Remotion
    root_p = Path(utils.root_dir()).resolve()
    remotion_dir = root_p / "remotion"
    remotion_installed = (remotion_dir / "node_modules").exists()
    has_node = bool(shutil.which("node") or shutil.which("npx"))
    remotion_ready = remotion_installed and has_node
    remotion_label = "Node & Remotion Ready" if remotion_ready else "Setup Required"

    return {
        "llm": {"ready": llm_ready, "label": llm_label},
        "tts": {"ready": tts_ready, "label": tts_label},
        "pexels": {"ready": pexels_ready, "label": pexels_label},
        "pixabay": {"ready": pixabay_ready, "label": pixabay_label},
        "coverr": {"ready": coverr_ready, "label": coverr_label},
        "ffmpeg": {"ready": ffmpeg_ready, "label": ffmpeg_label},
        "remotion": {"ready": remotion_ready, "label": remotion_label},
    }


def format_fallback_badge(scene: dict[str, Any]) -> str | None:
    """Format visual fallback badge if the scene was fallen back during generation."""
    fb = scene.get("fallback_from")
    planned = scene.get("planned_visual_type")
    resolved = scene.get("resolved_visual_type") or scene.get("visual_type")

    if fb:
        return f"{str(fb).upper()} → {str(resolved or 'TEXT').upper()} FALLBACK"
    elif planned and resolved and str(planned).upper() != str(resolved).upper():
        return f"{str(planned).upper()} → {str(resolved).upper()} FALLBACK"

    req_tpl = scene.get("requested_template")
    rend_tpl = scene.get("rendered_template")
    if req_tpl and rend_tpl and str(req_tpl).upper() != str(rend_tpl).upper():
        return f"{str(req_tpl).upper()} → {str(rend_tpl).upper()} FALLBACK"

    if scene.get("fallback_reason") and rend_tpl == "callout" and req_tpl != "callout":
        return "CALLOUT FALLBACK"

    return None


def sanitize_manifest_for_display(data: Any) -> Any:
    """Redact sensitive keys and URLs from manifest objects before UI rendering."""
    if isinstance(data, dict):
        sanitized: dict[str, Any] = {}
        for k, v in data.items():
            key_lower = str(k).lower()
            if any(term in key_lower for term in ("key", "secret", "token", "password", "auth", "bearer")):
                sanitized[k] = "[REDACTED]"
            elif isinstance(v, str) and ("api_key=" in v or "token=" in v or "sig=" in v):
                sanitized[k] = re.sub(r"(api_key|token|sig)=[A-Za-z0-9_\-\.]+", r"\1=[REDACTED]", v)
            else:
                sanitized[k] = sanitize_manifest_for_display(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_manifest_for_display(item) for item in data]
    return data


# ---------------------------------------------------------------------------
# Streamlit Production Workspace View
# ---------------------------------------------------------------------------

def render_production_workspace() -> None:
    """Render the primary Video Research & Asset Builder Production Workspace."""
    st.title("🎬 Production Video Workspace")
    st.caption("Autonomous multi-scene video research, evidence synthesis, motion graphics & assembly pipeline")

    # Session State Initialization
    if "production_task_id" not in st.session_state:
        st.session_state["production_task_id"] = utils.get_uuid()
    if "production_run_result" not in st.session_state:
        st.session_state["production_run_result"] = None
    if "demo_prefill" not in st.session_state:
        st.session_state["demo_prefill"] = False
    # Mode C state
    if "production_loaded_project_path" not in st.session_state:
        st.session_state["production_loaded_project_path"] = None
    if "production_workspace_loaded" not in st.session_state:
        st.session_state["production_workspace_loaded"] = False

    active_task_id = st.session_state["production_task_id"]
    task_storage_dir = Path(utils.task_dir(active_task_id)).resolve()
    project_inputs_dir = Path(utils.storage_dir("project_inputs", create=True)) / active_task_id
    project_inputs_dir.mkdir(parents=True, exist_ok=True)
    spec_save_target = project_inputs_dir / "project.json"

    # Provider Readiness Expander
    with st.expander("⚡ System & Provider Readiness", expanded=False):
        readiness = check_providers_readiness()
        cols = st.columns(len(readiness))
        for col, (provider_name, info) in zip(cols, readiness.items()):
            icon = "🟢" if info["ready"] else "🟡"
            col.metric(
                label=provider_name.upper(),
                value=f"{icon} {info['label']}",
            )

    # Workspace Mode Selector
    input_mode = st.radio(
        "Workflow Configuration Mode",
        ["Mode A: Form Builder (Interactive)", "Mode B: Import project.json", "Mode C: Reopen Task Workspace"],
        horizontal=True,
    )

    configured_spec: ProjectSpec | None = None
    # active_project_path is the canonical spec path for all G08/G09/G10 operations
    active_project_path: Path = spec_save_target

    # -----------------------------------------------------------------------
    # MODE A: FORM BUILDER
    # -----------------------------------------------------------------------
    if "Mode A" in input_mode:
        st.subheader("1. Project Specification")

        # Demo project loader
        col_demo_1, col_demo_2 = st.columns([1, 4])
        with col_demo_1:
            if st.button("🚀 Load Demo Project"):
                st.session_state["demo_prefill"] = True
                st.session_state["demo_title"] = "Why Electric Cars Feel So Fast"
                st.session_state["demo_subject"] = "Why Electric Cars Feel So Fast: Instant Torque & Electric Motors"
                st.session_state["demo_script"] = (
                    "Electric vehicles deliver peak torque instantly from zero RPM, creating an immediate "
                    "sensation of acceleration. Unlike internal combustion engines that require revving through gears, "
                    "direct-drive electric motors achieve maximum power without shifting delays."
                )
                st.session_state["demo_terms"] = "electric car acceleration, electric motor torque, instant power"

        demo_on = st.session_state.get("demo_prefill", False)
        default_title = st.session_state.get("demo_title", "") if demo_on else ""
        default_subject = st.session_state.get("demo_subject", "") if demo_on else ""
        default_script = st.session_state.get("demo_script", "") if demo_on else ""
        default_terms = st.session_state.get("demo_terms", "") if demo_on else ""

        col_a1, col_a2 = st.columns(2)
        with col_a1:
            title_input = st.text_input("Project Title (Optional)", value=default_title, placeholder="e.g. The Science of Speed")
            subject_input = st.text_area("Video Topic / Research Subject *", value=default_subject, placeholder="e.g. Quantum Computing Breakthroughs 2026", height=100)
            search_terms_raw = st.text_input("Search Terms (Comma-separated)", value=default_terms, placeholder="quantum qubits, superconductor, supercomputing")

        with col_a2:
            script_input = st.text_area("Narration Script (Optional)", value=default_script, placeholder="Leave blank to automatically generate narration with LLM...", height=188)

        st.subheader("2. Production & Voice Settings")
        col_p1, col_p2, col_p3 = st.columns(3)
        with col_p1:
            aspect_choice = st.selectbox("Aspect Ratio", ["16:9", "9:16", "1:1"], index=0)
            fps_choice = st.number_input("Frame Rate (FPS)", min_value=15, max_value=60, value=30, step=1)
            language_choice = st.selectbox("Language", ["en-US", "zh-CN", "es-ES", "de-DE", "ja-JP"], index=0)

        with col_p2:
            style_preset = st.selectbox(
                "Visual Style Preset",
                ["auto", "stock_clean", "cinematic_vlog", "real_life_documentary", "minimal_business", "shorts_fast"],
                index=0,
            )
            
            narration_source = st.radio("Narration Source", ["Generated TTS", "External Audio + SRT"], index=0)
            voice_name = ""
            narration_mode_ui = "synthesized"
            custom_audio_path = None
            custom_timing_path = None
            
            if narration_source == "Generated TTS":
                voice_name = st.text_input("Voice Name", value="en-US-JennyNeural-Female")
            else:
                narration_mode_ui = "file"
                ext_audio = st.file_uploader("Upload Audio (WAV/MP3)", type=["wav", "mp3"])
                if ext_audio:
                    ext_audio_p = project_inputs_dir / f"narration{Path(ext_audio.name).suffix}"
                    ext_audio_p.write_bytes(ext_audio.read())
                    st.session_state["narration_audio_path"] = str(ext_audio_p)
                if st.session_state.get("narration_audio_path"):
                    custom_audio_path = st.session_state["narration_audio_path"]
                    st.audio(custom_audio_path)
                
                ext_srt = st.file_uploader("Upload SRT", type=["srt"])
                if ext_srt:
                    ext_srt_p = project_inputs_dir / "narration.srt"
                    ext_srt_p.write_bytes(ext_srt.read())
                    st.session_state["narration_srt_path"] = str(ext_srt_p)
                if st.session_state.get("narration_srt_path"):
                    custom_timing_path = st.session_state["narration_srt_path"]
                    st.success(f"SRT loaded: {Path(custom_timing_path).name}")

            subtitle_enabled = st.checkbox("Burn Subtitles", value=True)

        with col_p3:
            stock_source = st.selectbox("Primary Stock Provider", ["pexels", "pixabay", "coverr", "local"], index=0)
            thread_count = st.number_input("Thread Count", min_value=1, max_value=16, value=4)

        # Advanced Settings Expander
        with st.expander("🛠️ Advanced Production Configuration", expanded=False):
            col_adv1, col_adv2 = st.columns(2)
            with col_adv1:
                clip_duration = st.number_input("Default Clip Duration (s)", min_value=2, max_value=30, value=5)
                match_materials = st.checkbox("Match Materials to Script", value=False)
                match_local_timing = st.checkbox("Match Local Clips to Script Timing", value=False)
                concat_mode = st.selectbox("Video Concat Mode", ["random", "sequential"], index=0)
            with col_adv2:
                transition_mode = st.selectbox("Transition Mode", ["none", "Shuffle", "FadeIn", "FadeOut", "SlideIn", "SlideOut"], index=0)
                ref_mode = st.checkbox("Reference Mode Enabled", value=False)
                ref_sources = st.multiselect("Reference Image Sources", ["pexels", "pixabay", "wikimedia"], default=["pexels", "pixabay", "wikimedia"])
                ref_count = st.number_input("Reference Image Count", min_value=1, max_value=20, value=8)

        # Build Spec from Form
        terms_list = [t.strip() for t in search_terms_raw.split(",") if t.strip()]
        if subject_input.strip():
            try:
                configured_spec = build_project_spec_from_ui(
                    title=title_input or subject_input,
                    subject=subject_input,
                    script=script_input,
                    language=language_choice,
                    aspect_ratio=aspect_choice,
                    fps=int(fps_choice),
                    video_style_preset=style_preset,
                    narration_mode=narration_mode_ui,
                    voice_name=voice_name,
                    custom_audio_file=custom_audio_path,
                    custom_timing_file=custom_timing_path,
                    subtitle_enabled=subtitle_enabled,
                    video_source=stock_source,
                    n_threads=int(thread_count),
                    search_terms=terms_list,
                    video_clip_duration=int(clip_duration),
                    match_materials_to_script=match_materials,
                    match_local_clips_to_script_timing=match_local_timing,
                    video_concat_mode=concat_mode,
                    video_transition_mode=transition_mode,
                    reference_mode_enabled=ref_mode,
                    reference_image_sources=ref_sources,
                    reference_image_count=int(ref_count),
                )
            except Exception as e:
                st.error(f"Specification Validation Error: {e}")

    # -----------------------------------------------------------------------
    # MODE B: IMPORT PROJECT.JSON
    # -----------------------------------------------------------------------
    elif "Mode B" in input_mode:
        st.subheader("Import Project Specification File")
        uploaded_json = st.file_uploader("Upload project.json", type=["json"])
        if uploaded_json is not None:
            try:
                saved_json_path = save_uploaded_file(uploaded_json, project_inputs_dir, allowed_extensions={".json"})
                configured_spec = load_project_spec(saved_json_path)
                st.success(f"Loaded: '{configured_spec.project.title}' ({len(configured_spec.visual_cues)} cues)")
                with st.expander("Preview project.json"):
                    st.json(sanitize_manifest_for_display(configured_spec.model_dump(mode="json")))
            except Exception as exc:
                st.error(f"Failed to parse project.json: {exc}")

    # -----------------------------------------------------------------------
    # MODE C: REOPEN TASK WORKSPACE
    # -----------------------------------------------------------------------
    elif "Mode C" in input_mode:
        st.subheader("Reopen / Resume Task Workspace")
        recent = get_recent_tasks(limit=10)
        options = [f"{t['task_id']} — {t['title']} ({t['status']})" for t in recent]
        if options:
            selected_task_opt = st.selectbox("Select Previous Task", options)
            selected_tid = selected_task_opt.split(" — ")[0]

            if st.button("Load Task Workspace"):
                resolved_p, resolve_err = resolve_task_project_path(selected_tid)
                if resolve_err or resolved_p is None:
                    st.error(f"Cannot load task workspace: {resolve_err or 'Project file not found'}")
                else:
                    # Clear stale run result from a different task
                    prev_run = st.session_state.get("production_run_result")
                    if prev_run and getattr(prev_run, "task_id", None) != selected_tid:
                        st.session_state["production_run_result"] = None

                    st.session_state["production_task_id"] = selected_tid
                    st.session_state["production_loaded_project_path"] = str(resolved_p)
                    st.session_state["production_workspace_loaded"] = True
                    st.rerun()
        else:
            st.info("No previous tasks found in storage/tasks.")

        # Reload spec from persisted path on every render (survives st.rerun)
        loaded_path_str = st.session_state.get("production_loaded_project_path")
        workspace_loaded = st.session_state.get("production_workspace_loaded", False)
        if workspace_loaded and loaded_path_str:
            try:
                loaded_path = Path(loaded_path_str).resolve()
                configured_spec = load_project_spec(loaded_path)
                active_project_path = loaded_path

                # Display Workspace Loaded Banner
                task_exec_manifest = task_storage_dir / "execution_manifest.json"
                task_status = "unknown"
                if task_exec_manifest.exists():
                    try:
                        _em = json.loads(task_exec_manifest.read_text(encoding="utf-8-sig"))
                        task_status = (_em.get("status") or "unknown").upper()
                    except Exception:
                        pass
                st.success(
                    f"Workspace Loaded ✅\n\n"
                    f"**Task:** `{active_task_id}`\n\n"
                    f"**Project:** {configured_spec.project.title}\n\n"
                    f"**Status:** {task_status}\n\n"
                    f"**Narration Mode:** {configured_spec.narration.mode.value.upper()}\n\n"
                    f"**Spec:** `{Path(loaded_path_str).name}`"
                )
            except Exception as exc:
                st.error(f"Failed to reload workspace spec: {sanitize_error_message(str(exc))}")
                st.session_state["production_workspace_loaded"] = False
                st.session_state["production_loaded_project_path"] = None
                configured_spec = None

    # -----------------------------------------------------------------------
    # Evidence & Media Assets Upload Section
    # -----------------------------------------------------------------------
    with st.expander("📁 Optional Evidence & Media Attachments", expanded=False):
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            sources_file = st.file_uploader("Upload sources.json (Evidence Registry)", type=["json"])
            if sources_file:
                save_uploaded_file(sources_file, project_inputs_dir, allowed_extensions={".json"})
                st.success("Saved sources.json")

            evidence_files = st.file_uploader("Upload Evidence Documents / Images (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
            if evidence_files:
                for ef in evidence_files:
                    save_uploaded_file(ef, project_inputs_dir)
                st.success(f"Saved {len(evidence_files)} evidence files")

        with col_u2:
            st.info("Additional media support arriving soon.")

    # -----------------------------------------------------------------------
    # Output Target & Execution
    # -----------------------------------------------------------------------
    st.write("---")
    st.subheader("3. Execution Target & Launch")
    target_stage = st.radio(
        "Output Stage Target",
        [
            "Final Video (G08 → G09 → G10 Assembly)",
            "Editor Package (G08 → G09 Modular Export)",
            "Scene Assets Only (G08 Research & Generation)",
        ],
        index=0,
    )

    stage_map = {
        "Final Video (G08 → G09 → G10 Assembly)": "final_video",
        "Editor Package (G08 → G09 Modular Export)": "editor_package",
        "Scene Assets Only (G08 Research & Generation)": "scene_assets",
    }
    output_target = stage_map.get(target_stage, "final_video")

    # Run Button
    col_run_1, col_run_2 = st.columns([2, 5])
    with col_run_1:
        run_clicked = st.button("🚀 Start Production Workflow", type="primary", use_container_width=True)

    progress_container = st.container()

    if run_clicked:
        if configured_spec is None:
            st.error("Please configure a valid project specification before starting.")
        else:
            # For Mode A and Mode B: persist spec to inputs dir and task dir
            # For Mode C: active_project_path already points to the task's original project.json
            if not st.session_state.get("production_workspace_loaded", False):
                save_project_spec(configured_spec, spec_save_target)
                save_project_spec(configured_spec, task_storage_dir / "project.json")
                # Copy any uploaded evidence sources into the task workspace
                if (project_inputs_dir / "sources.json").exists():
                    shutil.copy2(project_inputs_dir / "sources.json", task_storage_dir / "sources.json")

            with progress_container:
                progress_bar = st.progress(0, text="Initializing workflow coordinator...")
                status_text = st.empty()

                def _on_progress_ui(info: dict[str, Any]) -> None:
                    pct = info.get("progress_percent", 0)
                    stg = info.get("stage", "processing")
                    stat = info.get("status", "")
                    progress_bar.progress(min(100, max(0, pct)), text=f"Stage: {stg.upper()} ({stat})")
                    status_text.text(f"Current stage: {stg} — {stat}")

                try:
                    wf_result = run_production_workflow(
                        project_path=active_project_path,
                        task_id=active_task_id,
                        output_target=output_target,
                        on_progress=_on_progress_ui,
                    )
                    st.session_state["production_run_result"] = wf_result
                    progress_bar.progress(100, text="Workflow execution complete!")
                    st.success("Workflow completed!")
                    st.rerun()
                except Exception as run_exc:
                    st.error(f"Workflow execution failed: {run_exc}")
                    logger.error(f"Production UI workflow exception: {run_exc}")

    # -----------------------------------------------------------------------
    # Results & Inspection Dashboard
    # -----------------------------------------------------------------------
    exec_manifest_path = task_storage_dir / "execution_manifest.json"
    if exec_manifest_path.exists():
        st.write("---")
        st.header("📊 Task Results & Review")

        wf_res = st.session_state.get("production_run_result")
        if wf_res and getattr(wf_res, "task_id", None) == active_task_id and not getattr(wf_res, "is_success", True):
            err_text = sanitize_error_message(wf_res.error or "Stage execution incomplete")
            st.error(
                f"Production Workflow Incomplete ({wf_res.failed_stage or 'stage error'})\n\n"
                f"Reason: {err_text}\n\n"
                f"Task: `{active_task_id}`"
            )
            if "stale scene media" in err_text.lower() or "stale scene asset" in err_text.lower():
                st.warning("⚠️ Scene assets were generated with older timing. Resume Production to rebuild stale scenes.")

        try:
            manifest_data = json.loads(exec_manifest_path.read_text(encoding="utf-8-sig"))
        except Exception:
            manifest_data = {}

        scenes_list = manifest_data.get("scenes", [])
        showing_prior = False
        if not scenes_list:
            prior_manifest_path = task_storage_dir / "execution_manifest.prior.json"
            if prior_manifest_path.exists():
                try:
                    prior_data = json.loads(prior_manifest_path.read_text(encoding="utf-8-sig"))
                    if prior_data.get("scenes"):
                        scenes_list = prior_data.get("scenes", [])
                        showing_prior = True
                except Exception:
                    pass

        total_count = len(scenes_list)
        ready_count = sum(1 for s in scenes_list if s.get("status") == "ready")
        failed_count = sum(1 for s in scenes_list if s.get("status") == "failed")
        overall_status = manifest_data.get("status", "unknown").upper()

        # KPI Metrics
        kpi_cols = st.columns(6)
        kpi_cols[0].metric("Status", overall_status)
        kpi_cols[1].metric("Task ID", active_task_id[:8])
        kpi_cols[2].metric("Total Scenes", total_count)
        kpi_cols[3].metric("Ready", ready_count)
        kpi_cols[4].metric("Failed", failed_count)
        kpi_cols[5].metric("FPS", manifest_data.get("fps", 30))

        # Fallback ratio quality warning
        fallback_count = sum(1 for s in scenes_list if s.get("fallback_from"))
        if total_count > 0 and fallback_count > 0 and (fallback_count / total_count) >= 0.5:
            st.warning(
                f"⚠️ Visual planning used deterministic fallback for {fallback_count}/{total_count} scenes. "
                f"Review planner diagnostics; rich motion opportunities may have been reduced."
            )

        # Scene Review Grid
        st.subheader("Scene Asset Grid")
        if showing_prior:
            st.info("ℹ️ Displaying prior scene artifacts from previous execution snapshot.")
        if scenes_list:
            for scene in scenes_list:
                s_id = scene.get("scene_id", "scene")
                order = scene.get("order", 0)
                v_type = (scene.get("resolved_visual_type") or scene.get("planned_visual_type", "BROLL")).upper()
                s_status = scene.get("status", "failed")
                dur = scene.get("duration_frames", 0) / float(manifest_data.get("fps", 30))
                fb_badge = format_fallback_badge(scene)

                badge_str = f"`{v_type}`"
                if fb_badge:
                    badge_str += f" ⚠️ `{fb_badge}`"

                with st.expander(f"Scene {order:02d} [{s_id}] — {badge_str} ({dur:.1f}s) — Status: {s_status.upper()}", expanded=(s_status != "ready")):
                    col_sc1, col_sc2 = st.columns([3, 2])
                    with col_sc1:
                        out_f = scene.get("output_file")
                        if s_status == "ready" and out_f and Path(out_f).exists():
                            st.video(str(out_f))
                        elif s_status == "failed":
                            st.error(f"Generation Failed: {scene.get('error', 'Unknown scene failure')}")
                            if scene.get("planned_visual_type"):
                                st.caption(f"Planned: `{scene.get('planned_visual_type')}` | Stage: `{scene.get('source_stage', 'unknown')}` | Attempts: {scene.get('attempts', 1)}")
                        else:
                            st.warning(f"Clip output unavailable: {out_f}")

                    with col_sc2:
                        st.markdown(f"**Visual Type:** {v_type}")
                        if scene.get("visual_group_id"):
                            st.markdown(f"**Visual Group:** `{scene.get('visual_group_id')}`")
                        st.markdown(f"**Duration:** {dur:.2f}s ({scene.get('duration_frames', 0)} frames)")
                        st.markdown(f"**Time range:** {scene.get('start', 0.0):.2f}s → {scene.get('end', 0.0):.2f}s")
                        if scene.get("narration"):
                            st.caption(f"🗣️ *\"{scene.get('narration')}\"*")
                        if scene.get("purpose"):
                            st.markdown(f"**Purpose:** {scene.get('purpose')}")

                        # B-roll V2 Diagnostics
                        if v_type == "BROLL":
                            b_meta = scene.get("metadata") or {}
                            if not b_meta and out_f:
                                meta_json_p = Path(out_f).parent / "metadata.json"
                                if meta_json_p.exists():
                                    try:
                                        b_meta = json.loads(meta_json_p.read_text(encoding="utf-8-sig")).get("metadata", {})
                                    except Exception:
                                        pass

                            conf = b_meta.get("semantic_confidence")
                            if conf:
                                conf_color = "green" if conf == "HIGH" else ("orange" if conf == "MEDIUM" else "red")
                                st.markdown(f"**Confidence:** :{conf_color}[**{conf}**]")

                            q_tier = b_meta.get("query_tier")
                            if q_tier:
                                st.markdown(f"**Query Tier:** `{q_tier}`")

                            p_query = b_meta.get("primary_query")
                            q_used = scene.get("query_used") or b_meta.get("query_stage")
                            if p_query:
                                st.markdown(f"**Primary Query:** `{p_query}`")
                            if q_used and q_used != p_query:
                                st.markdown(f"**Query Used:** `{q_used}`")

                            matched = b_meta.get("matched_concepts")
                            if matched:
                                st.markdown(f"**Matched Concepts:** `{'`, `'.join(matched)}`")

                            missing = b_meta.get("missing_concepts")
                            if missing:
                                st.markdown(f"**Missing Concepts:** :red[`{'`, `'.join(missing)}`]")

                        # Motion / DATA Diagnostics
                        elif v_type in ("DATA", "TEXT"):
                            req_tpl = scene.get("requested_template")
                            rend_tpl = scene.get("rendered_template")
                            if req_tpl:
                                st.markdown(f"**Template:** `{req_tpl}`" + (f" → `{rend_tpl}`" if rend_tpl and rend_tpl != req_tpl else ""))
                            fb_r = scene.get("fallback_reason")
                            if fb_r:
                                st.warning(f"Fallback reason: {fb_r}")

        # Editor Package & Assembly Downloader
        st.subheader("📦 Package Export & Final Video")
        col_act1, col_act2 = st.columns(2)

        with col_act1:
            st.markdown("### Editor Package (G09)")
            exp_btn = st.button("Re-export Editor Package")
            if exp_btn:
                try:
                    res = export_editor_package(active_project_path, task_id=active_task_id)
                    st.success(f"Editor package exported to: {res.export_dir}")
                except Exception as ex:
                    st.error(f"Export failed: {ex}")

            # Check if editor package exists for download
            slug = manifest_data.get("project_title", "project").strip().lower().replace(" ", "-")
            export_path_candidates = [
                Path.cwd() / "exports" / slug,
                Path(utils.task_dir(active_task_id)) / "exports" / slug,
            ]
            valid_export_dir = next((p for p in export_path_candidates if p.exists()), None)

            if valid_export_dir:
                try:
                    zip_path = create_editor_package_zip(valid_export_dir)
                    with open(zip_path, "rb") as zf:
                        st.download_button(
                            label="⬇️ Download Editor Package ZIP",
                            data=zf.read(),
                            file_name=f"{slug}_editor_package.zip",
                            mime="application/zip",
                        )
                except Exception as ze:
                    logger.warning(f"Could not build zip: {ze}")

        with col_act2:
            st.markdown("### Final Video Assembly (G10)")
            ass_btn = st.button("Assemble Final Video")
            if ass_btn:
                try:
                    res_ass = assemble_final_video(active_project_path, task_id=active_task_id)
                    qc_data = None
                    if res_ass.qc_report_file and Path(res_ass.qc_report_file).exists():
                        try:
                            qc_data = json.loads(Path(res_ass.qc_report_file).read_text(encoding="utf-8-sig"))
                        except Exception:
                            pass
                    if res_ass.status != "complete" or (qc_data and not qc_data.get("is_valid", True)):
                        err_msg = res_ass.error or ("; ".join(qc_data.get("errors", [])) if qc_data else "Final assembly failed")
                        st.error(
                            f"Final Assembly Failed\n\n"
                            f"Reason: {sanitize_error_message(err_msg)}\n\n"
                            f"Task: `{active_task_id}`"
                        )
                        if res_ass.qc_report_file:
                            st.caption(f"QC Report: `{res_ass.qc_report_file}`")
                    else:
                        st.success(f"Final video assembled: {res_ass.final_video_file}")
                except Exception as ea:
                    st.error(
                        f"Final Assembly Failed\n\n"
                        f"Reason: {sanitize_error_message(str(ea))}\n\n"
                        f"Task: `{active_task_id}`"
                    )

            # Final video player
            final_mp4_candidates = [
                valid_export_dir / "final" / "final.mp4" if valid_export_dir else None,
                task_storage_dir / "final" / "final.mp4",
                Path.cwd() / "exports" / slug / "final" / "final.mp4",
            ]
            final_video_file = next((f for f in final_mp4_candidates if f and f.exists()), None)
            if final_video_file:
                st.video(str(final_video_file))
                st.caption(f"Path: {final_video_file}")

        # Execution Details JSON View
        with st.expander("🔍 Raw Execution Manifest (Sanitized)", expanded=False):
            st.json(sanitize_manifest_for_display(manifest_data))
