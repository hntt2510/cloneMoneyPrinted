from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pymupdf
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.models.evidence import EvidenceBBox, SelectedEvidenceAsset
from app.models.project import VisualCue
from app.utils import utils


class EvidenceRenderValidationError(ValueError):
    """Raised when rendered evidence video output fails resolution, fps, duration, or audio checks."""


def compute_evidence_spec_fingerprint(
    scene_id: str,
    search_query: str,
    highlight_target: str | None,
    source_id: str,
    source_sha256: str | None,
    page_number: int | None,
    match_type: str,
    highlight_boxes: list[EvidenceBBox] | list[dict[str, float]],
    duration_frames: int,
    fps: int,
    width: int,
    height: int,
    render_mode: str,
    title: str = "",
    publisher: str | None = None,
    trust: str = "",
    license: str | None = None,
    matched_text: str | None = None,
) -> str:
    """Compute deterministic SHA-256 fingerprint for an evidence scene specification."""
    clean_boxes = []
    for b in highlight_boxes:
        if isinstance(b, EvidenceBBox):
            clean_boxes.append(b.model_dump(mode="json"))
        elif isinstance(b, dict):
            clean_boxes.append({k: round(float(v), 4) for k, v in sorted(b.items())})

    canonical = {
        "scene_id": scene_id,
        "search_query": search_query,
        "highlight_target": highlight_target or "",
        "source_id": source_id,
        "source_sha256": source_sha256 or "",
        "page_number": page_number or 0,
        "match_type": match_type,
        "highlight_boxes": clean_boxes,
        "duration_frames": duration_frames,
        "fps": fps,
        "width": width,
        "height": height,
        "render_mode": render_mode,
        "title": title,
        "publisher": publisher or "",
        "trust": trust,
        "license": license or "",
        "matched_text": matched_text or "",
    }
    dumped = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def validate_rendered_evidence_clip(
    rendered_path: Path | str,
    expected_duration_frames: int,
    expected_width: int,
    expected_height: int,
    expected_fps: int = 30,
) -> float:
    """Strictly validate rendered evidence clip against target resolution, fps, duration, and audio absence."""
    dest = Path(rendered_path).resolve()
    if not dest.exists() or dest.stat().st_size == 0:
        raise EvidenceRenderValidationError(f"Rendered evidence file is missing or empty: {dest}")

    clip = None
    try:
        clip = VideoFileClip(str(dest))
        actual_duration = float(clip.duration or 0.0)
        actual_w, actual_h = clip.size
        actual_fps = float(clip.fps or 0.0)
        has_audio = clip.audio is not None

        if actual_duration <= 0 or actual_fps <= 0:
            raise EvidenceRenderValidationError(
                f"Decoded evidence clip has invalid duration ({actual_duration}) or fps ({actual_fps})"
            )

        if actual_w != expected_width or actual_h != expected_height:
            raise EvidenceRenderValidationError(
                f"Resolution mismatch: expected {expected_width}x{expected_height}, got {actual_w}x{actual_h}"
            )

        if abs(actual_fps - expected_fps) > 2.0:
            raise EvidenceRenderValidationError(
                f"FPS mismatch: expected ~{expected_fps}, got {actual_fps:.2f}"
            )

        expected_duration = expected_duration_frames / float(expected_fps)
        tolerance = max(1.0 / expected_fps, 0.05)
        duration_diff = abs(actual_duration - expected_duration)
        if duration_diff > tolerance:
            raise EvidenceRenderValidationError(
                f"Duration mismatch: expected {expected_duration:.3f}s ({expected_duration_frames} frames), "
                f"got {actual_duration:.3f}s (diff {duration_diff:.3f}s > tolerance {tolerance:.3f}s)"
            )

        if has_audio:
            raise EvidenceRenderValidationError("Evidence clip must not contain an audio stream")

        return actual_duration
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass


# --- Font Helpers ---

def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load default or system TrueType font safely."""
    font_candidates = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


# --- PDF Page & Image Rasterization ---

def render_pdf_page_to_image(
    pdf_path: Path | str,
    page_number: int = 1,
    target_long_edge: int = 2000,
) -> Image.Image:
    """Rasterize a single PDF page at high DPI for readable evidence display."""
    doc = None
    try:
        doc = pymupdf.open(str(Path(pdf_path).resolve()))
        idx = max(0, min(len(doc) - 1, page_number - 1))
        page = doc[idx]
        rect = page.rect
        orig_long = max(float(rect.width), float(rect.height), 1.0)
        zoom = max(1.0, float(target_long_edge) / orig_long)
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")
        return Image.open(io.BytesIO(img_bytes)).convert("RGB")
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def apply_highlight_overlay(
    base_image: Image.Image,
    boxes: list[EvidenceBBox] | list[dict[str, float]],
    highlight_color: tuple[int, int, int, int] = (255, 215, 0, 100),  # Golden amber fill
    border_color: tuple[int, int, int, int] = (230, 170, 0, 230),     # Solid amber border
) -> Image.Image:
    """Draw semi-transparent highlight rectangles over normalized bounding boxes."""
    if not boxes:
        return base_image.copy()

    rgba_img = base_image.convert("RGBA")
    overlay = Image.new("RGBA", rgba_img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    iw, ih = rgba_img.size
    for b in boxes:
        if isinstance(b, EvidenceBBox):
            bx, by, bw, bh = b.x, b.y, b.width, b.height
        else:
            bx = float(b.get("x", 0.0))
            by = float(b.get("y", 0.0))
            bw = float(b.get("width", 0.0))
            bh = float(b.get("height", 0.0))

        # Convert normalized bounds to pixel coords with slight padding
        pad_x = max(2, int(iw * 0.003))
        pad_y = max(2, int(ih * 0.003))
        px0 = max(0, int(bx * iw) - pad_x)
        py0 = max(0, int(by * ih) - pad_y)
        px1 = min(iw, int((bx + bw) * iw) + pad_x)
        py1 = min(ih, int((by + bh) * ih) + pad_y)

        # Draw filled highlight box
        draw.rectangle([px0, py0, px1, py1], fill=highlight_color, outline=border_color, width=max(2, int(ih * 0.0025)))

    combined = Image.alpha_composite(rgba_img, overlay)
    return combined.convert("RGB")


# --- Composed Document Frame Layout ---

def compose_document_frame(
    annotated_page_img: Image.Image,
    width: int,
    height: int,
    title: str,
    publisher: str | None = None,
    trust: str = "official",
    license_info: str | None = None,
) -> Image.Image:
    """Compose annotated document page into a clean, educational dark-mode presentation frame."""
    frame = Image.new("RGB", (width, height), (15, 17, 23))  # #0f1117 deep slate
    draw = ImageDraw.Draw(frame)

    # Ambient subtle gradient / border glow
    draw.rectangle([0, 0, width, height], fill=(15, 17, 23))
    # Subtle top bar
    draw.rectangle([0, 0, width, max(4, int(height * 0.006))], fill=(59, 130, 246))

    is_portrait = height > width

    # Header Source Badge
    badge_text = "OFFICIAL EVIDENCE" if trust == "official" else "SOURCE EVIDENCE"
    badge_color = (37, 99, 235) if trust == "official" else (16, 185, 129)
    font_badge = _get_font(max(14, int(min(width, height) * 0.022)), bold=True)
    font_title = _get_font(max(18, int(min(width, height) * 0.03)), bold=True)
    font_footer = _get_font(max(13, int(min(width, height) * 0.018)), bold=False)

    top_margin = int(height * (0.04 if is_portrait else 0.05))
    draw.text((int(width * 0.06), top_margin), badge_text, font=font_badge, fill=badge_color)

    # Document Title at top
    clean_title = (title[:65] + "...") if len(title) > 68 else title
    draw.text((int(width * 0.06), top_margin + int(height * 0.035)), clean_title, font=font_title, fill=(243, 244, 246))

    # Calculate page bounding area
    avail_top = top_margin + int(height * 0.08)
    avail_bottom = int(height * 0.92)
    avail_w = int(width * (0.88 if is_portrait else 0.78))
    avail_h = avail_bottom - avail_top

    # Scale annotated page maintaining aspect ratio
    pw, ph = annotated_page_img.size
    scale = min(float(avail_w) / float(pw), float(avail_h) / float(ph))
    target_w = max(10, int(pw * scale))
    target_h = max(10, int(ph * scale))
    resized_page = annotated_page_img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Drop shadow
    shadow_offset = max(6, int(min(width, height) * 0.015))
    pos_x = (width - target_w) // 2
    pos_y = avail_top + (avail_h - target_h) // 2

    # Draw dark shadow
    shadow_img = Image.new("RGBA", (target_w + shadow_offset * 2, target_h + shadow_offset * 2), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_img)
    s_draw.rectangle([shadow_offset // 2, shadow_offset // 2, target_w + shadow_offset // 2, target_h + shadow_offset // 2], fill=(0, 0, 0, 180))
    shadow_blur = shadow_img.filter(ImageFilter.GaussianBlur(radius=shadow_offset // 2))

    frame_rgba = frame.convert("RGBA")
    frame_rgba.paste(shadow_blur, (pos_x - shadow_offset // 2, pos_y - shadow_offset // 2), shadow_blur)
    frame_rgba.paste(resized_page, (pos_x, pos_y))

    # Border around page
    draw_rgba = ImageDraw.Draw(frame_rgba)
    draw_rgba.rectangle([pos_x, pos_y, pos_x + target_w, pos_y + target_h], outline=(75, 85, 99), width=1)

    # Footer source attribution
    footer_text = publisher or "Document Source"
    if license_info:
        footer_text += f" • {license_info}"
    draw_rgba.text((int(width * 0.06), int(height * 0.94)), footer_text, font=font_footer, fill=(156, 163, 175))

    return frame_rgba.convert("RGB")


# --- Composed Webpage Excerpt Card Layout ---

def compose_excerpt_card_frame(
    width: int,
    height: int,
    title: str,
    publisher: str | None,
    excerpt_text: str,
    highlight_target: str | None = None,
    trust: str = "official",
    license_info: str | None = None,
) -> Image.Image:
    """Compose exact extracted text excerpt into an honest, high-credibility source excerpt card."""
    frame = Image.new("RGB", (width, height), (15, 17, 23))  # #0f1117
    draw = ImageDraw.Draw(frame)

    # Subtle top bar
    draw.rectangle([0, 0, width, max(4, int(height * 0.006))], fill=(245, 158, 11))  # Amber bar

    is_portrait = height > width

    # Card dimensions
    card_w = int(width * (0.90 if is_portrait else 0.82))
    card_h = int(height * (0.75 if is_portrait else 0.70))
    card_x = (width - card_w) // 2
    card_y = (height - card_h) // 2

    # Draw card background (#1a1d26) with border (#2e3446)
    draw.rectangle([card_x, card_y, card_x + card_w, card_y + card_h], fill=(26, 29, 38), outline=(46, 52, 70), width=2)

    # Badge in card header
    font_badge = _get_font(max(14, int(min(width, height) * 0.02)), bold=True)
    font_pub = _get_font(max(16, int(min(width, height) * 0.024)), bold=True)
    font_body = _get_font(max(20, int(min(width, height) * 0.032)), bold=False)
    font_footer = _get_font(max(13, int(min(width, height) * 0.018)), bold=False)

    badge_label = "SOURCE EXCERPT" if trust != "official" else "OFFICIAL EXCERPT"
    badge_bg = (245, 158, 11) if trust != "official" else (37, 99, 235)

    header_y = card_y + int(card_h * 0.08)
    draw.text((card_x + int(card_w * 0.06), header_y), badge_label, font=font_badge, fill=badge_bg)

    pub_text = publisher or "Web Source"
    draw.text((card_x + int(card_w * 0.06), header_y + int(card_h * 0.06)), pub_text, font=font_pub, fill=(209, 213, 219))

    # Divider line
    divider_y = header_y + int(card_h * 0.14)
    draw.line([card_x + int(card_w * 0.06), divider_y, card_x + int(card_w * 0.94), divider_y], fill=(46, 52, 70), width=1)

    # Quotation mark symbol
    draw.text((card_x + int(card_w * 0.06), divider_y + int(card_h * 0.03)), "“", font=_get_font(max(36, int(min(width, height) * 0.06)), bold=True), fill=(107, 114, 128))

    # Wrap excerpt text cleanly
    body_text = f"\"{excerpt_text.strip()}\""
    # Word wrap
    max_char_per_line = int(card_w * (0.06 if is_portrait else 0.045))
    words = body_text.split()
    lines = []
    current_line = []
    current_len = 0
    for w in words:
        if current_len + len(w) + 1 > max_char_per_line:
            lines.append(" ".join(current_line))
            current_line = [w]
            current_len = len(w)
        else:
            current_line.append(w)
            current_len += len(w) + 1
    if current_line:
        lines.append(" ".join(current_line))

    # Draw lines
    line_start_y = divider_y + int(card_h * 0.12)
    line_spacing = max(26, int(min(width, height) * 0.042))
    for i, line in enumerate(lines[:6]):  # max 6 lines
        line_y = line_start_y + i * line_spacing
        draw.text((card_x + int(card_w * 0.08), line_y), line, font=font_body, fill=(243, 244, 246))

    # Card footer: Title citation
    clean_title = (title[:70] + "...") if len(title) > 73 else title
    footer_y = card_y + int(card_h * 0.88)
    draw.text((card_x + int(card_w * 0.06), footer_y), f"Source: {clean_title}", font=font_footer, fill=(156, 163, 175))

    return frame


# --- Render Video with FFmpeg ---

def render_evidence_scene_video(
    composite_image: Image.Image,
    output_mp4_path: Path | str,
    duration_frames: int,
    fps: int,
    width: int,
    height: int,
) -> None:
    """Render a single exact-duration evidence scene MP4 clip with deterministic FFmpeg encoding (zero audio)."""
    out_path = Path(output_mp4_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    temp_img = out_path.parent / f"_temp_frame_{out_path.stem}.png"
    composite_image.save(temp_img, format="PNG")

    duration_sec = duration_frames / float(fps)
    ffmpeg_bin = utils.get_ffmpeg_binary()

    # Subtle slow zoom filter for premium evidence feel
    # zoom from 1.0 to 1.03 over the duration
    filter_complex = (
        f"scale={width}x{height},"
        f"zoompan=z='min(zoom+0.0003,1.03)':d={duration_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-loop", "1",
        "-i", str(temp_img),
        "-vf", filter_complex,
        "-t", f"{duration_sec:.4f}",
        "-r", str(fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-an",
        str(out_path),
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            # Fallback to direct static frame loop if complex zoompan fails
            cmd_fallback = [
                ffmpeg_bin,
                "-y",
                "-loop", "1",
                "-i", str(temp_img),
                "-t", f"{duration_sec:.4f}",
                "-r", str(fps),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "18",
                "-an",
                str(out_path),
            ]
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    finally:
        temp_img.unlink(missing_ok=True)
