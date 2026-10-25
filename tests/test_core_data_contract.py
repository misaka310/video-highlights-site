import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import public_vod_exclusions
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
    def test_5vz_retention_exception_is_published_to_cache_and_public_data(self):
        now = uv.datetime(2026, 10, 25, tzinfo=uv.JST_TIMEZONE)
        target = {
            "provider": "youtube",
            "vod_id": "5VzXYJdQwMY",
            "vod_url": "https://www.youtube.com/watch?v=5VzXYJdQwMY",
            "title": "target",
            "published_at": "2026-08-16T00:00:00+00:00",
            "items": [],
        }
        ordinary_old = {**target, "vod_id": "ordinary-old", "title": "ordinary old"}
        self.assertTrue(vs.is_public_vod_within_retention(target, now))
        self.assertFalse(vs.is_public_vod_within_retention(ordinary_old, now))
        self.assertEqual(
            ["5VzXYJdQwMY"],
            [video["vod_id"] for video in vs.filter_public_videos_within_retention([target, ordinary_old], now)],
        )

        cache_path = uv.CACHE_PATH
        output_path = uv.OUT_PATH
        index_path = uv.VOD_INDEX_PATH
        details_dir = uv.VOD_DETAILS_DIR
        data_dir = uv.DATA_DIR
        thumbnails_dir = vs.SEGMENT_THUMBNAILS_DIR
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                uv.CACHE_PATH = root / "processed_vods.json"
                uv.OUT_PATH = root / "vods.json"
                uv.VOD_INDEX_PATH = root / "vod_index.json"
                uv.VOD_DETAILS_DIR = root / "vods"
                uv.DATA_DIR = root
                vs.SEGMENT_THUMBNAILS_DIR = root / "segment-thumbnails"
                uv.write_processed_cache([target, ordinary_old], now)
                cached = json.loads(uv.CACHE_PATH.read_text(encoding="utf-8"))
                self.assertCountEqual(["5VzXYJdQwMY", "ordinary-old"], [video["vod_id"] for video in cached["videos"]])

                uv.write_public_data([target, ordinary_old], now)
                public = json.loads(uv.OUT_PATH.read_text(encoding="utf-8"))
                index = json.loads(uv.VOD_INDEX_PATH.read_text(encoding="utf-8"))
                self.assertEqual(["5VzXYJdQwMY"], [video["vod_id"] for video in public["videos"]])
                self.assertEqual(["5VzXYJdQwMY"], [video["vod_id"] for video in index["videos"]])
                self.assertTrue((uv.VOD_DETAILS_DIR / "5VzXYJdQwMY.json").exists())
                self.assertFalse((uv.VOD_DETAILS_DIR / "ordinary-old.json").exists())
        finally:
            uv.CACHE_PATH = cache_path
            uv.OUT_PATH = output_path
            uv.VOD_INDEX_PATH = index_path
            uv.VOD_DETAILS_DIR = details_dir
            uv.DATA_DIR = data_dir
            vs.SEGMENT_THUMBNAILS_DIR = thumbnails_dir

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

    def test_next_update_is_the_next_daily_target_after_generation(self):
        updated_at = uv.datetime(2026, 10, 4, 7, 57, tzinfo=uv.JST_TIMEZONE)

        self.assertEqual(
            uv.next_scheduled_update_at(updated_at),
            uv.datetime(2026, 10, 4, 0, 0, tzinfo=uv.timezone.utc),
        )

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

        all_ids = [
            video["vod_id"]
            for payload in (processed, public, index)
            for video in payload.get("videos", [])
        ]
        self.assertEqual(frozenset({"5VzXYJdQwMY"}), vs.PUBLIC_VOD_RETENTION_EXCEPTION_IDS)
        self.assertNotIn("5VzXYJdQwMY", public_vod_exclusions.PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS)
        for excluded_id in public_vod_exclusions.PERMANENTLY_EXCLUDED_PUBLIC_VOD_IDS:
            self.assertNotIn(excluded_id, all_ids)
            self.assertFalse((ROOT / "data" / "captions" / f"{excluded_id}.json").exists())
            self.assertFalse((ROOT / "data" / "vods" / f"{excluded_id}.json").exists())
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
