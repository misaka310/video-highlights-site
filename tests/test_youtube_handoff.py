from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from youtube_handoff import (  # noqa: E402
    build_material_manifest,
    create_material_bundle,
    create_material_batch_bundle,
    extract_material_bundle,
    validate_material_batch_manifest,
    validate_material_manifest,
)


class YoutubeHandoffTests(unittest.TestCase):
    def _manifest(self) -> dict:
        return build_material_manifest(
            {
                "provider": "youtube",
                "vod_id": "WGTrmrSvZH0",
                "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                "title": "test",
                "published_at": "2026-09-17T00:00:00+00:00",
                "thumbnail_url": "https://i.ytimg.com/vi/WGTrmrSvZH0/hqdefault.jpg",
                "duration_sec": 1000,
            },
            [
                {"content_offset_seconds": 100.0, "message": "private text must not be bundled"},
                {"content_offset_seconds": 101.0, "author_name": "private user"},
            ],
            [
                {
                    "id": "WGTrmrSvZH0_90_120",
                    "rank": 1,
                    "start_sec": 90,
                    "end_sec": 120,
                    "score": 3.25,
                    "tags": ["好プレー"],
                }
            ],
        )

    def test_manifest_contains_offsets_only(self) -> None:
        manifest = self._manifest()
        self.assertIn("chat_offsets", manifest)
        self.assertNotIn("comments", manifest)
        self.assertNotIn("message", json.dumps(manifest, ensure_ascii=False))
        self.assertNotIn("author", json.dumps(manifest, ensure_ascii=False))
        self.assertEqual(manifest["selected_highlights"][0]["score"], 3.25)
        self.assertEqual(manifest["selected_highlights"][0]["tags"], ["好プレー"])
        self.assertEqual(validate_material_manifest(manifest), manifest)

    def test_manifest_rejects_unclassified_text_in_selected_tags(self) -> None:
        manifest = self._manifest()
        manifest["selected_highlights"][0]["tags"] = ["private text must not be bundled"]
        with self.assertRaisesRegex(ValueError, "unrecognized tag"):
            validate_material_manifest(manifest)

    def test_manifest_rejects_highlight_ids_outside_the_selected_video_interval(self) -> None:
        manifest = self._manifest()
        manifest["selected_highlights"][0]["id"] = "../outside"
        with self.assertRaisesRegex(ValueError, "does not match its video interval"):
            validate_material_manifest(manifest)

    def test_bundle_round_trip_is_limited_to_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio = root / "audio.wav"
            screenshot = root / "screenshot.webp"
            audio.write_bytes(b"wav")
            screenshot.write_bytes(b"webp")
            captions = root / "captions.json"
            captions.write_text(
                json.dumps(
                    {
                        "video_id": "WGTrmrSvZH0",
                        "source": "youtube_automatic_captions",
                        "language": "ja",
                        "language_source": "ja",
                        "fetched_at": "2026-09-19T00:00:00Z",
                        "cues": [{"start_sec": 0, "end_sec": 1, "text": "字幕"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            bundle = root / "material.tar.gz"
            create_material_bundle(
                bundle,
                self._manifest(),
                {"clips/clip-0.wav": audio, "clips/clip-0.webp": screenshot},
                captions_file=captions,
            )
            extracted = extract_material_bundle(bundle, root / "out")
            self.assertEqual(extracted["video"]["vod_id"], "WGTrmrSvZH0")
            self.assertTrue((root / "out" / "captions.json").is_file())
            self.assertTrue((root / "out" / "clips" / "clip-0.wav").is_file())
            self.assertTrue((root / "out" / "clips" / "clip-0.webp").is_file())

    def test_extraction_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "unsafe.tar.gz"
            with tarfile.open(bundle, "w:gz") as archive:
                payload = b"{}"
                info = tarfile.TarInfo("../escape")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(ValueError):
                extract_material_bundle(bundle, root / "out")

    def test_batch_bundle_round_trip_keeps_each_video_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entries = []
            for video_id in ("WGTrmrSvZH0", "2a_ATYeOiAQ"):
                audio = root / f"{video_id}.wav"
                screenshot = root / f"{video_id}.webp"
                audio.write_bytes(b"wav")
                screenshot.write_bytes(b"webp")
                captions = root / f"{video_id}.json"
                captions.write_text(
                    json.dumps(
                        {
                            "video_id": video_id,
                            "source": "youtube_automatic_captions",
                            "language": "ja",
                            "language_source": "ja",
                            "fetched_at": "2026-09-19T00:00:00Z",
                            "cues": [{"start_sec": 0, "end_sec": 1, "text": "字幕"}],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                manifest = self._manifest()
                manifest["video"]["vod_id"] = video_id
                manifest["video"]["vod_url"] = f"https://www.youtube.com/watch?v={video_id}"
                manifest["selected_highlights"][0]["id"] = f"{video_id}_90_120"
                manifest["media"][0]["item_id"] = f"{video_id}_90_120"
                entries.append(
                    (
                        manifest,
                        {"clips/clip-0.wav": audio, "clips/clip-0.webp": screenshot},
                        captions,
                    )
                )
            bundle = root / "batch.tar.gz"
            create_material_batch_bundle(bundle, entries)
            extracted = extract_material_bundle(bundle, root / "out")

            self.assertEqual(extracted["schema_version"], 2)
            self.assertEqual(
                [entry["video"]["vod_id"] for entry in extracted["videos"]],
                ["WGTrmrSvZH0", "2a_ATYeOiAQ"],
            )
            self.assertTrue((root / "out" / "videos" / "WGTrmrSvZH0" / "captions.json").is_file())
            self.assertTrue((root / "out" / "videos" / "2a_ATYeOiAQ" / "clips" / "clip-0.wav").is_file())

    def test_batch_manifest_preserves_caption_only_updates(self) -> None:
        video_id = "2a_ATYeOiAQ"
        manifest = self._manifest()
        prefix = "videos/WGTrmrSvZH0/"
        entry = dict(manifest)
        entry["media"] = [
            {
                **media,
                "audio_path": prefix + media["audio_path"],
                "screenshot_path": prefix + media["screenshot_path"],
            }
            for media in manifest["media"]
        ]
        update = {
            "video_id": video_id,
            "captions_path": f"caption-updates/{video_id}.json",
        }

        normalized = validate_material_batch_manifest(
            {
                "schema_version": 2,
                "videos": [entry],
                "caption_updates": [update],
            }
        )

        self.assertEqual(normalized.get("caption_updates"), [update])

    def test_caption_only_batch_round_trip_has_no_video_material(self) -> None:
        video_id = "2a_ATYeOiAQ"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            captions = root / "captions.json"
            captions.write_text(
                json.dumps(
                    {
                        "video_id": video_id,
                        "source": "youtube_automatic_captions",
                        "language": "ja",
                        "language_source": "ja",
                        "fetched_at": "2026-10-05T00:00:00Z",
                        "cues": [{"start_sec": 0, "end_sec": 1, "text": "字幕"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            bundle = root / "captions-only.tar.gz"
            create_material_batch_bundle(
                bundle,
                [],
                caption_updates=[(video_id, captions)],
            )

            extracted = extract_material_bundle(bundle, root / "out")

            self.assertEqual(extracted["videos"], [])
            self.assertEqual(extracted["caption_updates"][0]["video_id"], video_id)
            self.assertTrue((root / "out" / "caption-updates" / f"{video_id}.json").is_file())

    def test_actions_workflow_receives_material_without_youtube_downloader(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "process-youtube-material.yml").read_text(encoding="utf-8")
        timer = (ROOT / "ops" / "oracle" / "youtube-highlight.timer").read_text(encoding="utf-8")
        service = (ROOT / "ops" / "oracle" / "youtube-highlight.service").read_text(encoding="utf-8")
        self.assertNotIn("yt-dlp", workflow)
        self.assertNotIn("YOUTUBE_ORACLE_BUNDLE_DELETE_URL", workflow)
        self.assertIn("repository_dispatch", workflow)
        self.assertIn("data/captions", workflow)
        self.assertIn("OnCalendar=*-*-* 06:07:00 Asia/Tokyo", timer)
        self.assertIn("EnvironmentFile=-/etc/youtube-highlight/youtube.env", service)


if __name__ == "__main__":
    unittest.main()
