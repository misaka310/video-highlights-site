from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import youtube_captions as yc  # noqa: E402


class YoutubeCaptionsTests(unittest.TestCase):
    def test_converts_json3_into_bounded_public_cues(self):
        payload = {
            "events": [
                {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "  こんにちは\n"}]},
                {"tStartMs": 3000, "dDurationMs": 1500, "segs": [{"utf8": "次です"}]},
            ]
        }
        cues = yc.build_cues_from_json3_payload(payload)
        self.assertEqual(cues[0], {"start_sec": 1.0, "end_sec": 3.0, "text": "こんにちは"})
        self.assertEqual(cues[1], {"start_sec": 3.0, "end_sec": 4.5, "text": "次です"})

    def test_round_trip_validates_video_and_source(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "abc.ja.json3"
            source.write_text(
                json.dumps(
                    {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "字幕"}]}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            payload = yc.convert_json3_file(
                video_id="WGTrmrSvZH0",
                json3_path=source,
                language_source="ja",
                source=yc.CAPTIONS_SOURCE_AUTOMATIC,
            )
            output = root / "captions.json"
            yc.write_captions_payload(output, payload, expected_video_id="WGTrmrSvZH0")
            stored = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(stored["video_id"], "WGTrmrSvZH0")
            self.assertEqual(stored["source"], yc.CAPTIONS_SOURCE_AUTOMATIC)
            self.assertEqual(stored["cues"][0]["text"], "字幕")

    def test_collect_caption_text_joins_only_overlapping_cues(self):
        cues = [
            {"start_sec": 0, "end_sec": 5, "text": "before"},
            {"start_sec": 120, "end_sec": 130, "text": "会上がった。"},
            {"start_sec": 128, "end_sec": 140, "text": "会上がった。"},
            {"start_sec": 135, "end_sec": 150, "text": "すごいな。"},
            {"start_sec": 200, "end_sec": 210, "text": "after"},
        ]
        text = yc.collect_caption_text(cues, 120, 150)
        self.assertIn("会上がった", text)
        self.assertIn("すごいな", text)
        self.assertNotIn("before", text)
        self.assertNotIn("after", text)
        self.assertEqual(text.count("会上がった"), 1)

    def test_collect_caption_text_returns_empty_without_overlap(self):
        cues = [{"start_sec": 300, "end_sec": 320, "text": "外側"}]
        self.assertEqual(yc.collect_caption_text(cues, 120, 240), "")
        self.assertEqual(yc.collect_caption_text([], 120, 240), "")

    def test_rejects_mismatched_video_id(self):
        payload = yc.build_captions_payload(
            video_id="WGTrmrSvZH0",
            language_source="ja",
            source=yc.CAPTIONS_SOURCE_MANUAL,
            cues=[{"start_sec": 0, "end_sec": 1, "text": "字幕"}],
        )
        with self.assertRaises(ValueError):
            yc.validate_captions_payload(payload, expected_video_id="2a_ATYeOiAQ")


if __name__ == "__main__":
    unittest.main()
