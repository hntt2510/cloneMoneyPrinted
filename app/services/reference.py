import html
import io
import json
import math
import os
import re
from urllib.parse import urlencode

import numpy as np
import requests
from loguru import logger
from moviepy import ColorClip, CompositeVideoClip, ImageClip, vfx
from PIL import Image, ImageDraw, ImageFont

from app.config import config
from app.models.schema import VideoParams
from app.services import llm, material, subtitle
from app.services import video as video_service
from app.utils import utils


SUPPORTED_REFERENCE_IMAGE_SOURCES = ("pexels", "pixabay", "wikimedia")
DEFAULT_REFERENCE_IMAGE_SOURCES = ["pexels", "pixabay", "wikimedia"]
SUPPORTED_REFERENCE_EFFECT_PRESETS = ("old_paper_explained",)


def normalize_reference_image_sources(value) -> list[str]:
    if value is None:
        raw_sources = DEFAULT_REFERENCE_IMAGE_SOURCES
    elif isinstance(value, str):
        raw_sources = [item.strip() for item in value.replace("，", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_sources = [str(item).strip() for item in value]
    else:
        raw_sources = DEFAULT_REFERENCE_IMAGE_SOURCES

    sources = []
    for source in raw_sources:
        source = source.lower()
        if source in SUPPORTED_REFERENCE_IMAGE_SOURCES and source not in sources:
            sources.append(source)
    return sources or DEFAULT_REFERENCE_IMAGE_SOURCES.copy()


def normalize_reference_image_count(value) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 8
    return max(1, min(20, count))


def _strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(value).strip()


def _strip_code_fence(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```[a-zA-Z0-9]*\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def search_images_pexels(search_term: str, per_page: int = 8) -> list[dict]:
    api_key = material.get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0",
    }
    params = {
        "query": search_term,
        "per_page": max(1, min(20, per_page)),
    }
    query_url = f"https://api.pexels.com/v1/search?{urlencode(params)}"

    response = requests.get(
        query_url,
        headers=headers,
        proxies=config.proxy,
        verify=material._get_tls_verify(),
        timeout=(30, 60),
    ).json()

    results = []
    for photo in response.get("photos") or []:
        src = photo.get("src") or {}
        image_url = src.get("large2x") or src.get("large") or src.get("original")
        if not image_url:
            continue
        results.append(
            {
                "provider": "pexels",
                "image_url": image_url,
                "source_url": photo.get("url", ""),
                "author": photo.get("photographer", ""),
                "license": "Pexels License",
                "title": photo.get("alt") or search_term,
            }
        )
    return results


def search_images_pixabay(search_term: str, per_page: int = 8) -> list[dict]:
    api_key = material.get_api_key("pixabay_api_keys")
    params = {
        "key": api_key,
        "q": search_term,
        "image_type": "photo",
        "per_page": max(3, min(20, per_page)),
        "safesearch": "true",
    }
    query_url = f"https://pixabay.com/api/?{urlencode(params)}"

    response = requests.get(
        query_url,
        proxies=config.proxy,
        verify=material._get_tls_verify(),
        timeout=(30, 60),
    ).json()

    results = []
    for hit in response.get("hits") or []:
        image_url = hit.get("largeImageURL") or hit.get("webformatURL")
        if not image_url:
            continue
        results.append(
            {
                "provider": "pixabay",
                "image_url": image_url,
                "source_url": hit.get("pageURL", ""),
                "author": hit.get("user", ""),
                "license": "Pixabay Content License",
                "title": hit.get("tags") or search_term,
            }
        )
    return results


def search_images_wikimedia(search_term: str, per_page: int = 8) -> list[dict]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": search_term,
        "gsrnamespace": 6,
        "gsrlimit": max(1, min(20, per_page)),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1600,
    }
    headers = {
        "User-Agent": "MoneyPrinterTurbo/1.3 reference-image-search",
    }
    response = requests.get(
        "https://commons.wikimedia.org/w/api.php",
        params=params,
        headers=headers,
        proxies=config.proxy,
        verify=material._get_tls_verify(),
        timeout=(30, 60),
    ).json()

    results = []
    pages = (response.get("query") or {}).get("pages") or {}
    for page in pages.values():
        image_info = (page.get("imageinfo") or [{}])[0]
        metadata = image_info.get("extmetadata") or {}
        image_url = image_info.get("thumburl") or image_info.get("url")
        if not image_url:
            continue
        license_name = _strip_html(
            (metadata.get("LicenseShortName") or {}).get("value", "")
            or (metadata.get("License") or {}).get("value", "")
        )
        results.append(
            {
                "provider": "wikimedia",
                "image_url": image_url,
                "source_url": image_info.get("descriptionurl", ""),
                "author": _strip_html((metadata.get("Artist") or {}).get("value", "")),
                "license": license_name,
                "title": _strip_html(
                    (metadata.get("ObjectName") or {}).get("value", "")
                    or page.get("title", search_term)
                ),
            }
        )

    def has_clear_license(item: dict) -> bool:
        license_text = (item.get("license") or "").lower()
        return any(key in license_text for key in ("cc", "public domain", "pd", "gfdl"))

    results.sort(key=lambda item: 0 if has_clear_license(item) else 1)
    return results


def search_reference_images(
    search_term: str,
    sources,
    per_source: int = 4,
) -> list[dict]:
    providers = {
        "pexels": search_images_pexels,
        "pixabay": search_images_pixabay,
        "wikimedia": search_images_wikimedia,
    }
    results = []
    for source in normalize_reference_image_sources(sources):
        try:
            results.extend(providers[source](search_term, per_page=per_source))
        except ValueError as exc:
            logger.warning(f"skip reference image source {source}: {str(exc)}")
        except Exception as exc:
            logger.warning(
                f"reference image search failed, source: {source}, "
                f"term: {search_term}, error: {str(exc)}"
            )
    return results


def _scene_title(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text[:48] or "Reference"


def _fallback_reference_plan(
    video_subject: str,
    video_script: str,
    max_items: int,
) -> list[dict]:
    lines = utils.split_string_by_punctuations(
        utils.normalize_script_for_subtitle_matching(video_script)
    )
    if not lines:
        lines = [video_script.strip() or video_subject.strip() or "Reference"]
    lines = lines[:max_items]

    try:
        terms = llm.generate_terms(
            video_subject=video_subject,
            video_script=video_script,
            amount=len(lines),
            match_script_order=True,
        )
    except Exception as exc:
        logger.warning(f"reference fallback terms failed: {str(exc)}")
        terms = []
    if not isinstance(terms, list):
        terms = []

    scenes = []
    for index, line in enumerate(lines):
        term = terms[index] if index < len(terms) and terms[index] else ""
        if not term:
            term = f"{video_subject} {line[:60]}".strip()
        scenes.append(
            {
                "search_term": term,
                "title": _scene_title(line),
                "narration": line,
            }
        )
    return scenes


def build_reference_plan(
    video_subject: str,
    video_script: str,
    max_items: int = 8,
) -> list[dict]:
    max_items = normalize_reference_image_count(max_items)
    prompt = f"""
# Role: Reference Image Storyboarder

Create a chronological reference-image plan for an educational/explained video.

Return ONLY a valid minified JSON array. Each item must contain exactly:
"search_term", "title", "narration".

Rules:
1. Return at most {max_items} items.
2. Keep the item order aligned with the narration.
3. Write search_term in English, concise and image-search friendly.
4. Keep title short enough for an overlay label.
5. narration should be the matching script fragment, not a new script.

Video subject:
{video_subject}

Script:
{video_script}
""".strip()

    try:
        response = llm._generate_response(prompt)
        parsed = json.loads(_strip_code_fence(response))
        if not isinstance(parsed, list):
            raise ValueError("reference plan response is not a list")

        scenes = []
        for item in parsed[:max_items]:
            if not isinstance(item, dict):
                continue
            search_term = str(item.get("search_term") or "").strip()
            narration = str(item.get("narration") or "").strip()
            title = _scene_title(str(item.get("title") or narration or search_term))
            if search_term:
                scenes.append(
                    {
                        "search_term": search_term,
                        "title": title,
                        "narration": narration,
                    }
                )
        if scenes:
            return scenes
    except Exception as exc:
        logger.warning(f"failed to build reference plan with LLM: {str(exc)}")

    return _fallback_reference_plan(video_subject, video_script, max_items)


def _srt_time_to_seconds(value: str) -> float:
    match = re.match(r"(\d+):(\d+):(\d+),(\d+)", value.strip())
    if not match:
        return 0.0
    hours, minutes, seconds, milliseconds = [int(part) for part in match.groups()]
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def attach_reference_timing(
    scenes: list[dict],
    subtitle_path: str,
    audio_duration: float,
) -> list[dict]:
    if not scenes:
        return []

    subtitle_items = subtitle.file_to_subtitles(subtitle_path)
    scene_count = len(scenes)
    if subtitle_items:
        subtitle_count = len(subtitle_items)
        for index, scene in enumerate(scenes):
            start_index = math.floor(index * subtitle_count / scene_count)
            end_index = max(
                start_index,
                math.floor((index + 1) * subtitle_count / scene_count) - 1,
            )
            start_text, _ = subtitle_items[start_index][1].split(" --> ")
            _, cue_end_text = subtitle_items[min(end_index, subtitle_count - 1)][
                1
            ].split(" --> ")
            scene["start"] = _srt_time_to_seconds(start_text)
            scene["end"] = max(scene["start"] + 0.5, _srt_time_to_seconds(cue_end_text))
        return scenes

    total_duration = max(float(audio_duration or 0), float(scene_count))
    chunk_duration = total_duration / scene_count
    for index, scene in enumerate(scenes):
        scene["start"] = index * chunk_duration
        scene["end"] = min(total_duration, (index + 1) * chunk_duration)
    return scenes


def download_reference_image(candidate: dict, save_dir: str) -> str:
    image_url = candidate.get("image_url") or ""
    if not image_url:
        return ""

    os.makedirs(save_dir, exist_ok=True)
    image_hash = utils.md5(image_url.split("?")[0])
    image_path = os.path.join(save_dir, f"ref-{image_hash}.png")
    if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
        return image_path

    response = requests.get(
        image_url,
        headers={"User-Agent": "Mozilla/5.0"},
        proxies=config.proxy,
        verify=material._get_tls_verify(),
        timeout=(30, 90),
    )
    image = Image.open(io.BytesIO(response.content))
    image.load()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    image.save(image_path)
    return image_path if os.path.getsize(image_path) > 0 else ""


def prepare_reference_assets(
    task_id: str,
    params: VideoParams,
    video_script: str,
    subtitle_path: str,
    audio_duration: float,
) -> tuple[list[dict], list[dict]]:
    if not getattr(params, "reference_mode_enabled", False):
        return [], []

    logger.info("\n\n## preparing reference images")
    task_dir = utils.task_dir(task_id)
    image_dir = os.path.join(task_dir, "reference_images")
    source_list = normalize_reference_image_sources(params.reference_image_sources)
    scenes = build_reference_plan(
        video_subject=params.video_subject,
        video_script=video_script,
        max_items=params.reference_image_count,
    )
    scenes = attach_reference_timing(scenes, subtitle_path, audio_duration)

    used_urls = set()
    reference_images = []
    for scene in scenes:
        candidates = search_reference_images(
            search_term=scene.get("search_term", ""),
            sources=source_list,
            per_source=4,
        )
        for candidate in candidates:
            image_url = candidate.get("image_url", "")
            if not image_url or image_url in used_urls:
                continue
            try:
                image_path = download_reference_image(candidate, image_dir)
            except Exception as exc:
                logger.warning(
                    f"failed to download reference image: {image_url}, error: {str(exc)}"
                )
                continue
            if not image_path:
                continue
            used_urls.add(image_url)
            scene.update(
                {
                    "image_path": image_path,
                    "provider": candidate.get("provider", ""),
                    "source_url": candidate.get("source_url", ""),
                    "author": candidate.get("author", ""),
                    "license": candidate.get("license", ""),
                }
            )
            reference_images.append(
                {
                    "path": image_path,
                    "provider": scene["provider"],
                    "source_url": scene["source_url"],
                    "author": scene["author"],
                    "license": scene["license"],
                    "search_term": scene.get("search_term", ""),
                }
            )
            break
        if not scene.get("image_path"):
            logger.warning(
                "no reference image found for scene: "
                f"{scene.get('search_term', '')}"
            )

    plan_path = os.path.join(task_dir, "reference_plan.json")
    with open(plan_path, "w", encoding="utf-8") as file:
        file.write(
            utils.to_json(
                {
                    "sources": source_list,
                    "effect_preset": params.reference_effect_preset,
                    "scenes": scenes,
                    "images": reference_images,
                }
            )
        )
    logger.success(f"prepared {len(reference_images)} reference images")
    return scenes, reference_images


def _get_font(name: str, size: int):
    font_path = os.path.join(utils.font_dir(), name)
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap_pil_text(text: str, font, max_width: int, max_lines: int) -> list[str]:
    words = re.split(r"\s+", (text or "").strip())
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = font.getbbox(candidate)
        if bbox[2] - bbox[0] <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def _resize_to_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _paper_rgba(width: int, height: int) -> Image.Image:
    rng = np.random.default_rng(3)
    base = np.full((height, width, 3), (238, 232, 207), dtype=np.int16)
    noise = rng.integers(-7, 8, size=(height, width, 1))
    rgb = np.clip(base + noise, 0, 255).astype(np.uint8)
    alpha = np.full((height, width, 1), 244, dtype=np.uint8)
    return Image.fromarray(np.concatenate([rgb, alpha], axis=2))


def _make_reference_card(scene: dict, video_width: int, video_height: int) -> Image.Image:
    if video_width < video_height:
        card_w = int(video_width * 0.84)
        card_h = int(video_height * 0.34)
    else:
        card_w = int(video_width * 0.46)
        card_h = int(video_height * 0.56)
    card_w = min(max(260, card_w), max(1, video_width - 40))
    card_h = min(max(180, card_h), max(1, video_height - 60))
    pad = max(18, int(card_w * 0.045))

    card = _paper_rgba(card_w, card_h)
    draw = ImageDraw.Draw(card)
    border = (53, 52, 45, 235)
    draw.rectangle((8, 8, card_w - 9, card_h - 9), outline=border, width=4)
    draw.rectangle((16, 16, card_w - 17, card_h - 17), outline=(85, 80, 70, 130), width=1)

    title_font = _get_font("BeVietnamPro-Bold.ttf", max(28, int(card_w * 0.052)))
    text_font = _get_font("BeVietnamPro-Medium.ttf", max(20, int(card_w * 0.035)))
    source_font = _get_font("BeVietnamPro-Medium.ttf", max(14, int(card_w * 0.025)))

    title = _scene_title(scene.get("title") or scene.get("search_term") or "Reference")
    title_lines = _wrap_pil_text(title, title_font, card_w - 2 * pad, 2)
    title_h = sum(title_font.getbbox(line)[3] - title_font.getbbox(line)[1] for line in title_lines)
    title_h += max(0, len(title_lines) - 1) * 8

    footer_h = max(92, int(card_h * 0.23))
    image_top = pad + title_h + 18
    image_h = max(80, card_h - image_top - footer_h - pad)
    image_box = (pad, image_top, card_w - pad, image_top + image_h)

    try:
        with Image.open(scene["image_path"]) as image:
            image = image.convert("RGB")
            image = _resize_to_cover(image, (image_box[2] - image_box[0], image_box[3] - image_box[1]))
            card.paste(image, image_box[:2])
    except Exception as exc:
        logger.warning(f"failed to draw reference image card: {str(exc)}")

    draw.rectangle(image_box, outline=border, width=3)

    y = pad
    label_box = (pad - 4, y - 6, card_w - pad + 4, y + title_h + 14)
    draw.rounded_rectangle(label_box, radius=3, fill=(247, 242, 219, 210), outline=border, width=2)
    for line in title_lines:
        draw.text((pad + 8, y), line, font=title_font, fill=(55, 54, 48, 255))
        y += title_font.getbbox(line)[3] - title_font.getbbox(line)[1] + 8

    footer_top = image_box[3] + 16
    narration = scene.get("narration") or scene.get("search_term") or ""
    for line in _wrap_pil_text(narration, text_font, card_w - 2 * pad, 2):
        draw.text((pad, footer_top), line, font=text_font, fill=(64, 61, 54, 245))
        footer_top += text_font.getbbox(line)[3] - text_font.getbbox(line)[1] + 8

    provider = scene.get("provider") or ""
    if provider:
        source_font_size = getattr(source_font, "size", max(14, int(card_w * 0.025)))
        draw.text(
            (pad, card_h - pad - source_font_size),
            provider.upper(),
            font=source_font,
            fill=(91, 86, 73, 210),
        )
    return card


def render_reference_overlay(
    video_path: str,
    output_path: str,
    reference_plan: list[dict],
    params: VideoParams,
    threads: int = 2,
) -> str:
    if not getattr(params, "reference_mode_enabled", False):
        return video_path

    preset = (params.reference_effect_preset or "old_paper_explained").strip().lower()
    if preset not in SUPPORTED_REFERENCE_EFFECT_PRESETS:
        logger.warning(f"unsupported reference effect preset: {preset}")
        return video_path

    scenes = [
        scene
        for scene in reference_plan
        if scene.get("image_path")
        and os.path.exists(scene.get("image_path", ""))
        and float(scene.get("end", 0)) > float(scene.get("start", 0))
    ]
    if not scenes:
        return video_path

    base_clip = video_service._open_video_clip_quietly(video_path)
    overlay_clips = []
    try:
        video_width, video_height = base_clip.size
        for scene in scenes:
            start = max(0.0, float(scene.get("start", 0)))
            end = min(float(scene.get("end", 0)), float(base_clip.duration))
            duration = max(0.5, end - start)
            card = _make_reference_card(scene, video_width, video_height)
            card_clip = ImageClip(np.array(card), transparent=True).with_duration(duration)
            card_clip = card_clip.resized(lambda t: 1 + 0.025 * (t / max(duration, 0.1)))

            def position(t, clip=card_clip, vw=video_width, vh=video_height):
                x = int((vw - clip.w) / 2)
                y = int(vh * 0.10) if vw < vh else int((vh - clip.h) / 2)
                return x, y

            card_clip = (
                card_clip.with_start(start)
                .with_position(position)
                .with_effects([vfx.FadeIn(0.25), vfx.FadeOut(0.25)])
            )
            dim_clip = (
                ColorClip(size=(video_width, video_height), color=(0, 0, 0))
                .with_opacity(0.18)
                .with_start(start)
                .with_duration(duration)
                .with_effects([vfx.FadeIn(0.2), vfx.FadeOut(0.2)])
            )
            overlay_clips.extend([dim_clip, card_clip])

        if not overlay_clips:
            return video_path

        output_clip = CompositeVideoClip(
            [base_clip, *overlay_clips],
            size=(video_width, video_height),
        ).with_duration(base_clip.duration)
        video_service._write_videofile_with_codec_fallback(
            output_clip,
            output_file=output_path,
            codec=video_service._get_configured_video_codec(),
            logger=None,
            fps=video_service.fps,
            threads=threads or 2,
        )
        return (
            output_path
            if os.path.isfile(output_path) and os.path.getsize(output_path) > 0
            else video_path
        )
    except Exception as exc:
        logger.warning(f"failed to render reference overlay: {str(exc)}")
        return video_path
    finally:
        if "output_clip" in locals():
            video_service.close_clip(output_clip)
        else:
            for clip in overlay_clips:
                video_service.close_clip(clip)
            video_service.close_clip(base_clip)
