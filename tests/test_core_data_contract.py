import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_vods as uv
import vod_serialization as vs


VIDEO_FIELDS = {
    "vod_id",
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
}
ITEM_FIELDS = {
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
}
INDEX_FIELDS = VIDEO_FIELDS - {"items", "activity_map"} | {"detail_path"}
RETIRED_KEY_PARTS = (
    "".join(("trans", "cript")),
    "".join(("you", "tube")),
    "".join(("time", "stamp")),
)


def iter_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_keys(child)


class CoreDataContractTests(unittest.TestCase):
    def test_public_feed_keeps_five_latest_videos(self):
        now = uv.datetime(2026, 9, 20, tzinfo=uv.JST_TIMEZONE)
        videos = [
            {
                "provider": "youtube",
                "vod_id": f"{index:011d}",
                "vod_url": f"https://www.youtube.com/watch?v={index:011d}",
                "title": str(index),
                "published_at": f"2026-09-{20 - index:02d}T00:00:00+00:00",
                "items": [],
            }
            for index in range(6)
        ]
        payload = uv.build_public_payload(videos, now)
        self.assertEqual(len(payload["videos"]), 5)

    def test_storage_sanitizer_is_whitelist_based(self):
        source = {
            "vod_id": "1",
            "vod_url": "https://www.twitch.tv/videos/1",
            "title": "sample",
            "published_at": "2026-07-01T00:00:00+00:00",
            "items": [
                {
                    "id": "1_10_20",
                    "start_sec": 10,
                    "end_sec": 20,
                    "reason": "z-score",
                    "headline": "legacy",
                }
            ],
            "activity_map": {"bucket_sec": 10, "duration_sec": 20, "buckets": [0, 1]},
            "youtube_video_id": "legacy",
            "transcript_path": "legacy",
            "timestamps": [{"start_sec": 10}],
        }
        sanitized = uv.sanitize_video_for_storage(source)
        self.assertTrue(set(sanitized) <= VIDEO_FIELDS | {"provider", "analysis_version", "analyzed_at"})
        self.assertTrue(set(sanitized["items"][0]) <= ITEM_FIELDS)
        self.assertEqual(sanitized["items"][0]["headline"], "legacy")
        self.assertEqual([key for key in iter_keys(sanitized) if any(part in key.lower() for part in RETIRED_KEY_PARTS)], [])

    def test_repository_json_uses_core_contract(self):
        processed = json.loads((ROOT / "data" / "processed_vods.json").read_text(encoding="utf-8-sig"))
        public = json.loads((ROOT / "data" / "vods.json").read_text(encoding="utf-8-sig"))
        index = json.loads((ROOT / "data" / "vod_index.json").read_text(encoding="utf-8-sig"))

        for video in processed.get("videos", []):
            self.assertTrue(set(video) <= VIDEO_FIELDS | {"provider", "analysis_version", "analyzed_at"})
            for item in video.get("items", []):
                self.assertTrue(set(item) <= ITEM_FIELDS)
        for video in public.get("videos", []):
            self.assertEqual(set(video), VIDEO_FIELDS | ({"provider"} if video.get("provider") else set()))
            for item in video.get("items", []):
                self.assertTrue(set(item) <= ITEM_FIELDS)
        for video in index.get("videos", []):
            self.assertEqual(set(video), INDEX_FIELDS | ({"provider"} if video.get("provider") else set()))

        for payload in (processed, public, index):
            bad = [key for key in iter_keys(payload) if any(part in key.lower() for part in RETIRED_KEY_PARTS)]
            self.assertEqual(bad, [])

    def test_repository_json_is_utf8_without_bom(self):
        paths = [
            ROOT / "data" / "processed_vods.json",
            ROOT / "data" / "vods.json",
            ROOT / "data" / "vod_index.json",
            *(ROOT / "data" / "vods").glob("*.json"),
        ]
        with_bom = [str(path.relative_to(ROOT)) for path in paths if path.read_bytes().startswith(b"\xef\xbb\xbf")]
        self.assertEqual(with_bom, [])

    def test_cleanup_removes_captions_outside_public_retention(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            original = vs.SEGMENT_THUMBNAILS_DIR
            try:
                vs.SEGMENT_THUMBNAILS_DIR = root / "segment-thumbnails"
                captions = root / "captions"
                captions.mkdir()
                (captions / "keep.json").write_text("{}", encoding="utf-8")
                (captions / "stale.json").write_text("{}", encoding="utf-8")
                vs.cleanup_stale_segment_thumbnail_dirs({"keep"})
                self.assertTrue((captions / "keep.json").is_file())
                self.assertFalse((captions / "stale.json").exists())
            finally:
                vs.SEGMENT_THUMBNAILS_DIR = original

    def test_youtube_ids_resolve_segment_thumbnail_paths(self):
        self.assertEqual(
            "WGTrmrSvZH0",
            uv.infer_vod_id_from_segment_id("WGTrmrSvZH0_11900_11980"),
        )
        self.assertEqual(
            "2a_ATYeOiAQ",
            uv.infer_vod_id_from_segment_id("2a_ATYeOiAQ_4770_4850"),
        )
        self.assertEqual("2873115795", uv.infer_vod_id_from_segment_id("2873115795_10_20"))
        self.assertEqual("", uv.infer_vod_id_from_segment_id("../outside_10_20"))


if __name__ == "__main__":
    unittest.main()
