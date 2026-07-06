import os
import random
import threading
from typing import List
from urllib.parse import urlencode

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip
from yt_dlp import YoutubeDL

from app.config import config
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode
from app.utils import utils

# Thread-safe counter for API key rotation
_api_key_counter = 0
_api_key_lock = threading.Lock()


def _get_tls_verify() -> bool:
    # 默认开启 TLS 证书校验，防止素材搜索和下载过程被中间人篡改。
    # 仅在企业代理、自签证书等明确需要的场景下，允许用户通过
    # `config.toml` 显式设置 `tls_verify = false` 临时关闭。
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")

    if not tls_verify:
        logger.warning(
            "TLS certificate verification is disabled by config.app.tls_verify=false. "
            "Only use this in trusted proxy environments."
        )

    return bool(tls_verify)


def get_api_key(cfg_key: str):
    api_keys = config.app.get(cfg_key)
    if not api_keys:
        raise ValueError(
            f"\n\n##### {cfg_key} is not set #####\n\nPlease set it in the config.toml file: {config.config_file}\n\n"
            f"{utils.to_json(config.app)}"
        )

    # if only one key is provided, return it
    if isinstance(api_keys, str):
        return api_keys

    global _api_key_counter
    with _api_key_lock:
        _api_key_counter += 1
        return api_keys[_api_key_counter % len(api_keys)]


def search_videos_pexels(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)
    video_orientation = aspect.name
    video_width, video_height = aspect.to_resolution()
    api_key = get_api_key("pexels_api_keys")
    headers = {
        "Authorization": api_key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    }
    # Build URL
    params = {"query": search_term, "per_page": 20, "orientation": video_orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items = []
        if "videos" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["videos"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["video_files"]
            # loop through each url to determine the best quality
            for video in video_files:
                w = int(video["width"])
                h = int(video["height"])
                if w == video_width and h == video_height:
                    item = MaterialInfo()
                    item.provider = "pexels"
                    item.url = video["link"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_pixabay(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    aspect = VideoAspect(video_aspect)

    video_width, video_height = aspect.to_resolution()

    api_key = get_api_key("pixabay_api_keys")
    # Build URL
    params = {
        "q": search_term,
        "video_type": "all",  # Accepted values: "all", "film", "animation"
        "per_page": 50,
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url, proxies=config.proxy, verify=_get_tls_verify(), timeout=(30, 60)
        )
        response = r.json()
        video_items = []
        if "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items
        videos = response["hits"]
        # loop through each video in the result
        for v in videos:
            duration = v["duration"]
            # check if video has desired minimum duration
            if duration < minimum_duration:
                continue
            video_files = v["videos"]
            # loop through each url to determine the best quality
            for video_type in video_files:
                video = video_files[video_type]
                w = int(video["width"])
                # h = int(video["height"])
                if w >= video_width:
                    item = MaterialInfo()
                    item.provider = "pixabay"
                    item.url = video["url"]
                    item.duration = duration
                    video_items.append(item)
                    break
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def search_videos_coverr(
    search_term: str,
    minimum_duration: int,
    video_aspect: VideoAspect = VideoAspect.portrait,
) -> List[MaterialInfo]:
    """
    Coverr (https://coverr.co) - free HD/4K stock videos,
    subject to Coverr license terms (https://coverr.co/license).

    Coverr API notes (based on official docs at api.coverr.co/docs/):
      - 鉴权: Authorization: Bearer <api_key>
      - 搜索端点: GET /videos?query=...,响应结构 {"hits": [...], ...}
      - 加 ?urls=true 在搜索响应里直接返回 mp4 直链
      - URL 是 signed JWT(绑定 API key,无过期时间)
      - Coverr 库以 16:9 横屏为主,9:16 portrait 占比极低(约 1%)
        因此本函数不做 aspect_ratio 过滤,由下游 video.py 的
        resize + letterbox 逻辑统一处理
      - duration 字段同时存在 number 和 string 两种形态,本函数都接受

    本函数使用 urls.mp4_download 字段作为下载地址 —— 按 Coverr 官方文档
    (https://api.coverr.co/docs/videos/#download-a-video) 的说法,
    GET 这个 URL 本身就被 Coverr 当作一次合法的 download 事件计入统计,
    无需再调用 PATCH /videos/:id/stats/downloads。
    """
    api_key = get_api_key("coverr_api_keys")
    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "query": search_term,
        "page_size": 20,
        "urls": "true",
        "sort": "popular",
    }
    query_url = f"https://api.coverr.co/videos?{urlencode(params)}"
    logger.info(f"searching videos: {query_url}, with proxies: {config.proxy}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 60),
        )
        response = r.json()
        video_items: List[MaterialInfo] = []

        if not isinstance(response, dict) or "hits" not in response:
            logger.error(f"search videos failed: {response}")
            return video_items

        for v in response["hits"]:
            # duration 在不同响应里可能是 number(11.625) 或 string("10.500000")
            try:
                duration = int(float(v.get("duration") or 0))
            except (TypeError, ValueError):
                continue
            if duration < minimum_duration:
                continue

            video_id = v.get("id")
            mp4_download_url = (v.get("urls") or {}).get("mp4_download")
            if not video_id or not mp4_download_url:
                continue

            item = MaterialInfo()
            item.provider = "coverr"
            item.url = mp4_download_url
            item.duration = duration
            video_items.append(item)
        return video_items
    except Exception as e:
        logger.error(f"search videos failed: {str(e)}")

    return []


def save_video(video_url: str, save_dir: str = "") -> str:
    if not save_dir:
        save_dir = utils.storage_dir("cache_videos")

    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    url_without_query = video_url.split("?")[0]
    url_hash = utils.md5(url_without_query)
    video_id = f"vid-{url_hash}"
    video_path = f"{save_dir}/{video_id}.mp4"

    # if video already exists, return the path
    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        logger.info(f"video already exists: {video_path}")
        return video_path

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    # if video does not exist, download it
    with open(video_path, "wb") as f:
        f.write(
            requests.get(
                video_url,
                headers=headers,
                proxies=config.proxy,
                verify=_get_tls_verify(),
                timeout=(60, 240),
            ).content
        )

    if os.path.exists(video_path) and os.path.getsize(video_path) > 0:
        clip = None
        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps
            if duration > 0 and fps > 0:
                return video_path
        except Exception as e:
            logger.warning(f"invalid video file: {video_path} => {str(e)}")
            try:
                os.remove(video_path)
            except Exception as remove_error:
                logger.warning(
                    f"failed to remove invalid video file: {video_path}, error: {str(remove_error)}"
                )
        finally:
            if clip is not None:
                try:
                    clip.close()
                except Exception as close_error:
                    logger.warning(
                        f"failed to close video clip: {video_path}, error: {str(close_error)}"
                    )
    return ""


def _resolve_cookie_file() -> str:
    cookie_file = str(config.app.get("external_cookie_file", "cookies.txt") or "").strip()
    if not cookie_file:
        return ""

    if not os.path.isabs(cookie_file):
        cookie_file = os.path.join(utils.root_dir(), cookie_file)

    return cookie_file if os.path.isfile(cookie_file) else ""


def _collect_mp4_files(directory: str) -> set[str]:
    if not os.path.isdir(directory):
        return set()

    files = set()
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if filename.lower().endswith(".mp4"):
                files.add(os.path.join(root, filename))
    return files


def _valid_video_duration(video_path: str) -> float:
    clip = None
    try:
        clip = VideoFileClip(video_path)
        if clip.duration > 0 and clip.fps > 0:
            return float(clip.duration)
    except Exception as exc:
        logger.warning(f"invalid downloaded video: {video_path}, error: {str(exc)}")
    finally:
        if clip is not None:
            try:
                clip.close()
            except Exception:
                pass
    return 0.0


def _download_videos_with_ytdlp_search(
    task_id: str,
    search_terms: List[str],
    source: str,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    if source != "bilibili":
        return []

    save_dir = material_directory or utils.storage_dir("cache_videos")
    save_dir = os.path.join(save_dir, f"{source}-{task_id}")
    os.makedirs(save_dir, exist_ok=True)

    cookie_file = _resolve_cookie_file()
    per_term_limit = int(config.app.get("external_search_results_per_term", 3) or 3)
    per_term_limit = max(1, min(10, per_term_limit))
    ydl_opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(save_dir, "%(extractor)s-%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "noplaylist": False,
        "playlistend": per_term_limit,
        "retries": 2,
        "fragment_retries": 2,
    }
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    video_paths = []
    total_duration = 0.0
    required_duration = float(audio_duration or 0)
    with YoutubeDL(ydl_opts) as ydl:
        for search_term in search_terms:
            query = f"bilisearch{per_term_limit}:{search_term}"
            logger.info(f"searching and downloading external videos: {query}")
            before_files = _collect_mp4_files(save_dir)
            try:
                search_info = ydl.extract_info(query, download=False)
            except Exception as exc:
                logger.warning(f"yt-dlp search failed for '{search_term}': {str(exc)}")
                continue

            entries = (search_info or {}).get("entries") or []
            for entry in entries:
                if not _is_external_candidate_style_compatible(entry):
                    continue
                try:
                    ydl.extract_info(entry.get("webpage_url") or entry.get("url"), download=True)
                except Exception as exc:
                    logger.warning(
                        f"yt-dlp download failed for '{entry.get('title', '')}': {str(exc)}"
                    )
                    continue

                new_files = sorted(
                    _collect_mp4_files(save_dir) - before_files,
                    key=lambda file_path: os.path.getmtime(file_path),
                )
                for video_path in new_files:
                    if video_path in video_paths:
                        continue
                    duration = _valid_video_duration(video_path)
                    if duration <= 0:
                        continue
                    video_paths.append(video_path)
                    total_duration += min(max_clip_duration, duration)
                    if total_duration > required_duration:
                        logger.info(
                            f"total duration of external videos: {total_duration} seconds, skip downloading more"
                        )
                        return video_paths
                before_files = _collect_mp4_files(save_dir)

    logger.success(f"downloaded {len(video_paths)} external videos from {source}")
    return video_paths


def _is_external_candidate_style_compatible(entry: dict) -> bool:
    preset = str(config.app.get("video_style_preset", "auto") or "auto").strip().lower()
    if preset in ("auto", "shorts_fast"):
        return True

    text = " ".join(
        str(entry.get(field) or "")
        for field in ("title", "description", "uploader", "channel")
    ).lower()
    blocked_terms = (
        "游戏",
        "手游",
        "动画",
        "动漫",
        "直播",
        "鬼畜",
        "歌",
        "music",
        "game",
        "anime",
        "live",
        "舞蹈",
        "dance",
    )
    if any(term in text for term in blocked_terms):
        logger.info(f"skip style-mismatched external candidate: {entry.get('title', '')}")
        return False
    return True


def _download_url_with_ytdlp(video_url: str, save_dir: str) -> str:
    os.makedirs(save_dir, exist_ok=True)
    before_files = _collect_mp4_files(save_dir)
    cookie_file = _resolve_cookie_file()
    ydl_opts = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(save_dir, "%(extractor)s-%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "noplaylist": True,
        "retries": 2,
        "fragment_retries": 2,
    }
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(video_url, download=True)
    except Exception as exc:
        logger.warning(f"yt-dlp URL download failed: {video_url}, error: {str(exc)}")
        return ""

    new_files = sorted(
        _collect_mp4_files(save_dir) - before_files,
        key=lambda file_path: os.path.getmtime(file_path),
    )
    return new_files[-1] if new_files else ""


def _extract_urls_from_json(value) -> list[str]:
    urls = []
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if key.lower() in {
                "url",
                "video_url",
                "download_url",
                "play_url",
                "share_url",
                "aweme_url",
            } and isinstance(nested_value, str):
                urls.append(nested_value)
            else:
                urls.extend(_extract_urls_from_json(nested_value))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_extract_urls_from_json(item))
    return urls


def _search_douyin_videos_with_configured_api(search_term: str, limit: int) -> list[str]:
    search_api_url = str(config.app.get("douyin_search_api_url", "") or "").strip()
    if not search_api_url:
        logger.warning(
            "douyin_search_api_url is not configured; automatic Douyin keyword search is unavailable"
        )
        return []

    query_url = search_api_url.format(query=search_term, limit=limit)
    headers = {}
    api_key = str(config.app.get("douyin_api_key", "") or "").strip()
    jwt_token = str(config.app.get("douyin_jwt", "") or "").strip()
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 90),
        )
        response.raise_for_status()
        return list(dict.fromkeys(_extract_urls_from_json(response.json())))
    except Exception as exc:
        logger.warning(f"Douyin search API failed for '{search_term}': {str(exc)}")
        return []


def _download_videos_with_external_search_api(
    task_id: str,
    search_terms: List[str],
    source: str,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    if source != "douyin":
        return []

    save_dir = material_directory or utils.storage_dir("cache_videos")
    save_dir = os.path.join(save_dir, f"{source}-{task_id}")
    os.makedirs(save_dir, exist_ok=True)

    per_term_limit = int(config.app.get("external_search_results_per_term", 3) or 3)
    per_term_limit = max(1, min(10, per_term_limit))
    video_paths = []
    total_duration = 0.0
    required_duration = float(audio_duration or 0)

    for search_term in search_terms:
        candidate_urls = _search_douyin_videos_with_configured_api(
            search_term=search_term,
            limit=per_term_limit,
        )
        logger.info(f"found {len(candidate_urls)} Douyin candidates for '{search_term}'")
        for candidate_url in candidate_urls[:per_term_limit]:
            saved_video_path = save_video(video_url=candidate_url, save_dir=save_dir)
            if not saved_video_path:
                saved_video_path = _download_url_with_ytdlp(
                    video_url=candidate_url,
                    save_dir=save_dir,
                )
            if not saved_video_path:
                continue
            duration = _valid_video_duration(saved_video_path)
            if duration <= 0:
                continue
            video_paths.append(saved_video_path)
            total_duration += min(max_clip_duration, duration)
            if total_duration > required_duration:
                return video_paths

    return video_paths


def download_videos(
    task_id: str,
    search_terms: List[str],
    source: str = "pexels",
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    audio_duration: float = 0.0,
    max_clip_duration: int = 5,
    match_script_order: bool = False,
) -> List[str]:
    material_directory = config.app.get("material_directory", "").strip()
    if material_directory == "task":
        material_directory = utils.task_dir(task_id)
    elif material_directory and not os.path.isdir(material_directory):
        material_directory = ""

    if source == "bilibili":
        return _download_videos_with_ytdlp_search(
            task_id=task_id,
            search_terms=search_terms,
            source=source,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    if source == "douyin":
        return _download_videos_with_external_search_api(
            task_id=task_id,
            search_terms=search_terms,
            source=source,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    search_videos = search_videos_pexels
    if source == "pixabay":
        search_videos = search_videos_pixabay
    elif source == "coverr":
        search_videos = search_videos_coverr

    if match_script_order:
        return _download_videos_by_script_order(
            task_id=task_id,
            search_terms=search_terms,
            search_videos=search_videos,
            video_aspect=video_aspect,
            audio_duration=audio_duration,
            max_clip_duration=max_clip_duration,
            material_directory=material_directory,
        )

    valid_video_items = []
    valid_video_urls = []
    found_duration = 0.0
    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        for item in video_items:
            if item.url not in valid_video_urls:
                valid_video_items.append(item)
                valid_video_urls.append(item.url)
                found_duration += item.duration

    logger.info(
        f"found total videos: {len(valid_video_items)}, required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )
    video_paths = []

    concat_mode_value = getattr(video_concat_mode, "value", video_concat_mode)
    if concat_mode_value == VideoConcatMode.random.value:
        random.shuffle(valid_video_items)

    total_duration = 0.0
    for item in valid_video_items:
        try:
            logger.info(f"downloading video: {item.url}")
            saved_video_path = save_video(
                video_url=item.url, save_dir=material_directory
            )
            if saved_video_path:
                logger.info(f"video saved: {saved_video_path}")
                video_paths.append(saved_video_path)
                seconds = min(max_clip_duration, item.duration)
                total_duration += seconds
                if total_duration > audio_duration:
                    logger.info(
                        f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                    )
                    break
        except Exception as e:
            logger.error(f"failed to download video: {utils.to_json(item)} => {str(e)}")
    logger.success(f"downloaded {len(video_paths)} videos")
    return video_paths


def _download_videos_by_script_order(
    task_id: str,
    search_terms: List[str],
    search_videos,
    video_aspect: VideoAspect,
    audio_duration: float,
    max_clip_duration: int,
    material_directory: str,
) -> List[str]:
    """
    按脚本文案顺序下载素材。

    默认下载逻辑会把所有关键词的候选素材合并成一个大列表；如果第一个
    关键词返回很多结果，最终下载时可能一直消耗这个关键词的素材，后续
    脚本主题就排不上时间线。这里按关键词分组后轮询下载：
    第 1 轮取每个关键词的第 1 个候选，第 2 轮取每个关键词的第 2 个候选。
    这样在不重写视频合成引擎的前提下，尽量保证素材顺序贴近文案顺序。
    """
    logger.info("downloading videos with script-order material matching")
    candidate_groups = []
    valid_video_urls = set()
    found_duration = 0.0

    for search_term in search_terms:
        video_items = search_videos(
            search_term=search_term,
            minimum_duration=max_clip_duration,
            video_aspect=video_aspect,
        )
        logger.info(f"found {len(video_items)} videos for '{search_term}'")

        term_items = []
        for item in video_items:
            if item.url in valid_video_urls:
                continue
            term_items.append(item)
            valid_video_urls.add(item.url)
            found_duration += item.duration

        if term_items:
            candidate_groups.append((search_term, term_items))

    logger.info(
        f"found total ordered video candidates: {sum(len(items) for _, items in candidate_groups)}, "
        f"required duration: {audio_duration} seconds, found duration: {found_duration} seconds"
    )

    video_paths = []
    total_duration = 0.0
    candidate_index = 0
    while candidate_groups and total_duration <= audio_duration:
        has_candidate = False
        for search_term, term_items in candidate_groups:
            if candidate_index >= len(term_items):
                continue

            has_candidate = True
            item = term_items[candidate_index]
            try:
                logger.info(
                    f"downloading ordered video for '{search_term}': {item.url}"
                )
                saved_video_path = save_video(
                    video_url=item.url, save_dir=material_directory
                )
                if saved_video_path:
                    logger.info(f"video saved: {saved_video_path}")
                    video_paths.append(saved_video_path)
                    total_duration += min(max_clip_duration, item.duration)
                    if total_duration > audio_duration:
                        logger.info(
                            f"total duration of downloaded videos: {total_duration} seconds, skip downloading more"
                        )
                        break
            except Exception as e:
                logger.error(
                    f"failed to download ordered video: {utils.to_json(item)} => {str(e)}"
                )

        if not has_candidate:
            break
        candidate_index += 1

    logger.success(f"downloaded {len(video_paths)} ordered videos")
    return video_paths


if __name__ == "__main__":
    download_videos(
        "test123", ["Money Exchange Medium"], audio_duration=100, source="pixabay"
    )
