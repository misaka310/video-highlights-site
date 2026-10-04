from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import process_youtube_bundle  # noqa: E402
from youtube_handoff import create_material_batch_bundle  # noqa: E402


class ProcessYoutubeBundleTests(unittest.TestCase):
    def test_caption_only_retry_updates_existing_vod_without_reenrichment(self) -> None:
        video_id = "WGTrmrSvZH0"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "vod_index.json").write_text(
                '{"videos":[{"provider":"youtube","vod_id":"WGTrmrSvZH0"}]}',
                encoding="utf-8",
            )
            captions = root / "captions.json"
            captions.write_text(
                '{"video_id":"WGTrmrSvZH0","source":"youtube_automatic_captions",'
                '"language":"ja","language_source":"ja","fetched_at":"2026-10-05T00:00:00Z",'
                '"cues":[{"start_sec":0,"end_sec":1,"text":"字幕"}]}',
                encoding="utf-8",
            )
            bundle = root / "captions-only.tar.gz"
            create_material_batch_bundle(bundle, [], caption_updates=[(video_id, captions)])

            with (
                patch.object(process_youtube_bundle, "DATA_DIR", data_dir),
                patch.object(process_youtube_bundle, "enrich_youtube_video") as enrich,
                patch.object(process_youtube_bundle, "write_public_data") as write_public,
                patch.object(process_youtube_bundle, "write_processed_cache") as write_cache,
            ):
                result = process_youtube_bundle.process_bundle(
                    bundle,
                    now=datetime(2026, 10, 5, tzinfo=timezone.utc),
                )

            stored = json.loads((data_dir / "captions" / f"{video_id}.json").read_text(encoding="utf-8"))

        self.assertEqual(stored["cues"][0]["text"], "字幕")
        self.assertEqual(result["caption_updates"][0]["status"], "written")
        enrich.assert_not_called()
        write_public.assert_not_called()
        write_cache.assert_not_called()

    def test_uses_oracle_selected_intervals_without_redetecting_from_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_path = root / "clip.wav"
            screenshot_path = root / "clip.webp"
            destination_path = root / "public" / "clip.webp"
            audio_path.write_bytes(b"audio")
            screenshot_path.write_bytes(b"image")
            manifest = {
                "video": {
                    "provider": "youtube",
                    "vod_id": "WGTrmrSvZH0",
                    "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    "title": "test video",
                    "published_at": "2026-09-17T00:00:00+00:00",
                    "thumbnail_url": "https://i.ytimg.com/vi/WGTrmrSvZH0/hqdefault.jpg",
                    "duration_sec": 500,
                },
                "chat_offsets": [{"content_offset_seconds": 125}],
                "selected_highlights": [
                    {
                        "id": "WGTrmrSvZH0_120_150",
                        "rank": 1,
                        "start_sec": 120,
                        "end_sec": 150,
                        "score": 4.562,
                        "tags": ["好プレー"],
                    }
                ],
                "media": [
                    {
                        "item_id": "WGTrmrSvZH0_120_150",
                        "start_sec": 120,
                        "end_sec": 150,
                        "audio_path": "clip.wav",
                        "screenshot_path": "clip.webp",
                    }
                ],
            }
            enriched_inputs = []

            def capture_enrichment(video, **_kwargs):
                enriched_inputs.append(video)
                return video, SimpleNamespace(transcribed=0, headlines=0)

            with (
                patch("update_vods.detect_items") as detect_items,
                patch.object(process_youtube_bundle, "build_segment_screenshot_file_path", return_value=destination_path),
                patch.object(process_youtube_bundle, "enrich_youtube_video", side_effect=capture_enrichment),
                patch.object(process_youtube_bundle, "load_processed_cache", return_value={"videos": []}),
                patch.object(process_youtube_bundle, "write_processed_cache"),
                patch.object(process_youtube_bundle, "write_public_data"),
            ):
                process_youtube_bundle._process_manifest(
                    manifest,
                    root,
                    datetime(2026, 10, 1, tzinfo=timezone.utc),
                )

            detect_items.assert_not_called()
            self.assertEqual(
                [
                    (item["start_sec"], item["end_sec"])
                    for item in enriched_inputs[0]["items"]
                ],
                [(120, 150)],
            )
            self.assertEqual(enriched_inputs[0]["items"][0]["rank"], 1)
            self.assertEqual(enriched_inputs[0]["items"][0]["tags"], ["好プレー"])
            self.assertIn("z-score=4.562", enriched_inputs[0]["items"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
