from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from project_config import load_project_config
import vod_sources as vod_source
from youtube_sources import fetch_youtube_video
from youtube_update import run_youtube_mode
from vod_sources import (  # noqa: F401
    ChatFetchResult,
    FetchConfig,
    build_twitch_api_headers,
    extract_commenter_user_name,
    extract_twitchdownloader_message_text,
    extract_twitchdownloader_user_name,
    fetch_chat_comments_gql,
    fetch_chat_data,
    fetch_chat_data_with_twitchdownloader,
    fetch_current_stream_status,
    fetch_json,
    fetch_latest_videos,
    fetch_latest_videos_from_twitch_api,
    fetch_latest_videos_from_twitchmetrics,
    fetch_text,
    fetch_twitch_app_access_token,
    fetch_twitch_user_id,
    has_twitch_api_credentials,
    is_channel_live,
    parse_twitchdownloader_chat_payload,
    post_gql,
    resolve_twitchdownloader_bin,
)
from vod_highlights import (  # noqa: F401
    BASE_TAG_RULES,
    CLOSING_CHATTER_PATTERNS,
    CLOSING_CHATTER_REGEX,
    SEGMENT_THUMBNAILS_DIR,
    TAG_RULES,
    DetectConfig,
    build_activity_map,
    build_segment_screenshot_file_path,
    build_segment_screenshot_public_path,
    build_watch_url,
    bucket_counts,
    calculate_closing_chatter_penalty,
    classify_segment_tags,
    classify_tags_from_texts,
    clean_html_text,
    collect_nearby_comment_texts,
    count_closing_chatter_hits,
    detect_items,
    extract_message_text,
    fallback_items,
    format_hhmmss,
    html_unescape,
    is_segment_in_last_seconds_window,
    merge_hot_buckets,
    merge_overlapping_segments,
    normalize_activity_map,
    normalize_thumbnail_url,
    parse_int,
    parse_twitch_duration_text,
    rank_segments,
    sec_to_twitch_timestamp,
    select_diverse_segments,
    to_local_iso,
    z_scores,
)

from vod_serialization import (  # noqa: F401
    TAG_LABEL_ALIASES,
    assert_public_screenshot_urls_are_resolvable,
    build_vod_detail_path,
    calculate_comments_per_hour,
    cleanup_stale_segment_thumbnail_dirs,
    collect_public_vod_id_set,
    filter_public_videos_within_retention,
    find_missing_public_screenshot_urls,
    format_json_with_compact_arrays,
    has_segment_screenshot_file,
    infer_vod_id_from_segment_id,
    is_public_vod_within_retention,
    normalize_chat_total,
    normalize_comments_per_hour,
    normalize_tag_labels,
    order_public_videos,
    parse_non_negative_float,
    parse_timezone_aware_iso_datetime,
    refresh_cached_video_metadata,
    render_compact_numeric_array,
    render_json_value,
    resolve_comments_per_hour_duration_sec,
    resolve_public_segment_screenshot_url_if_exists,
    sanitize_item_for_storage,
    sanitize_video_for_storage,
    to_public_activity_map,
    to_public_item_entry,
    to_public_video_entry,
    to_public_video_index_entry,
    write_json_payload,
)

__all__ = (
    'ChatFetchResult',
    'FetchConfig',
    'build_twitch_api_headers',
    'extract_commenter_user_name',
    'extract_twitchdownloader_message_text',
    'extract_twitchdownloader_user_name',
    'fetch_chat_comments_gql',
    'fetch_chat_data',
    'fetch_chat_data_with_twitchdownloader',
    'fetch_current_stream_status',
    'fetch_json',
    'fetch_latest_videos',
    'fetch_latest_videos_from_twitch_api',
    'fetch_latest_videos_from_twitchmetrics',
    'fetch_text',
    'fetch_twitch_app_access_token',
    'fetch_twitch_user_id',
    'has_twitch_api_credentials',
    'is_channel_live',
    'parse_twitchdownloader_chat_payload',
    'post_gql',
    'resolve_twitchdownloader_bin',
    'fetch_youtube_video',
    'BASE_TAG_RULES',
    'CLOSING_CHATTER_PATTERNS',
    'CLOSING_CHATTER_REGEX',
    'SEGMENT_THUMBNAILS_DIR',
    'TAG_RULES',
    'DetectConfig',
    'build_activity_map',
    'build_segment_screenshot_file_path',
    'build_segment_screenshot_public_path',
    'build_watch_url',
    'bucket_counts',
    'calculate_closing_chatter_penalty',
    'classify_segment_tags',
    'classify_tags_from_texts',
    'clean_html_text',
    'collect_nearby_comment_texts',
    'count_closing_chatter_hits',
    'detect_items',
    'extract_message_text',
    'fallback_items',
    'format_hhmmss',
    'html_unescape',
    'is_segment_in_last_seconds_window',
    'merge_hot_buckets',
    'merge_overlapping_segments',
    'normalize_activity_map',
    'normalize_thumbnail_url',
    'parse_int',
    'parse_twitch_duration_text',
    'rank_segments',
    'sec_to_twitch_timestamp',
    'select_diverse_segments',
    'to_local_iso',
    'z_scores',
    'TAG_LABEL_ALIASES',
    'assert_public_screenshot_urls_are_resolvable',
    'build_vod_detail_path',
    'calculate_comments_per_hour',
    'cleanup_stale_segment_thumbnail_dirs',
    'collect_public_vod_id_set',
    'filter_public_videos_within_retention',
    'find_missing_public_screenshot_urls',
    'format_json_with_compact_arrays',
    'has_segment_screenshot_file',
    'infer_vod_id_from_segment_id',
    'is_public_vod_within_retention',
    'normalize_chat_total',
    'normalize_comments_per_hour',
    'normalize_tag_labels',
    'order_public_videos',
    'parse_non_negative_float',
    'parse_timezone_aware_iso_datetime',
    'refresh_cached_video_metadata',
    'render_compact_numeric_array',
    'render_json_value',
    'resolve_comments_per_hour_duration_sec',
    'resolve_public_segment_screenshot_url_if_exists',
    'sanitize_item_for_storage',
    'sanitize_video_for_storage',
    'to_public_activity_map',
    'to_public_item_entry',
    'to_public_video_entry',
    'to_public_video_index_entry',
    'write_json_payload',
)

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
LOCAL_ENV_BLOCKED_KEYS = frozenset({"TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"})
LOCAL_ENV_SECRET_SUFFIXES = ("_API_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_PRIVATE_KEY")
PROJECT_CONFIG = load_project_config(env={})
CHANNEL = PROJECT_CONFIG.twitch_channel_login
CHANNEL_URL = PROJECT_CONFIG.twitch_channel_url
TWITCHMETRICS_URL = PROJECT_CONFIG.twitchmetrics_url
TWITCH_API_CLIENT_ID = ""
TWITCH_API_CLIENT_SECRET = ""
TWITCH_GQL_CLIENT_ID = vod_source.DEFAULT_TWITCH_GQL_CLIENT_ID

def load_local_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in LOCAL_ENV_BLOCKED_KEYS or key.endswith(LOCAL_ENV_SECRET_SUFFIXES):
            continue
        value = value.strip().strip('"').strip("'"); os.environ.setdefault(key, value)


def configure_runtime_environment(mapping: Mapping[str, str] | None = None) -> None:
    source = os.environ if mapping is None else mapping
    project_config = load_project_config(env=source)
    client_id = str(source.get("TWITCH_CLIENT_ID") or "").strip()
    client_secret = str(source.get("TWITCH_CLIENT_SECRET") or "").strip()
    gql_client_id = str(source.get("TWITCH_GQL_CLIENT_ID") or vod_source.DEFAULT_TWITCH_GQL_CLIENT_ID).strip()
    vod_source.configure_source(
        channel=project_config.twitch_channel_login,
        twitchmetrics_url=project_config.twitchmetrics_url,
        client_id=client_id,
        client_secret=client_secret,
        gql_client_id=gql_client_id,
    )
    globals().update(
        PROJECT_CONFIG=project_config,
        CHANNEL=project_config.twitch_channel_login,
        CHANNEL_URL=project_config.twitch_channel_url,
        TWITCHMETRICS_URL=project_config.twitchmetrics_url,
        TWITCH_API_CLIENT_ID=client_id,
        TWITCH_API_CLIENT_SECRET=client_secret,
        TWITCH_GQL_CLIENT_ID=gql_client_id,
    )


configure_runtime_environment({})
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
OUT_PATH = DATA_DIR / "vods.json"
VOD_INDEX_PATH = DATA_DIR / "vod_index.json"
VOD_DETAILS_DIR = DATA_DIR / "vods"
CACHE_PATH = DATA_DIR / "processed_vods.json"
BACKFILL_SUMMARY_PATH = DATA_DIR / "backfill_summary.json"
ANALYSIS_VERSION = "chat-zscore-v8"
UPDATE_HOUR_LOCAL = 9
JST_TIMEZONE = timezone(timedelta(hours=9))
PUBLIC_VIDEO_LIMIT = 5
BACKFILL_DEFAULT_DAYS = 120
BACKFILL_SOURCE_LIMIT_MULTIPLIER = 3
BACKFILL_SOURCE_LIMIT_FLOOR = 30
TWITCH_LIVE_CHECK_ENABLED_DEFAULT = "1"
TWITCH_LIVE_CHECK_FAIL_OPEN_DEFAULT = "0"

JSON_READ_ENCODING = "utf-8-sig"


@dataclass(frozen=True)
class CliArgs:
    backfill: bool
    backfill_days: int
    backfill_limit: int | None
    force_reanalyze: bool
    youtube_url: str | None


@dataclass
class BackfillSummary:
    scanned: int = 0
    reused: int = 0
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0
    reused_vod_ids: list[str] = field(default_factory=list)
    failed_vod_ids: list[str] = field(default_factory=list)
    analyzed_details: list[dict[str, int | str]] = field(default_factory=list)

def main() -> None:
    load_local_env(ENV_PATH)
    configure_runtime_environment(os.environ)
    args = parse_cli_args()
    now = datetime.now().astimezone()
    if args.youtube_url:
        run_youtube_mode(
            now,
            args.youtube_url,
            analyze_video_entry=analyze_video_entry,
            load_processed_cache=load_processed_cache,
            write_processed_cache=write_processed_cache,
            write_public_data=write_public_data,
            output_path=OUT_PATH,
        )
        return
    if args.backfill:
        run_backfill_mode(now, args)
        return
    run_normal_mode(now)


def parse_cli_args() -> CliArgs:
    parser = argparse.ArgumentParser(description="Update Twitch highlight VOD cache and public JSON outputs.")
    parser.add_argument("--backfill", action="store_true", help="Enable local backfill mode.")
    parser.add_argument(
        "--backfill-days",
        type=int,
        default=BACKFILL_DEFAULT_DAYS,
        help=f"Backfill range in days (default: {BACKFILL_DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--backfill-limit",
        type=int,
        default=None,
        help="Optional max number of latest VODs to fetch for backfill.",
    )
    parser.add_argument(
        "--force-reanalyze",
        action="store_true",
        help="Force reanalysis for all scoped VODs (backfill mode only).",
    )
    parser.add_argument(
        "--youtube-url",
        default=None,
        help="Fetch and analyze one YouTube archive through the configured Oracle command.",
    )
    parsed = parser.parse_args()
    if parsed.backfill_days <= 0:
        parser.error("--backfill-days must be a positive integer")
    if parsed.backfill_limit is not None and parsed.backfill_limit <= 0:
        parser.error("--backfill-limit must be a positive integer")
    if not parsed.backfill:
        if parsed.backfill_limit is not None:
            parser.error("--backfill-limit requires --backfill")
        if parsed.force_reanalyze:
            parser.error("--force-reanalyze requires --backfill")
        if parsed.backfill_days != BACKFILL_DEFAULT_DAYS:
            parser.error("--backfill-days requires --backfill")
    if parsed.youtube_url and parsed.backfill:
        parser.error("--youtube-url cannot be combined with --backfill")
    return CliArgs(
        backfill=parsed.backfill,
        backfill_days=parsed.backfill_days,
        backfill_limit=parsed.backfill_limit,
        force_reanalyze=parsed.force_reanalyze,
        youtube_url=str(parsed.youtube_url).strip() if parsed.youtube_url else None,
    )

def run_normal_mode(now: datetime) -> None:
    target_count = PUBLIC_VIDEO_LIMIT
    source_limit = max(target_count * 2, target_count + 2)
    videos = fetch_latest_videos(limit=source_limit)
    skip_latest_candidate, skip_reason = resolve_live_skip_decision(CHANNEL)
    skipped_latest_vod_id = ""
    if skip_latest_candidate:
        skipped_latest_vod_id = resolve_latest_vod_id(videos)
        if skipped_latest_vod_id:
            print(f"skip_live_candidate: vod_id={skipped_latest_vod_id} reason={skip_reason}")
            videos = [video for video in videos if str(video.get("vod_id") or "").strip() != skipped_latest_vod_id]

    cache_payload = load_processed_cache()
    cached_videos = [item for item in cache_payload.get("videos", []) if item.get("vod_id")]
    cached_by_vod_id = {
        item["vod_id"]: item
        for item in cached_videos
    }
    selected_videos: list[dict[str, Any]] = []

    selected_vod_ids: set[str] = set()
    for video in videos:
        if len(selected_videos) >= target_count:
            break
        resolved = resolve_video_entry(video, cached_by_vod_id, now)
        if not resolved:
            continue
        selected_videos.append(resolved)
        cached_by_vod_id[resolved["vod_id"]] = resolved
        selected_vod_ids.add(resolved["vod_id"])

    if len(selected_videos) < target_count:
        for cached in cached_videos:
            cached_vod_id = str(cached.get("vod_id") or "").strip()
            if not cached_vod_id or cached_vod_id in selected_vod_ids:
                continue
            selected_videos.append(cached)
            selected_vod_ids.add(cached_vod_id)
            print(f"fallback {cached_vod_id}")
            if len(selected_videos) >= target_count:
                break

    if not selected_videos:
        raise RuntimeError("No valid videos available; refusing to overwrite data files")

    write_processed_cache(cached_by_vod_id.values(), now)
    write_public_data(cached_by_vod_id.values(), now)
    print(f"wrote {OUT_PATH}")


def run_backfill_mode(now: datetime, args: CliArgs) -> None:
    cache_payload = load_processed_cache()
    cached_videos = [item for item in cache_payload.get("videos", []) if item.get("vod_id")]
    cached_by_vod_id = {item["vod_id"]: item for item in cached_videos}

    source_limit = determine_backfill_source_limit(args.backfill_days, args.backfill_limit)
    videos = fetch_latest_videos(limit=source_limit)
    scoped_videos = select_backfill_videos(videos, now, args.backfill_days)
    summary = BackfillSummary(scanned=len(scoped_videos))

    print(
        "backfill mode:"
        f" days={args.backfill_days}"
        f" source_limit={source_limit}"
        f" fetched={len(videos)}"
        f" scoped={len(scoped_videos)}"
        f" force_reanalyze={'true' if args.force_reanalyze else 'false'}"
    )

    for video in scoped_videos:
        vod_id = video["vod_id"]
        cached = cached_by_vod_id.get(vod_id)
        if not should_reanalyze_cached_video(cached, force_reanalyze=args.force_reanalyze):
            print(f"reuse {vod_id}")
            cached_by_vod_id[vod_id] = merge_video_metadata(video, cached or {})
            summary.reused += 1
            summary.reused_vod_ids.append(vod_id)
            continue

        analyzed_video, status = analyze_video_entry(video, now)
        if analyzed_video:
            cached_by_vod_id[vod_id] = analyzed_video
            summary.analyzed += 1
            summary.analyzed_details.append(build_analyzed_detail_entry(analyzed_video))
            continue

        if status == "failed":
            summary.failed += 1
            summary.failed_vod_ids.append(vod_id)
        else:
            summary.skipped += 1

        if cached:
            print(f"keep-cache {vod_id}")
            cached_by_vod_id[vod_id] = merge_video_metadata(video, cached)

    write_processed_cache(cached_by_vod_id.values(), now)
    write_public_data(cached_by_vod_id.values(), now)
    write_backfill_summary_file(
        summary,
        now,
        backfill_days=args.backfill_days,
        source_limit=source_limit,
        fetched_count=len(videos),
        scoped_count=len(scoped_videos),
        force_reanalyze=args.force_reanalyze,
    )
    print_backfill_summary(summary)
    print("wrote data/vods.json")


def determine_backfill_source_limit(backfill_days: int, backfill_limit: int | None) -> int:
    if backfill_limit is not None:
        return backfill_limit
    return max(BACKFILL_SOURCE_LIMIT_FLOOR, backfill_days * BACKFILL_SOURCE_LIMIT_MULTIPLIER)


def select_backfill_videos(videos: list[dict[str, str]], now: datetime, backfill_days: int) -> list[dict[str, str]]:
    cutoff = now - timedelta(days=backfill_days)
    scoped: list[dict[str, str]] = []
    for video in videos:
        published_at = parse_timezone_aware_iso_datetime(video.get("published_at"))
        if not published_at:
            continue
        if published_at < cutoff:
            break
        scoped.append(video)
    return scoped


def print_backfill_summary(summary: BackfillSummary) -> None:
    print("backfill summary:")
    print(f"  scanned={summary.scanned}")
    print(f"  reused={summary.reused}")
    print(f"  analyzed={summary.analyzed}")
    print(f"  skipped={summary.skipped}")
    print(f"  failed={summary.failed}")
    print("  analyzed_vod_ids:")
    if summary.analyzed_details:
        for detail in summary.analyzed_details:
            print(
                "    -"
                f" {detail['vod_id']}"
                f" items_count={detail['items_count']}"
                f" activity_bucket_count={detail['activity_bucket_count']}"
            )
    else:
        print("    - (none)")
    print(f"  reused_vod_ids: {format_vod_id_list(summary.reused_vod_ids)}")
    print(f"  failed_vod_ids: {format_vod_id_list(summary.failed_vod_ids)}")
    print("  summary_file: data/backfill_summary.json")


def build_analyzed_detail_entry(video: dict[str, Any]) -> dict[str, int | str]:
    items = video.get("items")
    activity_map = normalize_activity_map(video.get("activity_map"))
    buckets = activity_map.get("buckets")
    return {
        "vod_id": str(video.get("vod_id") or "").strip(),
        "items_count": len(items) if isinstance(items, list) else 0,
        "activity_bucket_count": len(buckets) if isinstance(buckets, list) else 0,
    }


def format_vod_id_list(vod_ids: list[str]) -> str:
    return ", ".join(vod_ids) if vod_ids else "(none)"


def write_backfill_summary_file(
    summary: BackfillSummary,
    now: datetime,
    *,
    backfill_days: int,
    source_limit: int,
    fetched_count: int,
    scoped_count: int,
    force_reanalyze: bool,
) -> None:
    payload = {
        "mode": "backfill",
        "updated_at": now.isoformat(timespec="seconds"),
        "backfill_days": backfill_days,
        "source_limit": source_limit,
        "fetched": fetched_count,
        "scoped": scoped_count,
        "force_reanalyze": force_reanalyze,
        "counts": {
            "scanned": summary.scanned,
            "reused": summary.reused,
            "analyzed": summary.analyzed,
            "skipped": summary.skipped,
            "failed": summary.failed,
        },
        "analyzed": summary.analyzed_details,
        "reused": summary.reused_vod_ids,
        "failed": summary.failed_vod_ids,
    }
    write_json_payload(BACKFILL_SUMMARY_PATH, payload)


def next_scheduled_update_at(now: datetime) -> datetime:
    base = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    now_jst = base.astimezone(JST_TIMEZONE)
    scheduled_jst = now_jst.replace(hour=UPDATE_HOUR_LOCAL, minute=0, second=0, microsecond=0)
    if scheduled_jst <= now_jst:
        scheduled_jst += timedelta(days=1)
    return scheduled_jst.astimezone(timezone.utc)


def get_positive_int_env(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def env_flag_is_enabled(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def twitch_live_check_enabled() -> bool:
    return env_flag_is_enabled("TWITCH_LIVE_CHECK_ENABLED", default=(TWITCH_LIVE_CHECK_ENABLED_DEFAULT == "1"))


def twitch_live_check_fail_open() -> bool:
    return env_flag_is_enabled("TWITCH_LIVE_CHECK_FAIL_OPEN", default=(TWITCH_LIVE_CHECK_FAIL_OPEN_DEFAULT == "1"))


def resolve_live_skip_decision(channel_login: str | None = None) -> tuple[bool, str]:
    channel_login = str(channel_login or CHANNEL).strip()
    if not twitch_live_check_enabled():
        print(f"twitch_live_status: channel={channel_login} live_check_enabled=false")
        return False, "live_check_disabled"

    try:
        status = fetch_current_stream_status(channel_login)
    except Exception as exc:
        fail_open = twitch_live_check_fail_open()
        print(
            f"twitch_live_status_error: channel={channel_login}"
            f" error={exc}"
            f" fail_open={'true' if fail_open else 'false'}"
        )
        if fail_open:
            return False, "live_check_failed_fail_open"
        return True, "live_check_failed_safe_mode"

    if bool(status.get("live")):
        print(
            f"twitch_live_status: channel={channel_login} live=true"
            f" stream_id={status.get('stream_id') or ''}"
            f" started_at={status.get('started_at') or ''}"
        )
        return True, "channel_live"

    print(f"twitch_live_status: channel={channel_login} live=false")
    return False, "channel_offline"


def sort_videos_by_published_at_desc(videos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(video: dict[str, Any]) -> tuple[float, str]:
        published_at = parse_timezone_aware_iso_datetime(video.get("published_at"))
        timestamp = published_at.timestamp() if published_at else -1.0
        return (timestamp, str(video.get("vod_id") or ""))

    normalized = [video for video in videos if str(video.get("vod_id") or "").strip()]
    return sorted(normalized, key=key, reverse=True)


def resolve_latest_vod_id(videos: Iterable[dict[str, Any]]) -> str:
    ordered = sort_videos_by_published_at_desc(videos)
    if not ordered:
        return ""
    return str(ordered[0].get("vod_id") or "").strip()


def load_processed_cache() -> dict[str, Any]:
    for path in (CACHE_PATH, OUT_PATH):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding=JSON_READ_ENCODING))
        except json.JSONDecodeError:
            continue
        videos = payload.get("videos") or payload.get("vods") or []
        normalized = [normalize_cached_video(video) for video in videos]
        return {
            "channel": payload.get("channel", CHANNEL),
            "analysis_version": payload.get("analysis_version", ANALYSIS_VERSION),
            "videos": [video for video in normalized if video],
        }
    return {"channel": CHANNEL, "analysis_version": ANALYSIS_VERSION, "videos": []}


def normalize_cached_video(video: dict[str, Any]) -> dict[str, Any] | None:
    vod_id = str(video.get("vod_id") or video.get("id") or "").strip()
    if not vod_id:
        return None
    items = video.get("items") or video.get("segments") or []
    normalized = {
        "vod_id": vod_id,
        "vod_url": video.get("vod_url") or video.get("url") or f"https://www.twitch.tv/videos/{vod_id}",
        "title": video.get("title", ""),
        "published_at": video.get("published_at", ""),
        "thumbnail_url": video.get("thumbnail_url", ""),
        "duration_sec": video.get("duration_sec"),
        "count": int(video.get("count") or len(items)),
        "chat_total": normalize_chat_total(video.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(video.get("comments_per_hour")),
        "items": items,
        "activity_map": normalize_activity_map(video.get("activity_map")),
        "analysis_version": video.get("analysis_version", ANALYSIS_VERSION),
        "analyzed_at": video.get("analyzed_at") or video.get("updated_at") or "",
    }
    provider = str(video.get("provider") or "").strip().lower()
    if provider and provider != "twitch":
        normalized["provider"] = provider
    return normalized


def resolve_video_entry(
    video: dict[str, str], cached_by_vod_id: dict[str, dict[str, Any]], now: datetime
) -> dict[str, Any] | None:
    vod_id = video["vod_id"]
    cached = cached_by_vod_id.get(vod_id)
    if is_reusable_cached_video(cached):
        print(f"reuse {vod_id}")
        return merge_video_metadata(video, cached)

    analyzed_video, _ = analyze_video_entry(video, now)
    return analyzed_video


def analyze_video_entry(
    video: dict[str, str],
    now: datetime,
    *,
    chat_data_override: ChatFetchResult | None = None,
    metadata_override: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    vod_id = video["vod_id"]
    print(f"analyze {vod_id}")
    try:
        provider = str(video.get("provider") or "twitch").strip().lower()
        resolved_video: dict[str, Any] = dict(video)
        if metadata_override:
            resolved_video.update(metadata_override)
        if provider == "youtube" and chat_data_override is None:
            youtube_result = fetch_youtube_video(str(resolved_video.get("vod_url") or vod_id))
            resolved_video.update(youtube_result.video)
            chat_data = youtube_result.chat
        else:
            chat_data = chat_data_override or fetch_chat_data(
                vod_id,
                FetchConfig(),
                provider=provider,
                vod_url=str(resolved_video.get("vod_url") or ""),
            )
        comments = chat_data.comments
        chat_total = len(comments)
        activity_map = build_activity_map(comments, DetectConfig(), chat_data.duration_sec)
        comments_per_hour_duration_sec = resolve_comments_per_hour_duration_sec(
            chat_data_duration_sec=chat_data.duration_sec,
            activity_map_duration_sec=activity_map.get("duration_sec"),
        )
        comments_per_hour = calculate_comments_per_hour(chat_total, comments_per_hour_duration_sec)
        items = detect_items(
            comments,
            vod_id,
            DetectConfig(),
            total_duration_sec=comments_per_hour_duration_sec,
        )
        if provider == "youtube":
            for item in items:
                start_sec = parse_int(item.get("start_sec"))
                if start_sec is not None:
                    item["watch_url"] = build_youtube_watch_url(vod_id, start_sec)
    except Exception as exc:
        print(f"warn: skip {vod_id} ({exc})")
        return None, "failed"

    if not items:
        print(f"warn: skip {vod_id} (no detectable segments)")
        return None, "skipped"

    analyzed = {
        "vod_id": vod_id,
        "vod_url": resolved_video.get("vod_url") or video["vod_url"],
        "title": resolved_video.get("title") or video.get("title") or "",
        "published_at": resolved_video.get("published_at") or video.get("published_at") or "",
        "thumbnail_url": resolved_video.get("thumbnail_url") or video.get("thumbnail_url") or "",
        "duration_sec": comments_per_hour_duration_sec,
        "count": len(items),
        "chat_total": chat_total,
        "comments_per_hour": comments_per_hour,
        "items": items,
        "activity_map": activity_map,
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at": now.isoformat(timespec="seconds"),
    }
    if provider and provider != "twitch":
        analyzed["provider"] = provider
    return analyzed, "analyzed"


def build_youtube_watch_url(vod_id: str, start_sec: int) -> str:
    return f"https://www.youtube.com/watch?v={vod_id}&t={max(0, int(start_sec))}s"


def is_reusable_cached_video(video: dict[str, Any] | None) -> bool:
    if not video:
        return False
    if video.get("analysis_version") != ANALYSIS_VERSION:
        return False
    items = video.get("items") or []
    return bool(items)


def should_reanalyze_cached_video(video: dict[str, Any] | None, *, force_reanalyze: bool = False) -> bool:
    if force_reanalyze:
        return True
    if not video:
        return True
    if video.get("analysis_version") != ANALYSIS_VERSION:
        return True

    items = video.get("items")
    if not isinstance(items, list) or not items:
        return True

    activity_map = video.get("activity_map")
    if not isinstance(activity_map, dict) or not activity_map:
        return True
    buckets = activity_map.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        return True
    return False


def merge_video_metadata(latest: dict[str, str], cached: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "vod_id": latest["vod_id"],
        "vod_url": latest["vod_url"],
        "title": latest["title"],
        "published_at": latest["published_at"],
        "thumbnail_url": latest["thumbnail_url"],
        "duration_sec": parse_int(cached.get("duration_sec")) or parse_int(latest.get("duration_sec")),
        "count": int(cached.get("count") or len(cached.get("items") or [])),
        "chat_total": normalize_chat_total(cached.get("chat_total")),
        "comments_per_hour": normalize_comments_per_hour(cached.get("comments_per_hour")),
        "items": cached.get("items") or [],
        "activity_map": normalize_activity_map(cached.get("activity_map")),
        "analysis_version": cached.get("analysis_version", ANALYSIS_VERSION),
        "analyzed_at": cached.get("analyzed_at", ""),
    }
    provider = str(latest.get("provider") or cached.get("provider") or "").strip().lower()
    if provider and provider != "twitch":
        merged["provider"] = provider
    return merged


def write_processed_cache(videos: Iterable[dict[str, Any]], now: datetime) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        [sanitize_video_for_storage(video) for video in videos if video.get("vod_id")],
        key=lambda item: item.get("published_at", ""),
        reverse=True,
    )
    payload = {
        "updated_at": now.isoformat(timespec="seconds"),
        "channel": CHANNEL,
        "channel_url": CHANNEL_URL,
        "analysis_version": ANALYSIS_VERSION,
        "videos": ordered,
    }
    write_json_payload(CACHE_PATH, payload)


def build_public_payload(videos: Iterable[dict[str, Any]], now: datetime) -> dict[str, Any]:
    filtered_videos = filter_public_videos_within_retention(videos, now)
    public_videos = [to_public_video_entry(video) for video in filtered_videos[:PUBLIC_VIDEO_LIMIT]]
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "next_update_at": next_scheduled_update_at(now).isoformat(timespec="seconds"),
        "videos": public_videos,
    }


def build_public_index_payload(videos: Iterable[dict[str, Any]], now: datetime) -> dict[str, Any]:
    filtered_videos = filter_public_videos_within_retention(videos, now)
    return {
        "updated_at": now.isoformat(timespec="seconds"),
        "next_update_at": next_scheduled_update_at(now).isoformat(timespec="seconds"),
        "videos": [to_public_video_index_entry(video) for video in filtered_videos],
    }


def write_public_data(videos: Iterable[dict[str, Any]], now: datetime) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    public_videos = filter_public_videos_within_retention(videos, now)
    public_vod_ids = collect_public_vod_id_set(public_videos)
    removed_vod_ids = cleanup_stale_segment_thumbnail_dirs(public_vod_ids)
    for vod_id in removed_vod_ids:
        print(f"pruned stale thumbnails for vod_id={vod_id}")

    latest_payload = build_public_payload(public_videos, now)
    assert_public_screenshot_urls_are_resolvable(latest_payload.get("videos") or [])
    write_json_payload(OUT_PATH, latest_payload)

    index_payload = build_public_index_payload(public_videos, now)
    write_json_payload(VOD_INDEX_PATH, index_payload)

    VOD_DETAILS_DIR.mkdir(parents=True, exist_ok=True)
    detail_videos = [to_public_video_entry(video) for video in public_videos]
    assert_public_screenshot_urls_are_resolvable(detail_videos)
    detail_vod_ids: set[str] = set()
    for public_video in detail_videos:
        vod_id = public_video["vod_id"]
        detail_vod_ids.add(vod_id)
        detail_path = VOD_DETAILS_DIR / f"{vod_id}.json"
        write_json_payload(detail_path, public_video)

    for stale_path in VOD_DETAILS_DIR.glob("*.json"):
        if stale_path.stem not in detail_vod_ids:
            stale_path.unlink()


if __name__ == "__main__":
    main()
