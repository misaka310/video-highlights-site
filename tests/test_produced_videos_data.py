import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCED_VIDEOS = ROOT / "data" / "produced_videos.json"


class ProducedVideosDataTests(unittest.TestCase):
    def test_entries_expose_required_fields_with_local_posters(self):
        payload = json.loads(PRODUCED_VIDEOS.read_text(encoding="utf-8-sig"))
        videos = payload.get("videos")
        self.assertIsInstance(videos, list)
        self.assertTrue(videos, "produced_videos.json must list at least one video")

        for video in videos:
            for key in ("video_id", "title", "video_url", "duration_sec", "published_at"):
                self.assertTrue(str(video.get(key) or "").strip(), f"{key} is required")
            self.assertGreater(float(video["duration_sec"]), 0)

            poster = str(video.get("poster_url") or "").strip()
            if poster and not poster.startswith(("http://", "https://")):
                self.assertTrue((ROOT / "data" / poster).is_file(), f"missing poster: {poster}")

            chapters = video.get("chapters") or []
            self.assertIsInstance(chapters, list)
            starts = [float(chapter["start_sec"]) for chapter in chapters]
            self.assertEqual(starts, sorted(starts), "chapters must be ordered by start_sec")
            self.assertEqual(len(starts), len(set(starts)), "chapters must not repeat a start_sec")
            for chapter in chapters:
                self.assertTrue(str(chapter.get("label") or "").strip())
                self.assertLess(float(chapter["start_sec"]), float(video["duration_sec"]))

    def test_trailer_public_copy_omits_internal_version_and_repository_details(self):
        payload = json.loads(PRODUCED_VIDEOS.read_text(encoding="utf-8-sig"))
        trailer = next(video for video in payload["videos"] if video["video_id"] == "dotitao-trailer-2026")

        for field in ("title", "description", "credits", "poster_url"):
            public_value = str(trailer[field])
            for internal_word in ("v5", "正式採用", "制作正本", "dotitao-video-production"):
                self.assertNotIn(internal_word, public_value, f"{field} leaks production metadata")
        self.assertEqual("ドチタオ トレーラー", trailer["title"])
        self.assertEqual("produced-video-posters/dotitao-trailer.jpg", trailer["poster_url"])

    def test_trailer_uses_versionless_public_hls_entrypoint(self):
        payload = json.loads(PRODUCED_VIDEOS.read_text(encoding="utf-8-sig"))
        trailer = next(video for video in payload["videos"] if video["video_id"] == "dotitao-trailer-2026")
        self.assertEqual(
            "https://dotitao-moments.onrender.com/media/dotitao-trailer/master.m3u8",
            trailer["video_url"],
        )
        manifest_path = ROOT / "frontend" / "public" / "media" / "dotitao-trailer" / "master.m3u8"
        playlist = manifest_path.read_text(encoding="utf-8")
        self.assertTrue(playlist.startswith("#EXTM3U\n"))
        variant_urls = [line for line in playlist.splitlines() if line.startswith("https://")]
        self.assertEqual(3, len(variant_urls))
        self.assertEqual(3, playlist.count("#EXT-X-STREAM-INF:"))
        self.assertTrue(all(url.endswith("/index.m3u8") for url in variant_urls))

    def test_build_and_public_checks_copy_produced_videos(self):
        build = (ROOT / "scripts" / "build_public.sh").read_text(encoding="utf-8")
        check = (ROOT / "scripts" / "check_public_build.py").read_text(encoding="utf-8")

        self.assertIn("scripts/export_produced_videos.py", build)
        self.assertIn("public/data/produced_videos.json", build)
        self.assertIn("data/produced-video-posters", build)
        self.assertIn("produced_videos.json", check)
        self.assertIn("missing produced video poster", check)

    def test_public_export_keeps_only_absolute_video_urls(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from export_produced_videos import build_public_payload

        payload = {
            "updated_at": "2026-10-21T07:09:14+09:00",
            "videos": [
                {"video_id": "local", "title": "local", "video_url": "/media/local.mp4"},
                {"video_id": "remote", "title": "remote", "video_url": "https://example.com/v/remote"},
                {"video_id": "", "title": "broken", "video_url": "https://example.com/v/broken"},
                "invalid",
            ],
        }
        exported = build_public_payload(payload)
        self.assertEqual(["remote"], [video["video_id"] for video in exported["videos"]])
        self.assertEqual("2026-10-21T07:09:14+09:00", exported["updated_at"])
        self.assertEqual([], build_public_payload({})["videos"])
        self.assertEqual([], build_public_payload(None)["videos"])


if __name__ == "__main__":
    unittest.main()
