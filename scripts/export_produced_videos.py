"""制作動画データから、公開してよい制作動画だけを書き出す。

リポジトリは動画本体を保持しない。`video_url` が絶対URL（http/https）の制作動画だけを公開し、
開発サーバー専用のローカルパス（`/media/...`）は公開物へ出さない。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ABSOLUTE_PREFIXES = ("http://", "https://")


def select_public_videos(payload: Any) -> list[dict[str, Any]]:
    videos = payload.get("videos") if isinstance(payload, dict) else None
    if not isinstance(videos, list):
        return []
    selected: list[dict[str, Any]] = []
    for video in videos:
        if not isinstance(video, dict):
            continue
        video_url = str(video.get("video_url") or "").strip()
        if not video_url.startswith(ABSOLUTE_PREFIXES):
            continue
        if not str(video.get("video_id") or "").strip() or not str(video.get("title") or "").strip():
            continue
        selected.append(video)
    return selected


def build_public_payload(payload: Any) -> dict[str, Any]:
    updated_at = payload.get("updated_at") if isinstance(payload, dict) else ""
    return {
        "updated_at": str(updated_at or ""),
        "videos": select_public_videos(payload),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: export_produced_videos.py <source.json> <dest.json>", file=sys.stderr)
        return 2
    source = Path(argv[1])
    destination = Path(argv[2])
    payload: Any = {}
    if source.is_file():
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(build_public_payload(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
