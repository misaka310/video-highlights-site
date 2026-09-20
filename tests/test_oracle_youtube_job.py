import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import oracle_youtube_job  # noqa: E402


class OracleYoutubeJobTests(unittest.TestCase):
    def test_resolves_first_archive_from_streams_page(self):
        with patch.object(
            oracle_youtube_job,
            "_run_ytdlp",
            return_value=SimpleNamespace(stdout="2a_ATYeOiAQ\n"),
        ) as run_ytdlp:
            result = oracle_youtube_job._resolve_latest_stream_url(
                "https://www.youtube.com/@dotitube/streams",
                "/remote/yt-dlp",
                "/remote/deno",
                "/remote/youtube-cookies.txt",
            )

        self.assertEqual(result, "https://www.youtube.com/watch?v=2a_ATYeOiAQ")
        command = run_ytdlp.call_args.args[0]
        self.assertIn("--flat-playlist", command)
        self.assertIn("--playlist-end", command)
        self.assertEqual(command[-1], "https://www.youtube.com/@dotitube/streams")

    def test_resolves_multiple_archives_from_streams_page(self):
        with patch.object(
            oracle_youtube_job,
            "_run_ytdlp",
            return_value=SimpleNamespace(stdout="aTCWAb8wRd8\n2a_ATYeOiAQ\n930HUhvRKHc\n"),
        ) as run_ytdlp:
            result = oracle_youtube_job._resolve_stream_urls(
                "https://www.youtube.com/@dotitube/streams",
                "/remote/yt-dlp",
                "/remote/deno",
                "/remote/youtube-cookies.txt",
                limit=3,
            )

        self.assertEqual(
            result,
            [
                "https://www.youtube.com/watch?v=aTCWAb8wRd8",
                "https://www.youtube.com/watch?v=2a_ATYeOiAQ",
                "https://www.youtube.com/watch?v=930HUhvRKHc",
            ],
        )
        command = run_ytdlp.call_args.args[0]
        self.assertEqual(command[command.index("--playlist-end") + 1], "3")

    def test_reads_live_chat_artifact_created_by_successful_ytdlp(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work_dir = Path(raw_dir)

            def fake_ytdlp(command, **_kwargs):
                if "--write-subs" in command:
                    (work_dir / "archive.live_chat.json").write_text(
                        json.dumps({"videoOffsetTimeMsec": 1234}) + "\n",
                        encoding="utf-8",
                    )
                return SimpleNamespace(
                    stdout=json.dumps(
                        {
                            "id": "WGTrmrSvZH0",
                            "title": "Oracle archive",
                            "upload_date": "20260917",
                            "duration": 120,
                        }
                    )
                )

            with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp):
                _video, comments = oracle_youtube_job._download_chat_and_metadata(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    work_dir,
                    "/remote/yt-dlp",
                    "/remote/deno",
                    "/remote/youtube-cookies.txt",
                )

        self.assertEqual(comments, [{"content_offset_seconds": 1.234}])

    def test_keeps_live_chat_artifact_when_ytdlp_finishes_with_format_403(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work_dir = Path(raw_dir)

            def fake_ytdlp(command, **_kwargs):
                if "--write-subs" in command:
                    (work_dir / "archive.live_chat.json").write_text(
                        json.dumps({"videoOffsetTimeMsec": 1234}) + "\n",
                        encoding="utf-8",
                    )
                    raise oracle_youtube_job.OracleJobFailure("yt_dlp_failure", "format probe returned 403")
                return SimpleNamespace(
                    stdout=json.dumps(
                        {
                            "id": "WGTrmrSvZH0",
                            "title": "Oracle archive",
                            "upload_date": "20260917",
                            "duration": 120,
                            "thumbnail": "https://i.ytimg.com/vi/WGTrmrSvZH0/hqdefault.jpg",
                        }
                    )
                )

            with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp):
                video, comments = oracle_youtube_job._download_chat_and_metadata(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    work_dir,
                    "/remote/yt-dlp",
                    "/remote/deno",
                    "/remote/youtube-cookies.txt",
                )

        self.assertEqual(video["vod_id"], "WGTrmrSvZH0")
        self.assertEqual(comments, [{"content_offset_seconds": 1.234}])


    def test_downloads_public_youtube_captions_as_optional_json(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work_dir = Path(raw_dir)

            def fake_ytdlp(command, **_kwargs):
                if "--write-subs" in command:
                    (work_dir / "captions.ja.json3").write_text(
                        json.dumps(
                            {
                                "events": [
                                    {
                                        "tStartMs": 1000,
                                        "dDurationMs": 2000,
                                        "segs": [{"utf8": "テスト字幕"}],
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                return SimpleNamespace(stdout="")

            with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp):
                captions_path = oracle_youtube_job._download_captions(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    work_dir,
                    "/remote/yt-dlp",
                    "/remote/deno",
                    "/remote/youtube-cookies.txt",
                )

            self.assertIsNotNone(captions_path)
            payload = json.loads(Path(captions_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], "youtube_manual_captions")
            self.assertEqual(payload["cues"][0]["text"], "テスト字幕")

    def test_missing_public_captions_is_non_fatal(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work_dir = Path(raw_dir)
            with patch.object(oracle_youtube_job, "_run_ytdlp", return_value=SimpleNamespace(stdout="")):
                captions_path = oracle_youtube_job._download_captions(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    work_dir,
                    "/remote/yt-dlp",
                    "/remote/deno",
                    "/remote/youtube-cookies.txt",
                )
        self.assertIsNone(captions_path)


if __name__ == "__main__":
    unittest.main()
