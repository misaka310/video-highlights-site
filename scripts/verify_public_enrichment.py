"""Validate publishable headlines and screenshots for the latest public VOD entries."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from transcribe_segments import is_publishable_headline, validate_final_headline_japanese


VOD_INDEX_PATH = ROOT / "data" / "vod_index.json"


def load_runtime_public_videos(root: Path = ROOT) -> list[dict[str, Any]]:
    index_path = root / "data" / "vod_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    entries = index.get("videos") or []
    videos: list[dict[str, Any]] = []
    for entry in entries[:3]:
        vod_id = str(entry.get("vod_id") or "unknown")
        detail_path = str(entry.get("detail_path") or "").strip()
        if not detail_path:
            raise RuntimeError(f"vod_id={vod_id}: detail_path missing")
        detail_file = root / detail_path.lstrip("/")
        if not detail_file.is_file():
            raise RuntimeError(f"vod_id={vod_id}: detail payload missing")
        videos.append(json.loads(detail_file.read_text(encoding="utf-8-sig")))
    return videos


def collect_public_enrichment_failures(payload: dict[str, Any], *, root: Path = ROOT) -> list[str]:
    videos = payload.get("videos") or []
    failures: list[str] = []
    for video in videos[:3]:
        vod_id = str(video.get("vod_id") or "unknown")
        items = video.get("items") or []
        if not items:
            failures.append(f"vod_id={vod_id}: no highlight items")
            continue

        for item in items[:3]:
            segment_id = str(item.get("id") or "unknown")
            headline = str(item.get("headline") or "").strip()
            provider = str(video.get("provider") or "twitch").strip().lower()
            reason = str(item.get("reason") or "").strip()
            screenshot_url = str(item.get("screenshot_url") or "").strip()
            if headline:
                validation = validate_final_headline_japanese(headline)
                if not is_publishable_headline(headline):
                    reasons = ",".join(validation.reasons) or "publish_quality"
                    failures.append(f"segment_id={segment_id}: invalid headline ({reasons})")
            elif provider != "youtube" and not reason:
                # YouTube items without a publishable headline are published as
                # "見出し未生成" instead of blocking the whole update.
                failures.append(f"segment_id={segment_id}: headline missing")

            if not screenshot_url:
                failures.append(f"segment_id={segment_id}: screenshot_url missing")
                continue
            screenshot_path = root / screenshot_url.lstrip("/")
            if not screenshot_path.is_file() or screenshot_path.stat().st_size <= 0:
                failures.append(f"segment_id={segment_id}: screenshot file missing")

    return failures


def main() -> None:
    videos = load_runtime_public_videos()
    if not videos:
        raise RuntimeError("public VOD payload is empty")

    failures = collect_public_enrichment_failures({"videos": videos})
    if failures:
        raise RuntimeError("public enrichment incomplete: " + "; ".join(failures[:12]))

    print(f"public enrichment verified for {min(3, len(videos))} VODs")


if __name__ == "__main__":
    main()
