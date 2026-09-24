from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CAPTIONS_SOURCE_MANUAL = "youtube_manual_captions"
CAPTIONS_SOURCE_AUTOMATIC = "youtube_automatic_captions"
SUBTITLE_LANGUAGE_PRIORITY = ("ja-orig", "ja", "ja-jp")
_WS_RE = re.compile(r"\s+")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_subtitle_language_from_path(path: Path) -> str:
    name = path.name[:-6] if path.name.endswith(".json3") else path.name
    return name.rsplit(".", 1)[-1].strip().lower() if "." in name else ""


def _language_priority_score(language_source: str) -> tuple[int, str]:
    lang = str(language_source or "").strip().lower()
    if lang in SUBTITLE_LANGUAGE_PRIORITY:
        return (SUBTITLE_LANGUAGE_PRIORITY.index(lang), lang)
    if lang.startswith("ja"):
        return (len(SUBTITLE_LANGUAGE_PRIORITY), lang)
    return (len(SUBTITLE_LANGUAGE_PRIORITY) + 1, lang)


def pick_best_json3_file(paths: list[Path]) -> tuple[Path | None, str]:
    if not paths:
        return None, ""
    picked = sorted(
        paths,
        key=lambda path: (_language_priority_score(parse_subtitle_language_from_path(path)), path.name),
    )[0]
    return picked, parse_subtitle_language_from_path(picked)


def normalize_cue_text(raw: str) -> str:
    text = str(raw or "").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return _WS_RE.sub(" ", text).strip()


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def build_cues_from_json3_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = payload.get("events")
    if not isinstance(events, list):
        return []

    raw_cues: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        start_ms = _to_float(event.get("tStartMs"))
        segments = event.get("segs")
        if start_ms is None or not isinstance(segments, list):
            continue
        text = normalize_cue_text(
            "".join(str(segment.get("utf8") or "") for segment in segments if isinstance(segment, dict))
        )
        if not text:
            continue
        duration_ms = _to_float(event.get("dDurationMs"))
        raw_cues.append(
            {
                "start_sec": max(0.0, start_ms / 1000.0),
                "duration_sec": None if duration_ms is None else max(0.0, duration_ms / 1000.0),
                "text": text,
            }
        )

    cues: list[dict[str, Any]] = []
    for index, cue in enumerate(raw_cues):
        start_sec = float(cue["start_sec"])
        duration_sec = cue["duration_sec"]
        if isinstance(duration_sec, (int, float)) and duration_sec > 0:
            end_sec = start_sec + float(duration_sec)
        else:
            end_sec = next(
                (
                    float(candidate["start_sec"])
                    for candidate in raw_cues[index + 1 :]
                    if float(candidate["start_sec"]) >= start_sec
                ),
                start_sec,
            )
        cues.append(
            {
                "start_sec": round(start_sec, 3),
                "end_sec": round(max(start_sec, end_sec), 3),
                "text": cue["text"],
            }
        )

    merged: list[dict[str, Any]] = []
    for cue in cues:
        if merged:
            previous = merged[-1]
            if (
                previous["text"] == cue["text"]
                and float(cue["start_sec"]) <= float(previous["end_sec"]) + 0.3
            ):
                previous["end_sec"] = round(max(float(previous["end_sec"]), float(cue["end_sec"])), 3)
                continue
        merged.append(dict(cue))
    return merged


def build_captions_payload(
    *,
    video_id: str,
    language_source: str,
    source: str,
    cues: list[dict[str, Any]],
    fetched_at: str | None = None,
) -> dict[str, Any]:
    normalized_language = str(language_source or "").strip().lower()
    return {
        "video_id": str(video_id),
        "source": str(source),
        "language": "ja" if normalized_language.startswith("ja") else "unknown",
        "language_source": normalized_language or "unknown",
        "fetched_at": fetched_at or now_utc_iso(),
        "cues": cues,
    }


def convert_json3_file(
    *,
    video_id: str,
    json3_path: Path,
    language_source: str,
    source: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    payload = json.loads(Path(json3_path).read_text(encoding="utf-8-sig"))
    return build_captions_payload(
        video_id=video_id,
        language_source=language_source,
        source=source,
        cues=build_cues_from_json3_payload(payload),
        fetched_at=fetched_at,
    )


def validate_captions_payload(payload: Any, *, expected_video_id: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("captions payload must be an object")
    video_id = str(payload.get("video_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("captions payload has an invalid video id")
    if expected_video_id and video_id != expected_video_id:
        raise ValueError("captions payload video id does not match bundle video")
    source = str(payload.get("source") or "").strip()
    if source not in {CAPTIONS_SOURCE_MANUAL, CAPTIONS_SOURCE_AUTOMATIC}:
        raise ValueError("captions payload has an unsupported source")

    language = str(payload.get("language") or "").strip()
    language_source = str(payload.get("language_source") or "").strip()
    fetched_at = str(payload.get("fetched_at") or "").strip()
    raw_cues = payload.get("cues")
    if not isinstance(raw_cues, list) or not raw_cues or len(raw_cues) > 100_000:
        raise ValueError("captions payload must contain a bounded non-empty cue list")

    cues: list[dict[str, Any]] = []
    for cue in raw_cues:
        if not isinstance(cue, dict):
            raise ValueError("caption cue must be an object")
        start_sec = _to_float(cue.get("start_sec"))
        end_sec = _to_float(cue.get("end_sec"))
        text = normalize_cue_text(str(cue.get("text") or ""))
        if start_sec is None or end_sec is None or start_sec < 0 or end_sec < start_sec:
            raise ValueError("caption cue has invalid timing")
        if not text or len(text) > 2000:
            raise ValueError("caption cue has invalid text")
        cues.append(
            {
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "text": text,
            }
        )

    return {
        "video_id": video_id,
        "source": source,
        "language": language or ("ja" if language_source.lower().startswith("ja") else "unknown"),
        "language_source": language_source or "unknown",
        "fetched_at": fetched_at,
        "cues": cues,
    }


def collect_caption_text(cues: list[dict[str, Any]], start_sec: float, end_sec: float) -> str:
    """Join caption cues overlapping a highlight interval into one text blob."""

    parts: list[str] = []
    for cue in cues:
        cue_start = float(cue.get("start_sec") or 0.0)
        cue_end = float(cue.get("end_sec") or 0.0)
        if cue_end <= start_sec or cue_start >= end_sec:
            continue
        text = str(cue.get("text") or "").strip()
        if text and (not parts or parts[-1] != text):
            parts.append(text)
    return " ".join(parts).strip()


def write_captions_payload(path: Path, payload: Any, *, expected_video_id: str | None = None) -> None:
    validated = validate_captions_payload(payload, expected_video_id=expected_video_id)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(validated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


