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

    def test_selects_recent_archives_when_upload_date_is_missing_but_timestamp_exists(self):
        now = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
        records = [
            {
                "id": "aTCWAb8wRd8",
                "upload_date": "",
                "timestamp": str(dt.datetime(2026, 9, 29, 18, tzinfo=dt.timezone.utc).timestamp()),
            },
            {
                "id": "2a_ATYeOiAQ",
                "upload_date": "unknown",
                "timestamp": str(dt.datetime(2026, 7, 1, 18, tzinfo=dt.timezone.utc).timestamp()),
            },
        ]

        selected = oracle_youtube_job._select_unpublished_stream_urls(
            records,
            published_ids=set(),
            limit=5,
            now=now,
        )

        self.assertEqual(selected, ["https://www.youtube.com/watch?v=aTCWAb8wRd8"])

    def test_merges_recent_archive_with_timestamp_when_upload_date_is_missing(self):
        now = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
        merged = oracle_youtube_job._merge_discovered_stream_records(
            current_records=[
                {
                    "id": "aTCWAb8wRd8",
                    "upload_date": "",
                    "timestamp": str(dt.datetime(2026, 9, 29, 18, tzinfo=dt.timezone.utc).timestamp()),
                }
            ],
            cached_records=[],
            published_ids=set(),
            now=now,
        )

        self.assertEqual(
            merged,
            [
                {
                    "id": "aTCWAb8wRd8",
                    "upload_date": "20260929",
                    "timestamp": str(dt.datetime(2026, 9, 29, 18, tzinfo=dt.timezone.utc).timestamp()),
                }
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

    def test_main_skips_direct_video_url_when_already_published(self):
        video_id = "ndKhBP5HXvc"
        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            sys,
            "argv",
            [
                "oracle_youtube_job",
                "--streams-url",
                "",
                "--video-url",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
        ), patch.object(
            oracle_youtube_job, "_read_published_video_ids", return_value={video_id}
        ) as read_published_ids, patch.object(
            oracle_youtube_job, "_read_caption_ids", return_value={video_id}
        ), patch.object(
            oracle_youtube_job, "run"
        ) as run, patch.object(
            oracle_youtube_job, "_notify"
        ) as notify, redirect_stdout(output):
            exit_code = oracle_youtube_job.main()

        self.assertEqual(exit_code, 0)
        read_published_ids.assert_called_once_with()
        run.assert_not_called()
        notify.assert_called_once_with(None)
        self.assertIn(f"selected video_id={video_id}", output.getvalue())
        self.assertIn(f"skipped video_id={video_id} category=already_published", output.getvalue())

    def test_main_refreshes_only_captions_for_published_direct_video_without_captions(self):
        video_id = "ndKhBP5HXvc"
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            sys, "argv", ["oracle_youtube_job", "--streams-url", "", "--video-url", video_url]
        ), patch.object(
            oracle_youtube_job, "_read_published_video_ids", return_value={video_id}
        ), patch.object(
            oracle_youtube_job, "_read_caption_ids", return_value=set()
        ), patch.object(
            oracle_youtube_job, "run"
        ) as run, patch.object(
            oracle_youtube_job, "run_batch", return_value=[]
        ) as run_batch, patch.object(
            oracle_youtube_job, "_notify"
        ), redirect_stdout(output):
            exit_code = oracle_youtube_job.main()

        self.assertEqual(exit_code, 0)
        run.assert_not_called()
        run_batch.assert_called_once_with([], caption_retry_urls=[video_url])
        self.assertIn(f"selected caption_retry video_id={video_id}", output.getvalue())
        self.assertNotIn("already_published", output.getvalue())

    def test_main_dispatches_due_caption_retry_without_new_archives(self):
        video_id = "ndKhBP5HXvc"
        caption_url = f"https://www.youtube.com/watch?v={video_id}"
        with tempfile.TemporaryDirectory() as raw_dir:
            cookie_path = Path(raw_dir) / "youtube-cookies.txt"
            cookie_path.write_text("", encoding="utf-8")
            state = {
                "caption_retry_migration_version": 1,
                "caption_retry_records": [
                    {
                        "video_id": video_id,
                        "first_attempt_at": "2026-10-04T09:55:37Z",
                        "first_attempt_date": "2026-10-04",
                        "attempts": 1,
                        "last_reason_code": "caption_track_not_found",
                        "awaiting_publication": False,
                    }
                ],
            }
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
                return_value=dt.datetime(2026, 10, 5, 10, 0, tzinfo=dt.timezone.utc),
            ), patch.object(
                oracle_youtube_job, "_resolve_stream_archive_records", return_value=[]
            ), patch.object(
                oracle_youtube_job, "_read_published_video_ids", return_value={video_id}
            ), patch.object(
                oracle_youtube_job, "_read_caption_ids", return_value=set()
            ), patch.object(
                oracle_youtube_job, "_read_state", return_value=state
            ), patch.object(
                oracle_youtube_job, "_write_state"
            ), patch.object(
                oracle_youtube_job, "run_batch", return_value=[]
            ) as run_batch, patch.object(
                oracle_youtube_job, "_notify"
            ), redirect_stdout(StringIO()):
                exit_code = oracle_youtube_job.main()

        self.assertEqual(exit_code, 0)
        run_batch.assert_called_once_with([], caption_retry_urls=[caption_url])

    def test_caption_retry_is_due_after_24_and_72_hours(self):
        record = {
            "first_attempt_at": "2026-10-04T09:55:37Z",
            "first_attempt_date": "2026-10-04",
            "attempts": 1,
            "awaiting_publication": False,
        }
        before_next_day = dt.datetime(2026, 10, 5, 9, 55, 36, tzinfo=dt.timezone.utc)
        next_jst_day = dt.datetime(2026, 10, 5, 9, 55, 37, tzinfo=dt.timezone.utc)
        third_jst_day = dt.datetime(2026, 10, 7, 9, 55, 37, tzinfo=dt.timezone.utc)

        self.assertFalse(oracle_youtube_job._caption_retry_due(record, before_next_day))
        self.assertTrue(oracle_youtube_job._caption_retry_due(record, next_jst_day))
        record["attempts"] = 2
        self.assertFalse(oracle_youtube_job._caption_retry_due(record, dt.datetime(2026, 10, 6, 9, 55, 36, tzinfo=dt.timezone.utc)))
        self.assertTrue(oracle_youtube_job._caption_retry_due(record, third_jst_day))

    def test_migration_seeds_recent_published_vod_with_unknown_caption_attempt(self):
        video_id = "ndKhBP5HXvc"
        first_attempt = dt.datetime(2026, 10, 4, 18, 55, 37, tzinfo=oracle_youtube_job.JST)
        now = first_attempt.astimezone(dt.timezone.utc) + dt.timedelta(days=1)
        with tempfile.TemporaryDirectory() as raw_dir:
            repo_root = Path(raw_dir)
            data_dir = repo_root / "data"
            data_dir.mkdir()
            (data_dir / "processed_vods.json").write_text(
                json.dumps({"videos": [{"vod_id": video_id, "analyzed_at": first_attempt.isoformat()}]}),
                encoding="utf-8",
            )
            state = {}
            with patch.object(oracle_youtube_job, "REPOSITORY_ROOT", repo_root):
                oracle_youtube_job._seed_caption_retry_records(
                    state,
                    published_ids={video_id},
                    caption_ids=set(),
                    now=now,
                )

        record = state["caption_retry_records"][0]
        self.assertEqual(state["caption_retry_migration_version"], 1)
        self.assertEqual(record["last_reason_code"], "legacy_initial_state_unknown")
        self.assertEqual(record["attempt_history"][0]["outcome"], "unknown")
        self.assertTrue(oracle_youtube_job._caption_retry_due(record, now))

    def test_final_caption_retry_miss_is_recorded_as_abandoned(self):
        video_id = "ndKhBP5HXvc"
        record = {
            "video_id": video_id,
            "first_attempt_at": "2026-10-04T09:55:37Z",
            "first_attempt_date": "2026-10-04",
            "attempts": 2,
            "last_reason_code": "caption_download_error",
            "awaiting_publication": False,
        }
        now = dt.datetime(2026, 10, 7, 9, 55, 37, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as raw_dir:
            state_path = Path(raw_dir) / "state.json"
            state_path.write_text(json.dumps({"caption_retry_records": [record]}), encoding="utf-8")
            with patch.dict(os.environ, {"YOUTUBE_ORACLE_STATE_PATH": str(state_path)}):
                result = oracle_youtube_job._record_caption_retry_failure(
                    video_id,
                    "caption_track_not_found",
                    now=now,
                )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(result, "abandoned")
        self.assertEqual(state["caption_retry_records"], [])
        self.assertEqual(state["caption_retry_history"][-1]["attempts"], 3)
        self.assertEqual(state["caption_retry_history"][-1]["outcome"], "abandoned")

    def test_caption_retry_batch_dispatches_caption_only_bundle(self):
        video_id = "ndKhBP5HXvc"
        caption_path = Path("/tmp/retry-captions.json")
        record = {
            "video_id": video_id,
            "first_attempt_at": "2026-10-04T09:55:37Z",
            "first_attempt_date": "2026-10-04",
            "last_attempt_at": "2026-10-04T09:55:37Z",
            "attempts": 1,
            "last_reason_code": "caption_track_not_found",
            "awaiting_publication": False,
        }
        with tempfile.TemporaryDirectory() as raw_dir:
            cookies_path = Path(raw_dir) / "youtube-cookies.txt"
            cookies_path.write_text("", encoding="utf-8")
            state_path = Path(raw_dir) / "state.json"
            state_path.write_text(json.dumps({"caption_retry_records": [record]}), encoding="utf-8")
            env = {
                "YOUTUBE_ORACLE_COOKIES_PATH": str(cookies_path),
                "YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL": "https://par.example/upload",
                "YOUTUBE_ORACLE_WORK_ROOT": str(raw_dir),
                "YOUTUBE_ORACLE_STATE_PATH": str(state_path),
            }
            with patch.dict(os.environ, env), patch.object(
                oracle_youtube_job,
                "_download_captions",
                return_value={
                    "path": caption_path,
                    "reason_code": None,
                    "source_outcomes": {"manual": "available", "automatic": "not_attempted"},
                },
            ), patch.object(
                oracle_youtube_job, "create_material_batch_bundle"
            ) as bundle, patch.object(
                oracle_youtube_job, "upload_bundle_to_url"
            ), patch.object(
                oracle_youtube_job, "_dispatch_github"
            ) as dispatch:
                results = oracle_youtube_job.run_batch(
                    [], caption_retry_urls=[f"https://www.youtube.com/watch?v={video_id}"]
                )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(results, [])
        self.assertEqual(bundle.call_args.kwargs["caption_updates"], [(video_id, caption_path)])
        dispatch.assert_called_once_with([video_id])
        self.assertTrue(state["caption_retry_records"][0]["awaiting_publication"])
        self.assertEqual(state["caption_retry_records"][0]["attempts"], 2)
        self.assertEqual(state["caption_retry_records"][0]["attempt_history"][-1]["outcome"], "caption_available")
        self.assertFalse(
            oracle_youtube_job._caption_retry_due(
                state["caption_retry_records"][0],
                dt.datetime(2026, 10, 8, tzinfo=dt.timezone.utc),
            )
        )

    def test_caption_retry_miss_records_reason_and_schedules_third_day(self):
        video_id = "ndKhBP5HXvc"
        record = {
            "video_id": video_id,
            "first_attempt_at": "2026-10-04T09:55:37Z",
            "first_attempt_date": "2026-10-04",
            "attempts": 1,
            "last_reason_code": "caption_track_not_found",
            "awaiting_publication": False,
        }
        with tempfile.TemporaryDirectory() as raw_dir:
            cookies_path = Path(raw_dir) / "youtube-cookies.txt"
            cookies_path.write_text("", encoding="utf-8")
            state_path = Path(raw_dir) / "state.json"
            state_path.write_text(json.dumps({"caption_retry_records": [record]}), encoding="utf-8")
            env = {
                "YOUTUBE_ORACLE_COOKIES_PATH": str(cookies_path),
                "YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL": "https://par.example/upload",
                "YOUTUBE_ORACLE_WORK_ROOT": str(raw_dir),
                "YOUTUBE_ORACLE_STATE_PATH": str(state_path),
            }
            with patch.dict(os.environ, env), patch.object(
                oracle_youtube_job,
                "_download_captions",
                return_value={
                    "path": None,
                    "reason_code": "caption_download_error",
                    "source_outcomes": {"manual": "download_error", "automatic": "download_error"},
                },
            ), patch.object(
                oracle_youtube_job, "create_material_batch_bundle"
            ) as bundle, patch.object(
                oracle_youtube_job, "_dispatch_github"
            ) as dispatch:
                results = oracle_youtube_job.run_batch(
                    [], caption_retry_urls=[f"https://www.youtube.com/watch?v={video_id}"]
                )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(results, [])
        self.assertEqual(state["caption_retry_records"][0]["attempts"], 2)
        self.assertEqual(state["caption_retry_records"][0]["last_reason_code"], "caption_download_error")
        self.assertEqual(
            state["caption_retry_records"][0]["last_source_outcomes"],
            {"manual": "download_error", "automatic": "download_error"},
        )
        bundle.assert_not_called()
        dispatch.assert_not_called()

    def test_initial_caption_miss_records_safe_reason_and_source_outcomes(self):
        video_id = "ndKhBP5HXvc"
        with tempfile.TemporaryDirectory() as raw_dir:
            state_path = Path(raw_dir) / "state.json"
            with patch.dict(os.environ, {"YOUTUBE_ORACLE_STATE_PATH": str(state_path)}):
                oracle_youtube_job._mark_processed(
                    video_id,
                    captions_found=False,
                    caption_reason_code="caption_download_error",
                    caption_source_outcomes={"manual": "download_error", "automatic": "track_not_found"},
                    now=dt.datetime(2026, 10, 4, 9, 55, 37, tzinfo=dt.timezone.utc),
                )
            state = json.loads(state_path.read_text(encoding="utf-8"))

        record = state["caption_retry_records"][0]
        self.assertEqual(record["attempts"], 1)
        self.assertEqual(record["last_reason_code"], "caption_download_error")
        self.assertEqual(
            record["last_source_outcomes"],
            {"manual": "download_error", "automatic": "track_not_found"},
        )
        self.assertEqual(record["attempt_history"][0]["attempt"], 1)
        self.assertEqual(record["attempt_history"][0]["reason_code"], "caption_download_error")

    def test_processed_state_keeps_all_ids_instead_of_truncating_history(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            state_path = Path(raw_dir) / "state.json"
            initial_ids = [f"processed-{index}" for index in range(35)]
            state_path.write_text(json.dumps({"processed_video_ids": initial_ids}), encoding="utf-8")
            with patch.dict(os.environ, {"YOUTUBE_ORACLE_STATE_PATH": str(state_path)}):
                oracle_youtube_job._mark_processed("new-video")

            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(state["processed_video_ids"], initial_ids + ["new-video"])

    def test_failure_reason_code_is_required_and_validated(self):
        with self.assertRaises(TypeError):
            oracle_youtube_job.OracleJobFailure("live_chat_zero", "missing reason")
        with self.assertRaises(ValueError):
            oracle_youtube_job.OracleJobFailure(
                "live_chat_zero",
                "unsafe reason",
                reason_code="not a safe reason",
            )

    def test_failure_state_retains_only_bounded_safe_diagnostics(self):
        video_id = "ndKhBP5HXvc"
        now = dt.datetime(2026, 10, 2, 6, 59, tzinfo=dt.timezone.utc)
        with tempfile.TemporaryDirectory() as raw_dir:
            state_path = Path(raw_dir) / "state.json"
            expired_failure = {
                "video_id": "aTCWAb8wRd8",
                "failed_at": "2026-07-01T00:00:00Z",
                "category": "yt_dlp_failure",
                "stage": "media_cut",
                "reason_code": "media_section_not_created",
            }
            recent_failures = [
                {
                    "video_id": "fHXrGwQAn-A",
                    "failed_at": "2026-10-01T06:59:00Z",
                    "category": "yt_dlp_failure",
                    "stage": "media_cut",
                    "reason_code": "media_section_not_created",
                }
                for _ in range(oracle_youtube_job.MAX_FAILURE_RECORDS)
            ]
            state_path.write_text(
                json.dumps({"failure_records": [expired_failure, *recent_failures]}),
                encoding="utf-8",
            )
            failure = oracle_youtube_job.OracleJobFailure(
                "yt_dlp_failure",
                "private stderr and URL must not be retained: https://example.invalid/token=secret",
                stage="media_cut",
                reason_code="media_section_not_created",
            )
            with patch.dict(os.environ, {"YOUTUBE_ORACLE_STATE_PATH": str(state_path)}):
                oracle_youtube_job._record_failure(video_id, failure, now=now)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            serialized_state = state_path.read_text(encoding="utf-8")

        self.assertEqual(len(state["failure_records"]), oracle_youtube_job.MAX_FAILURE_RECORDS)
        self.assertEqual(
            state["failure_records"][-1],
            {
                "video_id": video_id,
                "failed_at": "2026-10-02T06:59:00Z",
                "category": "yt_dlp_failure",
                "stage": "media_cut",
                "reason_code": "media_section_not_created",
            },
        )
        self.assertNotIn("aTCWAb8wRd8", [record["video_id"] for record in state["failure_records"]])
        self.assertNotIn("private stderr", serialized_state)

    def test_run_persists_failure_reason_without_marking_video_processed(self):
        video_id = "ndKhBP5HXvc"
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            cookies_path = root / "youtube-cookies.txt"
            cookies_path.write_text("", encoding="utf-8")
            state_path = root / "state.json"
            state_path.write_text("{}", encoding="utf-8")
            failure = oracle_youtube_job.OracleJobFailure(
                "yt_dlp_failure",
                "selected media section was not created",
                stage="media_cut",
                reason_code="media_section_not_created",
            )
            env = {
                "YOUTUBE_ORACLE_STATE_PATH": str(state_path),
                "YOUTUBE_ORACLE_COOKIES_PATH": str(cookies_path),
                "YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL": "https://par.example/upload",
                "YOUTUBE_ORACLE_WORK_ROOT": str(root),
            }
            with patch.dict(os.environ, env), patch.object(
                oracle_youtube_job, "_prepare_material", side_effect=failure
            ):
                with self.assertRaises(oracle_youtube_job.OracleJobFailure):
                    oracle_youtube_job.run(f"https://www.youtube.com/watch?v={video_id}")

            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(state.get("processed_video_ids", []), [])
        self.assertEqual(state["failure_records"][0]["video_id"], video_id)
        self.assertEqual(state["failure_records"][0]["reason_code"], "media_section_not_created")

    def test_run_persists_safe_reason_for_unexpected_exception(self):
        video_id = "ndKhBP5HXvc"
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            cookies_path = root / "youtube-cookies.txt"
            cookies_path.write_text("", encoding="utf-8")
            state_path = root / "state.json"
            state_path.write_text("{}", encoding="utf-8")
            env = {
                "YOUTUBE_ORACLE_STATE_PATH": str(state_path),
                "YOUTUBE_ORACLE_COOKIES_PATH": str(cookies_path),
                "YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL": "https://par.example/upload",
                "YOUTUBE_ORACLE_WORK_ROOT": str(root),
            }
            with patch.dict(os.environ, env), patch.object(
                oracle_youtube_job,
                "_prepare_material",
                side_effect=ValueError("private URL and token must not be retained"),
            ):
                with self.assertRaisesRegex(ValueError, "private URL"):
                    oracle_youtube_job.run(f"https://www.youtube.com/watch?v={video_id}")

            state_text = state_path.read_text(encoding="utf-8")
            state = json.loads(state_text)

        self.assertEqual(state["failure_records"][0]["reason_code"], "unexpected_exception")
        self.assertNotIn("private URL", state_text)

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
                oracle_youtube_job, "_read_published_video_ids", return_value=set()
            ), patch.object(
                oracle_youtube_job, "run", return_value=result
            ), patch.object(
                oracle_youtube_job, "_mark_processed"
            ) as mark_processed, patch.object(
                oracle_youtube_job, "_notify"
            ) as notify, redirect_stdout(output):
                exit_code = oracle_youtube_job.main()

        self.assertEqual(exit_code, 0)
        mark_processed.assert_called_once_with("AI5K5VH3BhY")
        notify.assert_called_once_with(None, failures=[])
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
                    raise oracle_youtube_job.OracleJobFailure("yt_dlp_failure", "format probe returned 403", reason_code="yt_dlp_unclassified_error")
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


    def test_live_chat_failures_have_distinct_safe_reason_codes(self):
        cases = (
            (None, "live_chat_artifact_missing"),
            ('{"event": true}\n', "live_chat_no_offsets"),
            ("not-json\n", "live_chat_jsonl_invalid"),
        )
        for contents, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason), tempfile.TemporaryDirectory() as raw_dir:
                work_dir = Path(raw_dir)

                def fake_ytdlp(command, **_kwargs):
                    if contents is not None:
                        output_path = Path(command[command.index("-o") + 1])
                        output_path.with_name("archive.live_chat.json").write_text(contents, encoding="utf-8")
                    return SimpleNamespace(stdout="")

                output = StringIO()
                with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp):
                    with redirect_stdout(output):
                        with self.assertRaises(oracle_youtube_job.OracleJobFailure) as caught:
                            oracle_youtube_job._download_chat_and_metadata(
                                "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                                work_dir,
                                "/remote/yt-dlp",
                                "/remote/deno",
                                "/remote/youtube-cookies.txt",
                            )

                self.assertEqual(caught.exception.stage, "live_chat")
                self.assertEqual(caught.exception.reason_code, expected_reason)
                self.assertIn(f"reason={expected_reason}", output.getvalue())
                if expected_reason == "live_chat_no_offsets":
                    self.assertIn("json_records=1", output.getvalue())
                    self.assertIn("offset_records=0", output.getvalue())
                if expected_reason == "live_chat_jsonl_invalid":
                    self.assertIn("invalid_json_lines=1", output.getvalue())

    def test_live_chat_diagnostics_never_log_chat_content(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            work_dir = Path(raw_dir)
            private_text = "private chat content"

            def fake_ytdlp(command, **_kwargs):
                if "--write-subs" in command:
                    output_path = Path(command[command.index("-o") + 1])
                    output_path.with_name("archive.live_chat.json").write_text(
                        json.dumps(
                            {
                                "videoOffsetTimeMsec": 1234,
                                "liveChatTextMessageRenderer": {
                                    "message": {"simpleText": private_text}
                                },
                            }
                        )
                        + "\n",
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

            output = StringIO()
            with patch.object(oracle_youtube_job, "_run_ytdlp", side_effect=fake_ytdlp):
                with redirect_stdout(output):
                    _video, comments = oracle_youtube_job._download_chat_and_metadata(
                        "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                        work_dir,
                        "/remote/yt-dlp",
                        "/remote/deno",
                        "/remote/youtube-cookies.txt",
                    )

        self.assertEqual(comments[0]["message"], private_text)
        self.assertIn("offset_records=1", output.getvalue())
        self.assertNotIn(private_text, output.getvalue())

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
                captions_result = oracle_youtube_job._download_captions(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    work_dir,
                    "/remote/yt-dlp",
                    "/remote/deno",
                    "/remote/youtube-cookies.txt",
                )

            self.assertEqual(captions_result["reason_code"], None)
            self.assertEqual(captions_result["source_outcomes"]["manual"], "available")
            payload = json.loads(Path(captions_result["path"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], "youtube_manual_captions")
            self.assertEqual(payload["cues"][0]["text"], "テスト字幕")

    def test_caption_download_error_is_distinguished_from_no_subtitle_track(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            result = None
            with patch.object(
                oracle_youtube_job,
                "_run_ytdlp",
                side_effect=oracle_youtube_job.OracleJobFailure("yt_dlp_failure", "private stderr", reason_code="yt_dlp_unclassified_error"),
            ):
                result = oracle_youtube_job._download_captions(
                    "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    Path(raw_dir),
                    "/remote/yt-dlp",
                    "/remote/deno",
                    "/remote/youtube-cookies.txt",
                )

        self.assertEqual(
            result,
            {
                "path": None,
                "reason_code": "caption_download_error",
                "source_outcomes": {"manual": "download_error", "automatic": "download_error"},
            },
        )

    def test_caption_download_failure_logs_safe_category_without_raw_stderr(self):
        output = StringIO()
        with patch.object(
            oracle_youtube_job,
            "_run_captured",
            return_value=SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="private subtitle failure detail",
            ),
        ), patch.object(oracle_youtube_job.time, "sleep", return_value=None):
            with redirect_stdout(output):
                with self.assertRaises(oracle_youtube_job.OracleJobFailure):
                    oracle_youtube_job._run_ytdlp(
                        ["yt-dlp"],
                        attempts=1,
                        safe_failure_context="youtube_caption_manual",
                    )

        self.assertIn("youtube_caption_manual failed: category=yt_dlp_failure", output.getvalue())
        self.assertNotIn("private subtitle failure detail", output.getvalue())

    def test_ytdlp_page_reload_is_classified_as_transient_network_failure(self):
        completed = SimpleNamespace(stdout="", stderr="ERROR: The page needs to be reloaded.")
        self.assertEqual(
            oracle_youtube_job._classify_ytdlp_failure(completed),
            "temporary_network_failure",
        )

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

        self.assertEqual(caught.exception.category, "temporary_network_failure")
        self.assertEqual(caught.exception.reason_code, "yt_dlp_temporary_network_failure")
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
                    raise oracle_youtube_job.OracleJobFailure("temporary_network_failure", "page reload required", reason_code="yt_dlp_temporary_network_failure")
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
                raise oracle_youtube_job.OracleJobFailure("live_chat_zero", "no chat", reason_code="live_chat_no_offsets")
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
                "YOUTUBE_ORACLE_STATE_PATH": str(Path(raw_dir) / "state.json"),
            }
            output = StringIO()
            with patch.dict(os.environ, env), patch.object(
                oracle_youtube_job, "_prepare_material", side_effect=fake_prepare
            ), patch.object(
                oracle_youtube_job, "create_material_batch_bundle"
            ) as bundle, patch.object(
                oracle_youtube_job, "upload_bundle_to_url"
            ), patch.object(
                oracle_youtube_job, "_dispatch_github"
            ) as dispatch, redirect_stdout(output):
                results = oracle_youtube_job.run_batch(
                    [
                        "https://www.youtube.com/watch?v=aTCWAb8wRd8",
                        "https://www.youtube.com/watch?v=2a_ATYeOiAQ",
                        "https://www.youtube.com/watch?v=930HUhvRKHc",
                    ]
                )
            state = json.loads(Path(env["YOUTUBE_ORACLE_STATE_PATH"]).read_text(encoding="utf-8"))

        self.assertEqual([item["video_id"] for item in results], ["aTCWAb8wRd8", "930HUhvRKHc"])
        self.assertEqual(dispatch.call_args.args[0], ["aTCWAb8wRd8", "930HUhvRKHc"])
        bundle.assert_called_once()
        self.assertEqual(state["failure_records"][0]["video_id"], "2a_ATYeOiAQ")
        self.assertEqual(state["failure_records"][0]["category"], "live_chat_zero")
        self.assertEqual(state["failure_records"][0]["reason_code"], "live_chat_no_offsets")
        self.assertIn("batch preparation summary: selected=3 prepared=2 skipped=1", output.getvalue())

    def test_batch_preflight_failure_is_retained_for_every_selected_video(self):
        video_urls = [
            "https://www.youtube.com/watch?v=aTCWAb8wRd8",
            "https://www.youtube.com/watch?v=2a_ATYeOiAQ",
        ]
        with tempfile.TemporaryDirectory() as raw_dir:
            cookies_path = Path(raw_dir) / "youtube-cookies.txt"
            cookies_path.write_text("", encoding="utf-8")
            state_path = Path(raw_dir) / "state.json"
            state_path.write_text("{}", encoding="utf-8")
            env = {
                "YOUTUBE_ORACLE_COOKIES_PATH": str(cookies_path),
                "YOUTUBE_ORACLE_STATE_PATH": str(state_path),
                "YOUTUBE_ORACLE_WORK_ROOT": str(raw_dir),
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaises(oracle_youtube_job.OracleJobFailure) as caught:
                    oracle_youtube_job.run_batch(video_urls)
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(caught.exception.category, "handoff_configuration")
        self.assertEqual(
            [record["video_id"] for record in state["failure_records"]],
            ["aTCWAb8wRd8", "2a_ATYeOiAQ"],
        )
        self.assertTrue(all(record["reason_code"] == "bundle_upload_par_missing" for record in state["failure_records"]))

    def test_batch_raises_when_every_archive_fails(self):
        def fake_prepare(_video_url, _work_dir, *_args, **_kwargs):
            raise oracle_youtube_job.OracleJobFailure("live_chat_zero", "no chat", reason_code="live_chat_no_offsets")

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
        self.assertEqual(
            captions_path,
            {
                "path": None,
                "reason_code": "caption_track_not_found",
                "source_outcomes": {"manual": "track_not_found", "automatic": "track_not_found"},
            },
        )


    def test_main_failure_log_includes_stage_and_reason(self):
        output = StringIO()
        failure = oracle_youtube_job.OracleJobFailure(
            "live_chat_zero",
            "missing chat artifact",
            stage="live_chat",
            reason_code="live_chat_artifact_missing",
        )
        with patch.dict(os.environ, {"YOUTUBE_ORACLE_STREAMS_URL": ""}, clear=True), patch.object(
            sys,
            "argv",
            ["oracle_youtube_job", "--video-url", "https://www.youtube.com/watch?v=WGTrmrSvZH0"],
        ), patch.object(
            oracle_youtube_job,
            "_read_published_video_ids",
            return_value=set(),
        ), patch.object(oracle_youtube_job, "_notify"), patch.object(
            oracle_youtube_job,
            "run",
            side_effect=failure,
        ), redirect_stdout(output):
            result = oracle_youtube_job.main()

        self.assertEqual(result, 1)
        self.assertIn(
            "oracle YouTube job failed: category=live_chat_zero stage=live_chat reason=live_chat_artifact_missing",
            output.getvalue(),
        )


class OracleNotificationTests(unittest.TestCase):
    def test_failed_discord_delivery_retries_and_suppresses_duplicate(self):
        webhook = "https://example.invalid/webhook/test-value"
        render_url = "https://video-highlights-site.onrender.com"
        failure = {
            "video_id": "DFJ6L1ESayE",
            "failed_at": "2026-10-09T00:00:00Z",
            "category": "live_chat_zero",
            "stage": "live_chat",
            "reason_code": "live_chat_artifact_missing",
        }
        state = {}
        deliveries = []
        output = StringIO()

        def send(_webhook, content, *, event):
            deliveries.append((content, event))
            return len(deliveries) == 2

        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": webhook}, clear=True), patch.object(
            oracle_youtube_job, "_read_state", return_value=state
        ), patch.object(oracle_youtube_job, "_persist_notification_state") as persist, patch.object(
            oracle_youtube_job, "_render_site_url", return_value=render_url
        ), patch.object(oracle_youtube_job, "_send_discord", side_effect=send), redirect_stdout(output):
            oracle_youtube_job._notify(None, failures=[failure])
            self.assertFalse(state["failure_notified"])
            self.assertIsNone(state["failure_notification_version"])

            oracle_youtube_job._notify(None, failures=[failure])
            self.assertTrue(state["failure_notified"])
            self.assertEqual(
                state["failure_notification_version"],
                oracle_youtube_job.FAILURE_NOTIFICATION_VERSION,
            )

            oracle_youtube_job._notify(None, failures=[failure])

        self.assertEqual(len(deliveries), 2)
        self.assertEqual([event for _content, event in deliveries], ["failure", "failure"])
        self.assertEqual(persist.call_count, 3)
        self.assertIn("stage: live_chat", deliveries[0][0])
        self.assertIn("reason: live_chat_artifact_missing", deliveries[0][0])
        self.assertIn("video_id=DFJ6L1ESayE", deliveries[0][0])
        self.assertIn(render_url, deliveries[0][0])
        self.assertIn("reason=already_notified", output.getvalue())

    def test_discord_http_error_logs_status_without_webhook_or_message(self):
        webhook = "https://example.invalid/webhook/test-value"
        private_message = "private notification content"
        http_error = oracle_youtube_job.error.HTTPError(
            webhook, 429, "Too Many Requests", hdrs=None, fp=None
        )
        output = StringIO()

        with patch.object(oracle_youtube_job.request, "urlopen", side_effect=http_error), redirect_stdout(
            output
        ):
            delivered = oracle_youtube_job._send_discord(
                webhook, private_message, event="failure"
            )

        self.assertFalse(delivered)
        log = output.getvalue()
        self.assertIn("stage=discord_webhook", log)
        self.assertIn("status=429", log)
        self.assertNotIn(webhook, log)
        self.assertNotIn(private_message, log)


if __name__ == "__main__":
    unittest.main()
