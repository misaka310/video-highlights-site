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
            [{"id": "WGTrmrSvZH0_90_120", "rank": 1, "start_sec": 90, "end_sec": 120}],
        )

    def test_manifest_contains_offsets_only(self) -> None:
        manifest = self._manifest()
        self.assertIn("chat_offsets", manifest)
        self.assertNotIn("comments", manifest)
        self.assertNotIn("message", json.dumps(manifest, ensure_ascii=False))
        self.assertNotIn("author", json.dumps(manifest, ensure_ascii=False))
        self.assertEqual(validate_material_manifest(manifest), manifest)

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
                entries.append(
                    (
                        self._manifest() | {"video": self._manifest()["video"] | {"vod_id": video_id}},
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
