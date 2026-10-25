from __future__ import annotations

from typing import Any, Iterable, Mapping

# Explicit privacy removals only. Membership-required archives are handled by the Oracle job.
PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS = frozenset()


def is_public_vod_excluded(video: Mapping[str, Any]) -> bool:
    return str(video.get("vod_id") or "").strip() in PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS


def filter_excluded_public_vods(videos: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [video for video in videos if not is_public_vod_excluded(video)]
