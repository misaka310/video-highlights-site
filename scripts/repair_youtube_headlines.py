from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from typing import Any

from headline_candidate_selection import (
    build_headline_source_text,
    is_publishable_headline,
    is_valid_headline_source_text,
)
from transcription.config import PipelineSettings
from update_vods import DATA_DIR, load_processed_cache, write_processed_cache, write_public_data
from vod_serialization import filter_youtube_videos
from youtube_captions import collect_caption_text, validate_captions_payload


VOD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _require_remote_headline(result: Any, *, source_text: str, item_id: str) -> str:
    headline = str(getattr(result, "text", "") or "").strip()
    source = str(getattr(result, "source", "") or "").strip().lower()
    mode = str(getattr(result, "generation_mode", "") or "").strip()
    notes = str(getattr(result, "notes", "") or "").strip()
    if (
        not headline
        or source not in {"gemini", "groq", "nvidia"}
        or mode == "fallback_extractive"
        or notes == "local_candidate"
    ):
        raise RuntimeError(f"headline repair produced no remote LLM headline for {item_id}")
    if not is_publishable_headline(headline, source_text=source_text):
        raise RuntimeError(f"headline repair rejected low-quality headline for {item_id}")
    return headline


def repair_video_headlines(
    video: dict[str, Any],
    captions_payload: dict[str, Any],
    *,
    headline_generator: Any,
    source_config: dict[str, Any],
) -> int:
    cues = list(captions_payload.get("cues") or [])
    repaired = 0
    for item in video.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        start_sec = float(item.get("start_sec") or 0.0)
        end_sec = float(item.get("end_sec") or 0.0)
        if not item_id or end_sec <= start_sec:
            raise RuntimeError("headline repair found an invalid highlight interval")

        caption_text = collect_caption_text(cues, start_sec, end_sec)
        if not caption_text:
            raise RuntimeError(f"headline repair found no captions for {item_id}")
        validation_source_text = build_headline_source_text(caption_text, source_config) or caption_text
        source_validation = is_valid_headline_source_text(validation_source_text, source_config)

        result = headline_generator.generate(
            video_title=str(video.get("title") or "").strip(),
            start_time=str(item.get("start_time") or start_sec),
            end_time=str(item.get("end_time") or end_sec),
            transcript=caption_text,
            prepared_transcript=caption_text,
            source_validation=source_validation,
        )
        headline = _require_remote_headline(result, source_text=caption_text, item_id=item_id)
        item["headline"] = headline
        repaired += 1
        print(
            "headline repair:"
            f" item={item_id}"
            f" source={getattr(result, 'source', '')}"
            f" model={getattr(result, 'model', '')}"
            f" headline={headline}"
        )
    if repaired == 0:
        raise RuntimeError("headline repair found no highlight items")
    return repaired


def repair_vod(vod_id: str) -> int:
    if not VOD_ID_RE.fullmatch(vod_id):
        raise ValueError("vod id must be an 11-character YouTube id")

    from transcribe_segments import (
        apply_pipeline_settings,
        build_headline_generator,
        build_headline_source_config,
        refresh_runtime_configuration,
    )

    settings = PipelineSettings.from_env(os.environ)
    apply_pipeline_settings(settings)
    refresh_runtime_configuration()
    source_config = build_headline_source_config()
    headline_generator = build_headline_generator()

    cache_payload = load_processed_cache()
    videos = [
        item
        for item in cache_payload.get("videos", [])
        if isinstance(item, dict) and str(item.get("vod_id") or "").strip()
    ]
    video = next((item for item in videos if str(item.get("vod_id") or "").strip() == vod_id), None)
    if video is None:
        raise RuntimeError(f"headline repair could not find cached VOD {vod_id}")

    captions_path = DATA_DIR / "captions" / f"{vod_id}.json"
    if not captions_path.is_file():
        raise RuntimeError(f"headline repair requires committed captions for {vod_id}")
    captions_payload = validate_captions_payload(
        json.loads(captions_path.read_text(encoding="utf-8-sig")),
        expected_video_id=vod_id,
    )

    repaired = repair_video_headlines(
        video,
        captions_payload,
        headline_generator=headline_generator,
        source_config=source_config,
    )
    now = datetime.now().astimezone()
    write_processed_cache(videos, now)
    write_public_data(filter_youtube_videos(videos), now)
    return repaired


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate one cached YouTube VOD's headlines from committed captions.")
    parser.add_argument("--vod-id", required=True)
    args = parser.parse_args()
    repaired = repair_vod(str(args.vod_id).strip())
    print(f"headline repair complete: vod_id={args.vod_id} repaired={repaired}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
