import datetime as dt
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import oracle_youtube_job  # noqa: E402


class OracleYoutubeJobTests(unittest.TestCase):
    def assert_process_stopped(self, process_id):
        for _ in range(40):
            try:
                os.kill(process_id, 0)
            except ProcessLookupError:
                return
            stat_path = Path(f"/proc/{process_id}/stat")
            if stat_path.exists() and stat_path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] == "Z":
                return
            time.sleep(0.05)
        self.fail(f"child process {process_id} remained running")

    @unittest.skipUnless(os.name == "posix", "POSIX process groups are used on Oracle")
    def test_cleans_up_child_processes_after_command_exits(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            child_pid_path = Path(raw_dir) / "child.pid"
            parent_code = (
                "import subprocess, sys, time; "
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)']); "
                f"open({str(child_pid_path)!r}, 'w').write(str(child.pid)); "
                "time.sleep(0.1)"
            )

            with patch.object(oracle_youtube_job, "PROCESS_GROUP_TERMINATION_GRACE_SECONDS", 0.2):
                completed = oracle_youtube_job._run_captured([sys.executable, "-c", parent_code], timeout=5)

            self.assertEqual(completed.returncode, 0)
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            self.assert_process_stopped(child_pid)

    @unittest.skipUnless(os.name == "posix", "POSIX process groups are used on Oracle")
    def test_timeout_stops_child_processes_before_raising(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            child_pid_path = Path(raw_dir) / "child.pid"
            child_code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
            parent_code = (
                "import subprocess, sys, time; "
                f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
                f"open({str(child_pid_path)!r}, 'w').write(str(child.pid)); "
                "time.sleep(60)"
            )

            with patch.object(oracle_youtube_job, "PROCESS_GROUP_TERMINATION_GRACE_SECONDS", 0.2):
                with self.assertRaises(oracle_youtube_job.subprocess.TimeoutExpired):
                    oracle_youtube_job._run_captured([sys.executable, "-c", parent_code], timeout=0.1)

            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            self.assert_process_stopped(child_pid)

    def test_selects_newest_unpublished_public_window_archives_before_capping(self):
        now = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
        records = [
            {"id": "aTCWAb8wRd8", "upload_date": "20260929"},
            {"id": "2a_ATYeOiAQ", "upload_date": "20260928"},
            {"id": "930HUhvRKHc", "upload_date": "20260927"},
            {"id": "WGTrmrSvZH0", "upload_date": "20260926"},
            {"id": "AI5K5VH3BhY", "upload_date": "20260925"},
            {"id": "d41zBjWSGcc", "upload_date": "20260801"},
            {"id": "KwRhwLUZjko", "upload_date": "20260731"},
            {"id": "3V0swWyny-8", "upload_date": "unknown"},
        ]

        selected = oracle_youtube_job._select_unpublished_stream_urls(
            records,
            published_ids={"2a_ATYeOiAQ"},
            limit=3,
            now=now,
        )

        self.assertEqual(
            selected,
            [
                "https://www.youtube.com/watch?v=aTCWAb8wRd8",
                "https://www.youtube.com/watch?v=930HUhvRKHc",
                "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            ],
        )

    def test_uses_timestamps_to_order_same_day_archives_newest_first(self):
        now = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
        records = [
            {
                "id": "aTCWAb8wRd8",
                "upload_date": "20260929",
                "timestamp": str(dt.datetime(2026, 9, 29, 18, tzinfo=dt.timezone.utc).timestamp()),
            },
            {
                "id": "2a_ATYeOiAQ",
                "upload_date": "20260929",
                "timestamp": str(dt.datetime(2026, 9, 29, 8, tzinfo=dt.timezone.utc).timestamp()),
            },
        ]

        selected = oracle_youtube_job._select_unpublished_stream_urls(
            records,
            published_ids=set(),
            limit=5,
            now=now,
        )

        self.assertEqual(
            selected,
            [
                "https://www.youtube.com/watch?v=aTCWAb8wRd8",
                "https://www.youtube.com/watch?v=2a_ATYeOiAQ",
            ],
        )

    def test_merges_recent_cached_archives_when_streams_listing_omits_them(self):
        now = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
        merged = oracle_youtube_job._merge_discovered_stream_records(
            current_records=[
                {"id": "2a_ATYeOiAQ", "upload_date": "20260929"},
                {"id": "fHXrGwQAn-A", "upload_date": "20260930"},
            ],
            cached_records=[
                {"id": "fHXrGwQAn-A", "upload_date": "20260930", "timestamp": "1790722800"},
                {"id": "aTCWAb8wRd8", "upload_date": "20260928"},
                {"id": "d41zBjWSGcc", "upload_date": "20260701"},
                {"id": "bad-id", "upload_date": "20260930"},
            ],
            published_ids={"aTCWAb8wRd8"},
            now=now,
        )

        self.assertEqual(
            merged,
            [
                {"id": "fHXrGwQAn-A", "upload_date": "20260930", "timestamp": "1790722800"},
                {"id": "2a_ATYeOiAQ", "upload_date": "20260929", "timestamp": ""},
            ],
        )

    def test_main_retries_cached_candidate_omitted_from_streams_listing(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            cookie_path = Path(raw_dir) / "youtube-cookies.txt"
            cookie_path.write_text("", encoding="utf-8")
            state = {
                "processed_video_ids": [],
                "discovered_stream_records": [
                    {"id": "fHXrGwQAn-A", "upload_date": "20260930", "timestamp": "1790722800"}
                ],
            }
            output = StringIO()
            expected_urls = [
                "https://www.youtube.com/watch?v=fHXrGwQAn-A",
                "https://www.youtube.com/watch?v=2a_ATYeOiAQ",
            ]
            with patch.dict(
                os.environ,
                {
                    "YOUTUBE_ORACLE_STREAMS_URL": "https://www.youtube.com/@dotitube/streams",
                    "YOUTUBE_ORACLE_COOKIES_PATH": str(cookie_path),
                },
                clear=True,
            ), patch.object(sys, "argv", ["oracle_youtube_job"]), patch.object(
                oracle_youtube_job,
                "_utc_now",
                return_value=dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc),
            ), patch.object(
                oracle_youtube_job,
                "_resolve_stream_archive_records",
                return_value=[{"id": "2a_ATYeOiAQ", "upload_date": "20260929"}],
            ), patch.object(
                oracle_youtube_job, "_read_published_video_ids", return_value=set()
            ), patch.object(
                oracle_youtube_job, "_read_state", return_value=state
            ), patch.object(
                oracle_youtube_job, "_write_state"
            ) as write_state, patch.object(
                oracle_youtube_job, "run_batch", return_value=[]
            ) as run_batch, patch.object(
                oracle_youtube_job, "_notify"
            ), redirect_stdout(output):
                exit_code = oracle_youtube_job.main()

        self.assertEqual(exit_code, 0)
        run_batch.assert_called_once_with(expected_urls)
        write_state.assert_called_once()
        self.assertEqual(
            state["discovered_stream_records"],
            [
                {"id": "fHXrGwQAn-A", "upload_date": "20260930", "timestamp": "1790722800"},
                {"id": "2a_ATYeOiAQ", "upload_date": "20260929", "timestamp": ""},
            ],
        )

    def test_main_selects_newest_unpublished_before_limiting_to_five(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            cookie_path = Path(raw_dir) / "youtube-cookies.txt"
            cookie_path.write_text("", encoding="utf-8")
            output = StringIO()
            records = [
                {"id": "aTCWAb8wRd8", "upload_date": "20260929"},
                {"id": "2a_ATYeOiAQ", "upload_date": "20260928"},
                {"id": "930HUhvRKHc", "upload_date": "20260927"},
                {"id": "WGTrmrSvZH0", "upload_date": "20260926"},
                {"id": "AI5K5VH3BhY", "upload_date": "20260925"},
                {"id": "d41zBjWSGcc", "upload_date": "20260924"},
                {"id": "KwRhwLUZjko", "upload_date": "20260923"},
                {"id": "Oldest00001", "upload_date": "20260922"},
                {"id": "Oldest00002", "upload_date": "20260921"},
            ]
            expected_urls = [
                "https://www.youtube.com/watch?v=aTCWAb8wRd8",
                "https://www.youtube.com/watch?v=930HUhvRKHc",
                "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                "https://www.youtube.com/watch?v=AI5K5VH3BhY",
                "https://www.youtube.com/watch?v=d41zBjWSGcc",
            ]
            with patch.dict(
                os.environ,
                {
                    "YOUTUBE_ORACLE_STREAMS_URL": "https://www.youtube.com/@dotitube/streams",
                    "YOUTUBE_ORACLE_COOKIES_PATH": str(cookie_path),
                    "YOUTUBE_ORACLE_MAX_VIDEOS": "99",
                },
                clear=True,
            ), patch.object(sys, "argv", ["oracle_youtube_job"]), patch.object(
                oracle_youtube_job,
                "_utc_now",
                return_value=dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc),
            ), patch.object(
                oracle_youtube_job, "_resolve_stream_archive_records", return_value=records
            ), patch.object(
                oracle_youtube_job, "_read_published_video_ids", return_value={"2a_ATYeOiAQ"}
            ), patch.object(
                oracle_youtube_job, "_read_state", return_value={"processed_video_ids": ["aTCWAb8wRd8"]}
            ), patch.object(
                oracle_youtube_job, "_write_state"
            ), patch.object(
                oracle_youtube_job, "run_batch", return_value=[]
            ) as run_batch, patch.object(
                oracle_youtube_job, "_notify"
            ), redirect_stdout(output):
                exit_code = oracle_youtube_job.main()

        self.assertEqual(exit_code, 0)
        run_batch.assert_called_once_with(expected_urls)

    def test_processed_state_keeps_all_ids_instead_of_truncating_history(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            state_path = Path(raw_dir) / "state.json"
            initial_ids = [f"processed-{index}" for index in range(35)]
            state_path.write_text(json.dumps({"processed_video_ids": initial_ids}), encoding="utf-8")
            with patch.dict(os.environ, {"YOUTUBE_ORACLE_STATE_PATH": str(state_path)}):
                oracle_youtube_job._mark_processed("new-video")

            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(state["processed_video_ids"], initial_ids + ["new-video"])

    def test_main_wraps_single_run_result_before_marking_processed(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            cookie_path = Path(raw_dir) / "youtube-cookies.txt"
            cookie_path.write_text("", encoding="utf-8")
            result = {
                "video_id": "AI5K5VH3BhY",
                "chat_total": 10,
                "highlights": 3,
                "captions": True,
                "media_bytes": 100,
            }
            output = StringIO()
            with patch.dict(
                os.environ,
                {
                    "YOUTUBE_ORACLE_VIDEO_URL": "https://www.youtube.com/watch?v=AI5K5VH3BhY",
                    "YOUTUBE_ORACLE_COOKIES_PATH": str(cookie_path),
                },
                clear=True,
            ), patch.object(sys, "argv", ["oracle_youtube_job"]), patch.object(
                oracle_youtube_job, "run", return_value=result
            ), patch.object(
                oracle_youtube_job, "_mark_processed"
            ) as mark_processed, patch.object(
                oracle_youtube_job, "_notify"
            ) as notify, redirect_stdout(output):
                exit_code = oracle_youtube_job.main()

        self.assertEqual(exit_code, 0)
        mark_processed.assert_called_once_with("AI5K5VH3BhY")
        notify.assert_called_once_with(None)
        self.assertIn("oracle YouTube job complete: videos=1", output.getvalue())

    def test_resolves_first_archive_from_streams_page(self):
        with patch.object(
            oracle_youtube_job,
            "_run_ytdlp",
            return_value=SimpleNamespace(
                stdout=json.dumps(
                    {
                        "id": "2a_ATYeOiAQ",
                        "upload_date": "20260917",
                        "timestamp": 1789603200,
                    }
                )
                + "\n"
            ),
        ) as run_ytdlp:
            result = oracle_youtube_job._resolve_stream_archive_records(
                "https://www.youtube.com/@dotitube/streams",
                "/remote/yt-dlp",
                "/remote/deno",
                "/remote/youtube-cookies.txt",
                now=dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc),
            )

        self.assertEqual(
            result,
            [{"id": "2a_ATYeOiAQ", "upload_date": "20260917", "timestamp": "1789603200"}],
        )
        command = run_ytdlp.call_args.args[0]
        self.assertIn("--flat-playlist", command)
        self.assertIn("--dateafter", command)
        self.assertIn("youtubetab:approximate_date", command)
        self.assertEqual(command[command.index("--print") + 1], "%(.{id,upload_date,timestamp})j")
        self.assertEqual(command[command.index("--dateafter") + 1], "20260730")
        self.assertEqual(command[-1], "https://www.youtube.com/@dotitube/streams")

    def test_resolves_multiple_archives_from_streams_page(self):
        with patch.object(
            oracle_youtube_job,
            "_run_ytdlp",
            return_value=SimpleNamespace(
                stdout="\n".join(
                    json.dumps({"id": video_id, "upload_date": upload_date})
                    for video_id, upload_date in (
                        ("aTCWAb8wRd8", "20260918"),
                        ("2a_ATYeOiAQ", "20260917"),
                        ("930HUhvRKHc", "20260916"),
                    )
                )
            ),
        ) as run_ytdlp:
            result = oracle_youtube_job._resolve_stream_archive_records(
                "https://www.youtube.com/@dotitube/streams",
                "/remote/yt-dlp",
                "/remote/deno",
                "/remote/youtube-cookies.txt",
            )

        self.assertEqual(
            result,
            [
                {"id": "aTCWAb8wRd8", "upload_date": "20260918", "timestamp": ""},
                {"id": "2a_ATYeOiAQ", "upload_date": "20260917", "timestamp": ""},
                {"id": "930HUhvRKHc", "upload_date": "20260916", "timestamp": ""},
            ],
        )
        self.assertNotIn("--playlist-end", run_ytdlp.call_args.args[0])

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

        with patch.object(oracle_youtube_job, "_run_captured", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            completed = oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(completed.stdout, "ok")
        self.assertEqual(sleep.call_count, 1)

    def test_ytdlp_permanent_failure_is_not_retried(self):
        def fake_run(_command, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: Sign in to confirm your age")

        with patch.object(oracle_youtube_job, "_run_captured", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            with self.assertRaises(oracle_youtube_job.OracleJobFailure) as caught:
                oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(caught.exception.category, "cookie_authentication_failure")
        self.assertEqual(sleep.call_count, 0)

    def test_ytdlp_transient_failure_raises_after_final_attempt(self):
        def fake_run(_command, **_kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: The page needs to be reloaded.")

        with patch.object(oracle_youtube_job, "_run_captured", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            with self.assertRaises(oracle_youtube_job.OracleJobFailure) as caught:
                oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(caught.exception.category, "yt_dlp_failure")
        self.assertEqual(sleep.call_count, oracle_youtube_job.YTDLP_TRANSIENT_RETRY_ATTEMPTS - 1)

    def test_ytdlp_timeout_is_retried_then_succeeds(self):
        def fake_run(_command, **_kwargs):
            if fake_run.calls == 0:
                fake_run.calls += 1
                raise oracle_youtube_job.subprocess.TimeoutExpired(cmd="yt-dlp", timeout=10)
            return SimpleNamespace(returncode=0, stdout="ok")

        fake_run.calls = 0

        with patch.object(oracle_youtube_job, "_run_captured", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            completed = oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(completed.stdout, "ok")
        self.assertEqual(sleep.call_count, 1)

    def test_ytdlp_members_only_failure_is_not_retried(self):
        def fake_run(_command, **_kwargs):
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="ERROR: [youtube] abc: Join this channel to get access to members-only content",
            )

        with patch.object(oracle_youtube_job, "_run_captured", side_effect=fake_run), patch.object(
            oracle_youtube_job.time, "sleep", return_value=None
        ) as sleep:
            with self.assertRaises(oracle_youtube_job.OracleJobFailure) as caught:
                oracle_youtube_job._run_ytdlp(["yt-dlp"], timeout=10)

        self.assertEqual(caught.exception.category, "youtube_access_failure")
        self.assertEqual(sleep.call_count, 0)

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
