"""Process an Oracle YouTube material bundle on GitHub Actions.

This entrypoint has no YouTube network client.  It accepts only the validated
manifest and the selected clips supplied by Oracle, then reuses the existing
highlight/output pipeline and runs Whisper locally in Actions.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from transcribe_segments import build_segment_screenshot_file_path, build_segment_screenshot_public_path
from update_vods import (
    ANALYSIS_VERSION,
    DATA_DIR,
    OUT_PATH,
    build_youtube_watch_url,
    load_processed_cache,
    write_processed_cache,
    write_public_data,
)
from vod_highlights import DetectConfig, build_activity_map, format_hhmmss, sec_to_twitch_timestamp
from vod_serialization import (
    calculate_comments_per_hour,
    filter_youtube_videos,
    resolve_comments_per_hour_duration_sec,
)
from youtube_enrichment import enrich_youtube_video
from youtube_handoff import extract_material_bundle
from youtube_captions import write_captions_payload


def _interval_key(start_sec: Any, end_sec: Any) -> tuple[int, int]:
    return int(start_sec), int(end_sec)


def _build_selected_items(video_id: str, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for item in selected:
        start_sec, end_sec = _interval_key(item["start_sec"], item["end_sec"])
        score = float(item.get("score") or 0.0)
        items.append(
            {
                "rank": int(item["rank"]),
                "id": str(item["id"]),
                "start_sec": start_sec,
                "end_sec": end_sec,
                "duration_sec": end_sec - start_sec,
                "start_time": format_hhmmss(start_sec),
                "end_time": format_hhmmss(end_sec),
                "reason": f"Chat activity spike around {sec_to_twitch_timestamp(start_sec)} (z-score={score}).",
                "tags": list(item.get("tags") or []),
                "watch_url": build_youtube_watch_url(video_id, start_sec),
            }
        )
    return items


def _build_oracle_analysis(manifest: dict[str, Any], active_now: datetime) -> dict[str, Any]:
    video = dict(manifest["video"])
    offsets = [
        {"content_offset_seconds": float(item["content_offset_seconds"])}
        for item in manifest["chat_offsets"]
    ]
    items = _build_selected_items(str(video["vod_id"]), list(manifest["selected_highlights"]))
    activity_map = build_activity_map(offsets, DetectConfig(), video.get("duration_sec"))
    duration_sec = resolve_comments_per_hour_duration_sec(
        chat_data_duration_sec=video.get("duration_sec"),
        activity_map_duration_sec=activity_map.get("duration_sec"),
    )
    analyzed: dict[str, Any] = {
        "provider": "youtube",
        "vod_id": str(video["vod_id"]),
        "vod_url": video.get("vod_url") or f"https://www.youtube.com/watch?v={video['vod_id']}",
        "title": video.get("title") or "",
        "published_at": video.get("published_at") or "",
        "thumbnail_url": video.get("thumbnail_url") or "",
        "duration_sec": duration_sec,
        "count": len(items),
        "chat_total": len(offsets),
        "comments_per_hour": calculate_comments_per_hour(len(offsets), duration_sec),
        "items": items,
        "activity_map": activity_map,
        "analysis_version": ANALYSIS_VERSION,
        "analyzed_at": active_now.isoformat(timespec="seconds"),
    }
    return analyzed


def _process_manifest(manifest: dict[str, Any], root: Path, active_now: datetime) -> dict[str, Any]:
    video = dict(manifest["video"])
    selected = list(manifest["selected_highlights"])
    analyzed = _build_oracle_analysis(manifest, active_now)

    item_by_interval = {
        _interval_key(item["start_sec"], item["end_sec"]): item
        for item in analyzed.get("items") or []
    }
    media_by_item_id: dict[str, dict[str, Path]] = {}
    for media in manifest["media"]:
        item_id = str(media["item_id"])
        item = item_by_interval.get(_interval_key(media["start_sec"], media["end_sec"]))
        if item is None:
            raise RuntimeError(f"missing selected interval for {item_id}")
        audio_path = root / media["audio_path"]
        screenshot_path = root / media["screenshot_path"]
        destination = build_segment_screenshot_file_path(video["vod_id"], item["id"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(screenshot_path, destination)
        item["screenshot_url"] = build_segment_screenshot_public_path(video["vod_id"], item["id"])
        media_by_item_id[item_id] = {"audio": audio_path, "screenshot": screenshot_path}

    def media_fetcher(_vod_url: str, start_sec: int, end_sec: int, _work_dir: Path) -> Path:
        item = item_by_interval.get((int(start_sec), int(end_sec)))
        if item is None or item["id"] not in media_by_item_id:
            raise RuntimeError("requested bundle interval is not present")
        return media_by_item_id[item["id"]]["audio"]

    captions_payload: dict[str, Any] | None = None
    captions_source_path = root / str(manifest.get("captions_path") or "captions.json")
    if captions_source_path.is_file():
        captions_payload = json.loads(captions_source_path.read_text(encoding="utf-8"))

    enriched, summary = enrich_youtube_video(
        analyzed,
        media_fetcher=media_fetcher,
        caption_cues=list((captions_payload or {}).get("cues") or []) or None,
    )
    cache_payload = load_processed_cache()
    cached_by_vod_id = {
        item["vod_id"]: item
        for item in cache_payload.get("videos", [])
        if item.get("vod_id")
    }
    cached_by_vod_id[enriched["vod_id"]] = enriched
    captions_written = False
    if captions_payload is not None:
        captions_destination = DATA_DIR / "captions" / f"{enriched['vod_id']}.json"
        write_captions_payload(
            captions_destination,
            captions_payload,
            expected_video_id=enriched["vod_id"],
        )
        captions_written = True
    write_processed_cache(cached_by_vod_id.values(), active_now)
    write_public_data(filter_youtube_videos(cached_by_vod_id.values()), active_now)
    result = {
        "vod_id": enriched["vod_id"],
        "chat_total": enriched["chat_total"],
        "highlights": len(enriched.get("items") or []),
        "transcribed": getattr(summary, "transcribed", 0),
        "headlines": getattr(summary, "headlines", 0),
        "screenshots": len(manifest["media"]),
        "captions": captions_written,
        "output": str(OUT_PATH),
    }
    print(
        "youtube bundle processed:"
        f" vod_id={result['vod_id']}"
        f" oracle_offsets={result['chat_total']}"
        f" highlights={result['highlights']}"
        f" transcribed={result['transcribed']}"
        f" headlines={result['headlines']}"
        f" screenshots={result['screenshots']}"
        f" captions={'yes' if result['captions'] else 'no'}"
    )
    return result


def process_bundle(bundle_path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Validate, enrich, and publish one single- or multi-video bundle."""

    active_now = now or datetime.now().astimezone()
    with tempfile.TemporaryDirectory(prefix="youtube-material-", dir=DATA_DIR.parent) as temp_dir:
        root = Path(temp_dir)
        manifest = extract_material_bundle(Path(bundle_path), root)
        if manifest.get("schema_version") == 2:
            results = [_process_manifest(entry, root, active_now) for entry in manifest["videos"]]
            return {"videos": results, "output": str(OUT_PATH)}
        return _process_manifest(manifest, root, active_now)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process a safe Oracle YouTube material bundle.")
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    process_bundle(args.bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
