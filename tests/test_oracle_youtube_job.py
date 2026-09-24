import json
import os
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

    def test_ytdlp_transient_failure_is_retried_until_success(self):
        responses = [
            SimpleNamespace(returncode=1, stdout="", stderr="ERROR: The page needs to be reloaded."),
            SimpleNamespace(returncode=0, stdout="ok"),
        ]

        def fake_run(_command, **_kwargs):
            return responses.pop(0)

        with patch.object(oracle_youtube_job.subprocess, "run", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            completed = oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(completed.stdout, "ok")
        self.assertEqual(sleep.call_count, 1)

    def test_ytdlp_permanent_failure_is_not_retried(self):
        def fake_run(_command, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Sign in to confirm your age")

        with patch.object(oracle_youtube_job.subprocess, "run", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            with self.assertRaises(oracle_youtube_job.OracleJobFailure) as caught:
                oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(caught.exception.category, "cookie_authentication_failure")
        self.assertEqual(sleep.call_count, 0)

    def test_ytdlp_transient_failure_raises_after_final_attempt(self):
        def fake_run(_command, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: The page needs to be reloaded.")

        with patch.object(oracle_youtube_job.subprocess, "run", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            with self.assertRaises(oracle_youtube_job.OracleJobFailure) as caught:
                oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(caught.exception.category, "yt_dlp_failure")
        self.assertEqual(sleep.call_count, oracle_youtube_job.YTDLP_TRANSIENT_RETRY_ATTEMPTS - 1)

    def test_chat_download_retries_when_no_artifact_was_written(self):
        calls = {"chat": 0}

        def fake_ytdlp(command, **_kwargs):
            if "--write-subs" in command:
                calls["chat"] += 1
                if calls["chat"] == 1:
                    raise oracle_youtube_job.OracleJobFailure("temporary_network_failure", "page reload required")
                output_path = Path(command[command.index("-o") + 1])
                output_path.with_name("archive.live_chat.json").write_text(
                    json.dumps({"videoOffsetTimeMsec": 1234}) + "\n",
                    encoding="utf-8",
                )
                return SimpleNamespace(stdout="")
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

        with tempfile.TemporaryDirectory() as raw_dir:
            with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp), patch.object(
                oracle_youtube_job.time, "sleep", return_value=None
            ) as sleep:
                _video, comments = oracle_youtube_job._download_chat_and_metadata(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    Path(raw_dir),
                    "/remote/yt-dlp",
                    "/remote/deno",
                    "/remote/youtube-cookies.txt",
                )

        self.assertEqual(calls["chat"], 2)
        self.assertEqual(comments, [{"content_offset_seconds": 1.234}])
        self.assertEqual(sleep.call_count, 1)

    def test_batch_continues_when_one_archive_fails(self):
        def fake_prepare(video_url, _work_dir, *_args, **_kwargs):
            video_id = oracle_youtube_job.parse_youtube_video_id(video_url)
            if video_id == "2a_ATYeOiAQ":
                raise oracle_youtube_job.OracleJobFailure("live_chat_zero", "no chat")
            return {
                "video_id": video_id,
                "manifest": {"vod_id": video_id},
                "media_files": {},
                "captions_file": None,
                "chat_total": 1,
                "highlights": 1,
                "media_bytes": 0,
            }

        with tempfile.TemporaryDirectory() as raw_dir:
            cookies_path = Path(raw_dir) / "youtube-cookies.txt"
            cookies_path.write_text("", encoding="utf-8")
            env = {
                "YOUTUBE_ORACLE_COOKIES_PATH": str(cookies_path),
                "YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL": "https://par.example/upload",
                "YOUTUBE_ORACLE_WORK_ROOT": str(raw_dir),
            }
            with patch.dict(os.environ, env), patch.object(
                oracle_youtube_job, "_prepare_material", side_effect=fake_prepare
            ), patch.object(
                oracle_youtube_job, "create_material_batch_bundle"
            ) as bundle, patch.object(
                oracle_youtube_job, "upload_bundle_to_url"
            ), patch.object(
                oracle_youtube_job, "_dispatch_github"
            ) as dispatch:
                results = oracle_youtube_job.run_batch(
                    [
                        "https://www.youtube.com/watch?v=aTCWAb8wRd8",
                        "https://www.youtube.com/watch?v=2a_ATYeOiAQ",
                        "https://www.youtube.com/watch?v=930HUhvRKHc",
                    ]
                )

        self.assertEqual([item["video_id"] for item in results], ["aTCWAb8wRd8", "930HUhvRKHc"])
        self.assertEqual(dispatch.call_args.args[0], ["aTCWAb8wRd8", "930HUhvRKHc"])
        bundle.assert_called_once()

    def test_batch_raises_when_every_archive_fails(self):
        def fake_prepare(_video_url, _work_dir, *_args, **_kwargs):
            raise oracle_youtube_job.OracleJobFailure("live_chat_zero", "no chat")

        with tempfile.TemporaryDirectory() as raw_dir:
            cookies_path = Path(raw_dir) / "youtube-cookies.txt"
            cookies_path.write_text("", encoding="utf-8")
            env = {
                "YOUTUBE_ORACLE_COOKIES_PATH": str(cookies_path),
                "YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL": "https://par.example/upload",
                "YOUTUBE_ORACLE_WORK_ROOT": str(raw_dir),
            }
            with patch.dict(os.environ, env), patch.object(
                oracle_youtube_job, "_prepare_material", side_effect=fake_prepare
            ), patch.object(
                oracle_youtube_job, "upload_bundle_to_url"
            ) as upload, patch.object(
                oracle_youtube_job, "_dispatch_github"
            ) as dispatch:
                with self.assertRaises(oracle_youtube_job.OracleJobFailure):
                    oracle_youtube_job.run_batch(
                        [
                            "https://www.youtube.com/watch?v=aTCWAb8wRd8",
                            "https://www.youtube.com/watch?v=2a_ATYeOiAQ",
                        ]
                    )

        upload.assert_not_called()
        dispatch.assert_not_called()

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
