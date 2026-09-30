from __future__ import annotations

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


class ProcessYoutubeBundleTests(unittest.TestCase):
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
