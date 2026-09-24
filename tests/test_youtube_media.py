import io
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from youtube_media import (  # noqa: E402
    build_youtube_media_batch_script,
    build_youtube_media_script,
    build_youtube_screenshot_batch_script,
    classify_youtube_media_failure,
    fetch_youtube_segment_media_file,
    fetch_youtube_highlight_media_files,
)
from youtube_sources import YoutubeOracleConfig  # noqa: E402
from youtube_enrichment import enrich_youtube_video  # noqa: E402


class YoutubeMediaTests(unittest.TestCase):
    def test_media_script_cuts_one_selected_section_and_never_prints_chat(self):
        script = build_youtube_media_script("WGTrmrSvZH0", 120, 240)
        self.assertIn('--download-sections "*120-240"', script)
        self.assertIn('-f "worstaudio[protocol=https]/bestaudio[protocol=https]"', script)
        self.assertIn("tar -C", script)
        self.assertNotIn("live_chat", script)
        self.assertNotIn("message", script)

    def test_media_fetch_safely_unpacks_one_tar_member(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w") as archive:
            body = b"selected media"
            info = tarfile.TarInfo("clip.webm")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))

        config = YoutubeOracleConfig(
            host="oracle.example.test",
            user="oracle-user",
            key_path=Path(__file__),
            script_path=Path(__file__),
            timeout_sec=30,
        )

        def runner(command, **kwargs):
            return SimpleNamespace(returncode=0, stdout=payload.getvalue(), stderr=b"")

        with tempfile.TemporaryDirectory() as temp_dir:
            output = fetch_youtube_segment_media_file(
                "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                120,
                240,
                Path(temp_dir),
                config=config,
                runner=runner,
            )
            self.assertEqual(output.read_bytes(), b"selected media")

    def test_batch_media_script_cuts_only_selected_audio_intervals(self):
        script = build_youtube_media_batch_script("WGTrmrSvZH0", [(120, 180), (600, 660)])
        self.assertIn('-ss 120 -t 60 -i "$source_path" -vn -ac 1 -ar 16000', script)
        self.assertIn('-ss 600 -t 60 -i "$source_path" -vn -ac 1 -ar 16000', script)
        self.assertIn("-f \"worstaudio[protocol=https]/bestaudio[protocol=https]\"", script)
        self.assertIn("clip-0.wav", script)
        self.assertIn("clip-1.wav", script)

    def test_screenshot_batch_script_returns_only_selected_webp_stills(self):
        script = build_youtube_screenshot_batch_script("WGTrmrSvZH0", [(120, 180), (600, 660)])
        self.assertIn('-ss 120 -i "$source_path" -frames:v 1', script)
        self.assertIn('-ss 600 -i "$source_path" -frames:v 1', script)
        self.assertIn("clip-0.webp clip-1.webp", script)
        self.assertNotIn("live_chat", script)

    def test_batch_media_fetch_returns_only_expected_clip_indices(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w") as archive:
            for index in range(2):
                body = f"clip-{index}".encode()
                info = tarfile.TarInfo(f"clip-{index}.wav")
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
        config = YoutubeOracleConfig(
            host="oracle.example.test",
            user="oracle-user",
            key_path=Path(__file__),
            script_path=Path(__file__),
            timeout_sec=30,
        )

        def runner(command, **kwargs):
            return SimpleNamespace(returncode=0, stdout=payload.getvalue(), stderr=b"")

        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = fetch_youtube_highlight_media_files(
                "WGTrmrSvZH0",
                [(120, 180), (600, 660)],
                Path(temp_dir),
                config=config,
                runner=runner,
            )
            self.assertEqual(set(outputs), {0, 1})
            self.assertEqual(outputs[1].read_bytes(), b"clip-1")

    def test_media_failure_is_classified_without_exposing_details(self):
        self.assertEqual(
            classify_youtube_media_failure("Sign in to confirm you're not a bot"),
            "authentication_cookie_failure",
        )
        self.assertEqual(classify_youtube_media_failure("ffmpeg not found"), "oracle_ffmpeg_failure")

    def test_enrichment_uses_transcript_for_headline_and_strips_nothing_into_public_contract(self):
        video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "archive",
            "items": [{"id": "WGTrmrSvZH0_120_240", "start_sec": 120, "end_sec": 240, "tags": ["ww"]}],
        }

        def media_fetcher(_url, _start, _end, output_dir):
            path = output_dir / "clip.webm"
            path.write_bytes(b"clip")
            return path

        class FakeTranscriber:
            def transcribe(self, *_args, **_kwargs):
                return SimpleNamespace(
                    text="窓の外がうるさくて集中できない。迷路を突破してバナナにたどり着くのに。",
                    source_text="窓の外がうるさくて集中できない。迷路を突破してバナナにたどり着くのに。",
                    language="ja",
                    language_probability=0.9,
                    segments=None,
                )

        class FakeHeadlineGenerator:
            def generate(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    text="迷路を突破してバナナに到達",
                    source="groq",
                    model="openai/gpt-oss-120b",
                    generation_mode="llm_ranked",
                    confidence="high",
                    notes="",
                )

        headline_generator = FakeHeadlineGenerator()
        enriched, summary = enrich_youtube_video(
            video,
            media_fetcher=media_fetcher,
            transcriber=FakeTranscriber(),
            headline_generator=headline_generator,
        )
        self.assertEqual(summary.headlines, 1)
        self.assertIn("迷路", enriched["items"][0]["headline"])
        self.assertNotIn("ww", enriched["items"][0]["headline"])
        self.assertEqual(enriched["items"][0]["headline_source"], "groq")
        self.assertEqual(enriched["items"][0]["headline_model"], "openai/gpt-oss-120b")
        self.assertEqual(enriched["items"][0]["headline_generation_mode"], "llm_ranked")
        self.assertIn("迷路", headline_generator.kwargs["prepared_transcript"])

    def test_enrichment_skips_whisper_when_captions_cover_the_interval(self):
        video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "archive",
            "items": [{"id": "WGTrmrSvZH0_120_240", "start_sec": 120, "end_sec": 240, "tags": ["ww"]}],
        }

        def media_fetcher(_url, _start, _end, output_dir):
            path = output_dir / "clip.webm"
            path.write_bytes(b"clip")
            return path

        class FailIfCalledTranscriber:
            def transcribe(self, *_args, **_kwargs):
                raise AssertionError("whisper must not run when captions cover the interval")

        class FakeHeadlineGenerator:
            def generate(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    text="字幕から見出しを作る",
                    source="groq",
                    model="openai/gpt-oss-120b",
                    generation_mode="llm_ranked",
                    confidence="high",
                    notes="",
                )

        headline_generator = FakeHeadlineGenerator()
        enriched, summary = enrich_youtube_video(
            video,
            media_fetcher=media_fetcher,
            caption_cues=[
                {"start_sec": 118, "end_sec": 130, "text": "会上がった。"},
                {"start_sec": 130, "end_sec": 242, "text": "すごいな。"},
            ],
            transcriber=FailIfCalledTranscriber(),
            headline_generator=headline_generator,
        )
        self.assertEqual(summary.headlines, 1)
        self.assertIn("会上がった", headline_generator.kwargs["prepared_transcript"])
        self.assertIn("すごいな", headline_generator.kwargs["transcript"])
        self.assertNotIn("ww", enriched["items"][0]["headline"])
        self.assertEqual(enriched["items"][0]["headline_source"], "groq")

    def test_enrichment_falls_back_to_whisper_when_captions_miss_the_interval(self):
        video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "archive",
            "items": [{"id": "WGTrmrSvZH0_120_240", "start_sec": 120, "end_sec": 240}],
        }

        def media_fetcher(_url, _start, _end, output_dir):
            path = output_dir / "clip.webm"
            path.write_bytes(b"clip")
            return path

        transcriber_calls = []

        class FakeTranscriber:
            def transcribe(self, media_path, **_kwargs):
                transcriber_calls.append(media_path)
                return SimpleNamespace(
                    text="この気まずくなる流れ好きすぎるからやめて。",
                    source_text="この気まずくなる流れ好きすぎるからやめて。",
                    language="ja",
                    language_probability=0.9,
                    segments=None,
                )

        class FakeHeadlineGenerator:
            def generate(self, **_kwargs):
                return SimpleNamespace(
                    text="気まずくなる流れ好き",
                    source="groq",
                    model="openai/gpt-oss-120b",
                    generation_mode="llm_ranked",
                    confidence="high",
                    notes="",
                )

        enriched, summary = enrich_youtube_video(
            video,
            media_fetcher=media_fetcher,
            caption_cues=[{"start_sec": 300, "end_sec": 360, "text": "区間の外の字幕"}],
            transcriber=FakeTranscriber(),
            headline_generator=FakeHeadlineGenerator(),
        )
        self.assertEqual(len(transcriber_calls), 1)
        self.assertEqual(summary.transcribed, 1)
        self.assertEqual(summary.headlines, 1)
        self.assertIn("気まずくなる流れ", enriched["items"][0]["headline"])

    def test_enrichment_uses_publishable_extractive_headline_fallback(self):
        video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "archive",
            "items": [{"id": "WGTrmrSvZH0_120_240", "start_sec": 120, "end_sec": 240}],
        }

        def media_fetcher(_url, _start, _end, output_dir):
            path = output_dir / "clip.webm"
            path.write_bytes(b"clip")
            return path

        class FakeTranscriber:
            def transcribe(self, *_args, **_kwargs):
                return SimpleNamespace(
                    text="この気まずくなる流れ好きすぎるからやめて。",
                    source_text="この気まずくなる流れ好きすぎるからやめて。",
                    language="ja",
                    language_probability=0.9,
                    segments=None,
                )

        class ExtractiveFallbackGenerator:
            def generate(self, **_kwargs):
                return SimpleNamespace(
                    text="気まずくなる流れ好き",
                    source="extractive",
                    model="local-extractive",
                    generation_mode="fallback_extractive",
                    confidence="low",
                    notes="extractive_fallback",
                )

        enriched, summary = enrich_youtube_video(
            video,
            media_fetcher=media_fetcher,
            transcriber=FakeTranscriber(),
            headline_generator=ExtractiveFallbackGenerator(),
        )
        self.assertEqual(summary.headlines, 1)
        self.assertEqual(enriched["items"][0]["headline"], "気まずくなる流れ好き")
        self.assertEqual(enriched["items"][0]["headline_source"], "extractive")

    def test_enrichment_leaves_unpublishable_headline_missing_without_failing(self):
        video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "archive",
            "items": [
                {"id": "WGTrmrSvZH0_120_240", "start_sec": 120, "end_sec": 240},
                {"id": "WGTrmrSvZH0_300_360", "start_sec": 300, "end_sec": 360},
            ],
        }

        def media_fetcher(_url, _start, _end, output_dir):
            path = output_dir / "clip.webm"
            path.write_bytes(b"clip")
            return path

        class FakeTranscriber:
            def transcribe(self, *_args, **_kwargs):
                return SimpleNamespace(
                    text="どういうこと？そうだよね。",
                    source_text="どういうこと？そうだよね。",
                    language="ja",
                    language_probability=0.9,
                    segments=None,
                )

        class UnpublishableGenerator:
            def __init__(self):
                self.fallback = self

            def generate(self, **_kwargs):
                return SimpleNamespace(
                    text="どういうこと？」が連呼",
                    source="groq",
                    model="openai/gpt-oss-120b",
                    generation_mode="llm_ranked",
                    confidence="medium",
                    notes="",
                )

        enriched, summary = enrich_youtube_video(
            video,
            media_fetcher=media_fetcher,
            transcriber=FakeTranscriber(),
            headline_generator=UnpublishableGenerator(),
        )
        self.assertEqual(summary.attempted, 2)
        self.assertEqual(summary.headlines, 0)
        for item in enriched["items"]:
            self.assertNotIn("headline", item)
            self.assertEqual(item["headline_status"], "missing:not_publishable")

    def test_enrichment_refreshes_headline_runtime_from_environment(self):
        video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "archive",
            "items": [{"id": "WGTrmrSvZH0_120_240", "start_sec": 120, "end_sec": 240}],
        }

        def media_fetcher(_url, _start, _end, output_dir):
            path = output_dir / "clip.webm"
            path.write_bytes(b"clip")
            return path

        class FakeTranscriber:
            def transcribe(self, *_args, **_kwargs):
                return SimpleNamespace(
                    text="迷路を突破してバナナにたどり着く。",
                    source_text="迷路を突破してバナナにたどり着く。",
                    language="ja",
                    language_probability=0.9,
                    segments=None,
                )

        class FakeHeadlineGenerator:
            def generate(self, **_kwargs):
                return SimpleNamespace(
                    text="迷路を突破してバナナに到達",
                    source="groq",
                    model="openai/gpt-oss-120b",
                    generation_mode="llm_ranked",
                    confidence="high",
                    notes="",
                )

        captured = {}

        def fake_builder():
            import transcribe_segments as ts

            captured["api_key"] = ts.GROQ_API_KEY
            captured["model"] = ts.GROQ_MODEL
            return FakeHeadlineGenerator()

        with patch.dict(
            os.environ,
            {
                "GROQ_API_KEY": "x",
                "GROQ_MODEL": "openai/gpt-oss-120b",
                "GEMINI_API_KEY": "",
                "NVIDIA_API_KEY": "",
            },
            clear=False,
        ):
            with patch("transcribe_segments.build_headline_generator", side_effect=fake_builder):
                enriched, _summary = enrich_youtube_video(
                    video,
                    media_fetcher=media_fetcher,
                    transcriber=FakeTranscriber(),
                )

        self.assertEqual(captured["api_key"], "x")
        self.assertEqual(captured["model"], "openai/gpt-oss-120b")
        self.assertEqual(enriched["items"][0]["headline_source"], "groq")

    def test_oracle_workflow_uses_gpt_oss_120b_for_headlines(self):
        workflow = (ROOT / ".github" / "workflows" / "process-youtube-material.yml").read_text(encoding="utf-8")
        self.assertIn("GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}", workflow)
        self.assertIn("GROQ_MODEL: openai/gpt-oss-120b", workflow)


if __name__ == "__main__":
    unittest.main()
