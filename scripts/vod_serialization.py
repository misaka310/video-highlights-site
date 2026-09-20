from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from vod_highlights import (
    DetectConfig,
    SEGMENT_THUMBNAILS_DIR,
    build_activity_map,
    build_segment_screenshot_file_path,
    build_segment_screenshot_public_path,
    classify_segment_tags,
    format_hhmmss,
    normalize_activity_map,
    parse_int,
)
from youtube_url import is_youtube_url

PUBLIC_VOD_RETENTION_DAYS = 60


PUBLIC_ITEM_FIELDS = (
    "rank",
    "id",
    "start_sec",
    "end_sec",
    "duration_sec",
    "start_time",
    "end_time",
    "reason",
    "headline",
    "tags",
    "watch_url",
    "screenshot_url",
)


COMPACT_ARRAY_PATHS = {("activity_map", "buckets")}


COMPACT_ARRAY_ITEMS_PER_LINE = 40


JSON_WRITE_ENCODING = "utf-8"


TAG_LABEL_ALIASES = {
    "笑い": "ww",
    "衝撃": "えっ",
    "神プレイ": "好プレー",
    "えっろ": "えっど",
    "は？": "は",
}


def is_youtube_video(video: Mapping[str, Any]) -> bool:
    """Return whether a cached video belongs to the current public YouTube feed."""

    provider = str(video.get("provider") or "").strip().lower()
    if provider:
        return provider == "youtube"
    return is_youtube_url(str(video.get("vod_url") or ""))


def filter_youtube_videos(videos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exclude legacy Twitch cache entries from YouTube public output."""

    return [video for video in videos if is_youtube_video(video)]


def normalize_tag_labels(tags: Iterable[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        label = TAG_LABEL_ALIASES.get(str(tag), str(tag)).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    return normalized


def refresh_cached_video_metadata(video: dict[str, Any], comments: list[dict[str, Any]], duration_sec: int | None) -> dict[str, Any]:
    refreshed = dict(video)
    items: list[dict[str, Any]] = []
    for item in video.get("items") or []:
        updated_item = dict(item)
        start_sec = parse_int(item.get("start_sec"))
        end_sec = parse_int(item.get("end_sec"))
        if start_sec is not None and end_sec is not None:
            updated_item["tags"] = normalize_tag_labels(classify_segment_tags(comments, start_sec, end_sec))
        items.append(updated_item)
    refreshed["items"] = items
    refreshed["activity_map"] = build_activity_map(comments, DetectConfig(), duration_sec)
    return refreshed


def normalize_chat_total(value: Any) -> int | None:
    chat_total = parse_int(value)
    if chat_total is None or chat_total < 0:
        return None
    return chat_total


def parse_non_negative_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def normalize_comments_per_hour(value: Any) -> float | None:
    comments_per_hour = parse_non_negative_float(value)
    if comments_per_hour is None:
        return None
    return round(comments_per_hour, 3)


def resolve_comments_per_hour_duration_sec(
    *,
    chat_data_duration_sec: Any,
    activity_map_duration_sec: Any,
) -> int | None:
    chat_duration_sec = parse_int(chat_data_duration_sec)
    if chat_duration_sec is not None and chat_duration_sec > 0:
        return chat_duration_sec
    activity_duration_sec = parse_int(activity_map_duration_sec)
    if activity_duration_sec is not None and activity_duration_sec > 0:
        return activity_duration_sec
    return None


def calculate_comments_per_hour(chat_total: int, duration_sec: int | None) -> float | None:
    if duration_sec is None or duration_sec <= 0:
        return None
    return round(float(chat_total) / (float(duration_sec) / 3600.0), 3)


def to_public_video_entry(video: dict[str, Any]) -> dict[str, Any]:
    vod_id = str(video.get("vod_id") or "").strip()
    public_video = {
        "vod_id": vod_id,
        "vod_url": video.get("vod_url") or f"https://www.twitch.tv/videos/{vod_id}",
        "title": video.get("title", ""),
        "published_at": video.get("published_at", ""),
        "thumbnail_url": video.get("thumbnail_url", ""),
        "duration_sec": parse_int(video.get("duration_sec")),
        "count": int(video.get("count") or len(video.get("items") or [])),
        "chat_total": normalize_chat_total(video.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(video.get("comments_per_hour")),
        "items": [to_public_item_entry(item) for item in (video.get("items") or [])],
        "activity_map": to_public_activity_map(video.get("activity_map")),
    }
    provider = str(video.get("provider") or "").strip().lower()
    if provider and provider != "twitch":
        public_video["provider"] = provider
    return public_video


def to_public_video_index_entry(video: dict[str, Any]) -> dict[str, Any]:
    vod_id = str(video.get("vod_id") or "").strip()
    public_video = {
        "vod_id": vod_id,
        "vod_url": video.get("vod_url") or f"https://www.twitch.tv/videos/{vod_id}",
        "title": video.get("title", ""),
        "published_at": video.get("published_at", ""),
        "thumbnail_url": video.get("thumbnail_url", ""),
        "duration_sec": parse_int(video.get("duration_sec")),
        "count": int(video.get("count") or len(video.get("items") or [])),
        "chat_total": normalize_chat_total(video.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(video.get("comments_per_hour")),
        "detail_path": build_vod_detail_path(vod_id),
    }
    provider = str(video.get("provider") or "").strip().lower()
    if provider and provider != "twitch":
        public_video["provider"] = provider
    return public_video


def build_vod_detail_path(vod_id: str) -> str:
    return f"/data/vods/{vod_id}.json"


def to_public_activity_map(value: Any) -> dict[str, Any]:
    activity_map = normalize_activity_map(value)
    activity_map.pop("peak_count", None)
    return activity_map


def format_json_with_compact_arrays(value: Any) -> str:
    rendered = render_json_value(value, level=0, path=())
    return f"{rendered}\n"


def write_json_payload(path: Path, value: Any) -> None:
    path.write_text(format_json_with_compact_arrays(value), encoding=JSON_WRITE_ENCODING)


def render_json_value(value: Any, *, level: int, path: tuple[str, ...]) -> str:
    if isinstance(value, dict):
        if not value:
            return "{}"
        indent = "  " * level
        next_indent = "  " * (level + 1)
        parts: list[str] = []
        items = list(value.items())
        for index, (key, child) in enumerate(items):
            key_text = json.dumps(str(key), ensure_ascii=False)
            child_text = render_json_value(child, level=level + 1, path=path + (str(key),))
            line = f"{next_indent}{key_text}: {child_text}"
            if index < len(items) - 1:
                line += ","
            parts.append(line)
        return "{\n" + "\n".join(parts) + "\n" + indent + "}"

    if isinstance(value, list):
        if (
            path[-2:] in COMPACT_ARRAY_PATHS
            and value
            and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
        ):
            return render_compact_numeric_array(value, level=level)

        if not value:
            return "[]"
        indent = "  " * level
        next_indent = "  " * (level + 1)
        parts: list[str] = []
        for index, child in enumerate(value):
            child_text = render_json_value(child, level=level + 1, path=path)
            line = f"{next_indent}{child_text}"
            if index < len(value) - 1:
                line += ","
            parts.append(line)
        return "[\n" + "\n".join(parts) + "\n" + indent + "]"

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_compact_numeric_array(values: list[int | float], *, level: int) -> str:
    indent = "  " * level
    line_indent = "  " * (level + 1)
    chunks = [
        values[index : index + COMPACT_ARRAY_ITEMS_PER_LINE]
        for index in range(0, len(values), COMPACT_ARRAY_ITEMS_PER_LINE)
    ]
    lines: list[str] = []
    for chunk_index, chunk in enumerate(chunks):
        numbers = ", ".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in chunk)
        suffix = "," if chunk_index < len(chunks) - 1 else ""
        lines.append(f"{line_indent}{numbers}{suffix}")
    return "[\n" + "\n".join(lines) + "\n" + indent + "]"


def to_public_item_entry(item: dict[str, Any]) -> dict[str, Any]:
    public_item = {field: item[field] for field in PUBLIC_ITEM_FIELDS if field in item}
    start_sec = parse_int(public_item.get("start_sec"))
    end_sec = parse_int(public_item.get("end_sec"))
    if start_sec is not None and end_sec is not None and "duration_sec" not in public_item:
        public_item["duration_sec"] = max(0, end_sec - start_sec)
    if start_sec is not None and "start_time" not in public_item:
        public_item["start_time"] = format_hhmmss(start_sec)
    if end_sec is not None and "end_time" not in public_item:
        public_item["end_time"] = format_hhmmss(end_sec)
    tags = public_item.get("tags")
    if isinstance(tags, list):
        public_item["tags"] = normalize_tag_labels(tags)
    segment_id = str(public_item.get("id") or "").strip()
    vod_id = infer_vod_id_from_segment_id(segment_id)
    screenshot_url = resolve_public_segment_screenshot_url_if_exists(vod_id, segment_id)
    if screenshot_url:
        public_item["screenshot_url"] = screenshot_url
    else:
        public_item.pop("screenshot_url", None)
    return public_item


def infer_vod_id_from_segment_id(segment_id: str) -> str:
    value = str(segment_id or "").strip()
    if not value:
        return ""
    match = re.fullmatch(r"(.+)_([0-9]+)_([0-9]+)", value)
    if not match:
        return ""
    head = match.group(1)
    # Twitch IDs are numeric, while YouTube IDs are alphanumeric and may
    # contain '-' or '_'. Keep the whitelist tight because this value is also
    # used to resolve a local thumbnail path.
    return head if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", head) else ""


def has_segment_screenshot_file(vod_id: str, segment_id: str) -> bool:
    if not vod_id or not segment_id:
        return False
    screenshot_path = build_segment_screenshot_file_path(vod_id, segment_id)
    if not screenshot_path.exists():
        return False
    try:
        return screenshot_path.stat().st_size > 0
    except OSError:
        return False


def resolve_public_segment_screenshot_url_if_exists(vod_id: str, segment_id: str) -> str:
    if not has_segment_screenshot_file(vod_id, segment_id):
        return ""
    return build_segment_screenshot_public_path(vod_id, segment_id)


def sanitize_video_for_storage(video: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "vod_id",
        "provider",
        "vod_url",
        "title",
        "published_at",
        "thumbnail_url",
        "duration_sec",
        "count",
        "chat_total",
        "comments_per_hour",
        "items",
        "activity_map",
        "analysis_version",
        "analyzed_at",
    )
    sanitized = {field: video[field] for field in fields if field in video}
    sanitized["items"] = [sanitize_item_for_storage(item) for item in (video.get("items") or [])]
    return sanitized


def sanitize_item_for_storage(item: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "rank",
        "id",
        "start_sec",
        "end_sec",
        "duration_sec",
        "start_time",
        "end_time",
        "reason",
        "headline",
        "tags",
        "watch_url",
        "screenshot_url",
    )
    return {field: item[field] for field in fields if field in item}


def order_public_videos(videos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [video for video in videos if str(video.get("vod_id") or "").strip()],
        key=lambda item: str(item.get("published_at", "")),
        reverse=True,
    )


def parse_timezone_aware_iso_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def is_public_vod_within_retention(video: dict[str, Any], now: datetime) -> bool:
    published_at = parse_timezone_aware_iso_datetime(video.get("published_at"))
    if not published_at:
        return False
    cutoff = now - timedelta(days=PUBLIC_VOD_RETENTION_DAYS)
    return published_at >= cutoff


def filter_public_videos_within_retention(videos: Iterable[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    ordered_videos = order_public_videos(videos)
    return [video for video in ordered_videos if is_public_vod_within_retention(video, now)]


def collect_public_vod_id_set(videos: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(video.get("vod_id") or "").strip()
        for video in videos
        if str(video.get("vod_id") or "").strip()
    }


def cleanup_stale_segment_thumbnail_dirs(public_vod_ids: set[str]) -> list[str]:
    removed_vod_ids: list[str] = []
    if SEGMENT_THUMBNAILS_DIR.exists():
        for child in sorted(SEGMENT_THUMBNAILS_DIR.iterdir(), key=lambda path: path.name):
            if not child.is_dir():
                continue
            vod_id = child.name.strip()
            if not vod_id or vod_id in public_vod_ids:
                continue
            shutil.rmtree(child)
            removed_vod_ids.append(vod_id)

    captions_dir = SEGMENT_THUMBNAILS_DIR.parent / "captions"
    if captions_dir.is_dir():
        for caption_path in captions_dir.glob("*.json"):
            if caption_path.stem not in public_vod_ids:
                caption_path.unlink()
    return removed_vod_ids


def find_missing_public_screenshot_urls(public_videos: Iterable[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for video in public_videos:
        vod_id = str(video.get("vod_id") or "").strip()
        for item in video.get("items") or []:
            screenshot_url = str(item.get("screenshot_url") or "").strip()
            if not screenshot_url:
                continue
            segment_id = str(item.get("id") or "").strip()
            if not has_segment_screenshot_file(vod_id, segment_id):
                missing.append(screenshot_url)
    return missing


def assert_public_screenshot_urls_are_resolvable(public_videos: Iterable[dict[str, Any]]) -> None:
    missing = find_missing_public_screenshot_urls(public_videos)
    if missing:
        sample = ", ".join(missing[:3])
        raise RuntimeError(f"public screenshot_url references missing files: {sample}")
