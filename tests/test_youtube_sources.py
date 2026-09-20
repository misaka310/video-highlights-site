import json
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from youtube_sources import (  # noqa: E402
    YoutubeOracleConfig,
    build_oracle_command,
    fetch_youtube_video,
    parse_youtube_oracle_output,
    parse_youtube_video_id,
    youtube_oracle_config_from_env,
)
import vod_serialization as serialization  # noqa: E402
import vod_sources  # noqa: E402
import update_vods as uv  # noqa: E402
import youtube_update  # noqa: E402


class YoutubeSourceTests(unittest.TestCase):
    def test_youtube_public_filter_excludes_legacy_twitch_cache_entries(self):
        videos = [
            {
                "vod_id": "2873115795",
                "vod_url": "https://www.twitch.tv/videos/2873115795",
                "published_at": "2026-09-13T00:00:00+00:00",
            },
            {
                "provider": "youtube",
                "vod_id": "WGTrmrSvZH0",
                "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                "published_at": "2026-09-13T00:00:00+00:00",
            },
        ]

        self.assertEqual(
            [video["vod_id"] for video in serialization.filter_youtube_videos(videos)],
            ["WGTrmrSvZH0"],
        )

    def test_youtube_public_filter_rejects_a_spoofed_youtube_path(self):
        videos = [
            {
                "vod_id": "spoofed",
                "vod_url": "https://attacker.example/youtube.com/watch?v=WGTrmrSvZH0",
            },
            {
                "vod_id": "WGTrmrSvZH0",
                "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            },
        ]

        self.assertEqual(
            [video["vod_id"] for video in serialization.filter_youtube_videos(videos)],
            ["WGTrmrSvZH0"],
        )

    def test_youtube_update_publishes_only_the_youtube_cache_scope(self):
        youtube_video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "YouTube archive",
            "published_at": "2026-09-13T00:00:00+00:00",
            "chat_total": 1,
            "items": [{"id": "WGTrmrSvZH0_10_20", "start_sec": 10, "end_sec": 20}],
        }
        public_batches = []

        def analyze(video, _now, **_kwargs):
            return dict(video), "analyzed"

        youtube_update.run_youtube_mode(
            datetime(2026, 9, 17, tzinfo=timezone.utc),
            youtube_video["vod_url"],
            analyze_video_entry=analyze,
            load_processed_cache=lambda: {
                "videos": [
                    {"vod_id": "2873115795", "vod_url": "https://www.twitch.tv/videos/2873115795"},
                    {**youtube_video, "vod_id": "older-youtube"},
                ]
            },
            write_processed_cache=lambda _videos, _now: None,
            write_public_data=lambda videos, _now: public_batches.append(list(videos)),
            output_path=Path("data/vods.json"),
            fetch_video=lambda _url: SimpleNamespace(
                video=youtube_video,
                chat=vod_sources.ChatFetchResult(comments=[{"content_offset_seconds": 10.0}], duration_sec=20),
            ),
            enrich_video=lambda video: (video, SimpleNamespace(transcribed=1, headlines=1, screenshots=1)),
        )

        self.assertEqual(
            [video["vod_id"] for video in public_batches[0]],
            ["older-youtube", "WGTrmrSvZH0"],
        )

    def test_parse_youtube_video_id_accepts_public_url_shapes(self):
        self.assertEqual(parse_youtube_video_id("https://www.youtube.com/watch?v=WGTrmrSvZH0"), "WGTrmrSvZH0")
        self.assertEqual(parse_youtube_video_id("https://youtu.be/WGTrmrSvZH0?t=30"), "WGTrmrSvZH0")
        self.assertEqual(parse_youtube_video_id("WGTrmrSvZH0"), "WGTrmrSvZH0")

    def test_parse_oracle_output_normalizes_offsets_and_drops_chat_payload(self):
        output = "\n".join(
            [
                json.dumps(
                    {
                        "type": "metadata",
                        "video_id": "WGTrmrSvZH0",
                        "title": "Oracle archive",
                        "published_at": "2026-07-25T00:00:00+00:00",
                        "thumbnail_url": "https://i.ytimg.com/vi/WGTrmrSvZH0/hqdefault.jpg",
                        "duration_sec": 13678,
                    }
                ),
                json.dumps(
                    {
                        "replayChatItemAction": {
                            "videoOffsetTimeMsec": "123456",
                            "actions": [{"message": "private text", "author": "private user"}],
                        }
                    }
                ),
                json.dumps({"videoOffsetTimeMsec": 2000}),
                json.dumps({"videoOffsetTimeMsec": "invalid"}),
            ]
        )

        result = parse_youtube_oracle_output(output, "https://www.youtube.com/watch?v=WGTrmrSvZH0")

        self.assertEqual(result.video["vod_id"], "WGTrmrSvZH0")
        self.assertEqual(result.video["provider"], "youtube")
        self.assertEqual(result.video["duration_sec"], 13678)
        self.assertEqual([item["content_offset_seconds"] for item in result.chat.comments], [123.456, 2.0])
        self.assertNotIn("message", result.chat.comments[0])

    def test_parse_oracle_output_keeps_message_only_in_memory_for_tag_detection(self):
        output = "\n".join(
            [
                "__YOUTUBE_ORACLE_TSV_BEGIN__",
                "video_offset\tposted_at_jst\tmessage",
                "00:00:10.500\t2026-09-17T10:00:00+09:00\tすごいww",
                "__YOUTUBE_ORACLE_TSV_END__",
                "__YOUTUBE_ORACLE_METADATA_BEGIN__",
                json.dumps(
                    {
                        "id": "930HUhvRKHc",
                        "title": "video",
                        "upload_date": "20260917",
                        "duration": 100,
                    }
                ),
                "__YOUTUBE_ORACLE_METADATA_END__",
            ]
        )

        result = parse_youtube_oracle_output(output, "930HUhvRKHc")

        self.assertEqual(result.chat.comments[0]["message"], "すごいww")
        self.assertNotIn("author", result.chat.comments[0])

    def test_parse_oracle_output_accepts_yt_dlp_infojson_metadata(self):
        output = "\n".join(
            [
                json.dumps(
                    {
                        "id": "WGTrmrSvZH0",
                        "title": "Archive from Oracle",
                        "upload_date": "20260725",
                        "duration": 13678.2,
                        "thumbnail": "https://i.ytimg.com/vi/WGTrmrSvZH0/maxresdefault.jpg",
                    }
                ),
                json.dumps({"videoOffsetTimeMsec": 5000}),
            ]
        )

        result = parse_youtube_oracle_output(output, "WGTrmrSvZH0")

        self.assertEqual(result.video["title"], "Archive from Oracle")
        self.assertEqual(result.video["published_at"], "2026-07-25T00:00:00+00:00")
        self.assertEqual(result.video["duration_sec"], 13679)
        self.assertEqual(
            result.video["thumbnail_url"],
            "https://i.ytimg.com/vi/WGTrmrSvZH0/maxresdefault.jpg",
        )

    def test_parse_oracle_script_output_accepts_livechat_tsv_and_ignores_transport_logs(self):
        output = "\n".join(
            [
                "REMOTE_HOST=primary-vnic",
                "2026.08.19",
                "[youtube_live_chat] Downloading live chat",
                "ORACLE_CHAT_COUNT= 1365",
                "__YOUTUBE_ORACLE_TSV_BEGIN__",
                "video_offset\tposted_at_jst",
                "00:00:00.000\t2026-09-13T22:20:12.467+09:00",
                "00:00:55.830\t2026-09-13T22:24:46.148+09:00",
                "03:47:58.311\t2026-09-14T02:11:48.522+09:00",
                "__YOUTUBE_ORACLE_TSV_END__",
                "__YOUTUBE_ORACLE_METADATA_BEGIN__",
                json.dumps(
                    {
                        "id": "WGTrmrSvZH0",
                        "title": "Confirmed Oracle title",
                        "upload_date": "20260913",
                        "duration": 13679,
                        "thumbnail": "https://i.ytimg.com/vi/WGTrmrSvZH0/maxresdefault.jpg",
                    }
                ),
                "__YOUTUBE_ORACLE_METADATA_END__",
                "RAW_CHAT_REMOVED=YES",
            ]
        )

        result = parse_youtube_oracle_output(
            output,
            "WGTrmrSvZH0",
            allow_transport_logs=True,
        )

        self.assertEqual(len(result.chat.comments), 3)
        self.assertEqual(result.chat.comments[-1]["content_offset_seconds"], 13678.311)
        self.assertEqual(result.video["title"], "Confirmed Oracle title")
        self.assertEqual(result.video["published_at"], "2026-09-13T00:00:00+00:00")
        self.assertEqual(result.video["duration_sec"], 13679)

    def test_oracle_config_uses_the_configured_route(self):
        config = youtube_oracle_config_from_env(
            {
                "YOUTUBE_ORACLE_HOST": "oracle.example.test",
                "YOUTUBE_ORACLE_USER": "oracle-user",
                "YOUTUBE_ORACLE_KEY_PATH": "test-ssh-key",
                "YOUTUBE_ORACLE_SCRIPT_PATH": "test-oracle-script",
            }
        )
        self.assertEqual(
            build_oracle_command(config, "WGTrmrSvZH0"),
            [
                "ssh.exe",
                "-i",
                "test-ssh-key",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=20",
                "oracle-user@oracle.example.test",
                "bash",
                "-s",
            ],
        )

    def test_oracle_config_has_no_machine_specific_defaults(self):
        config = youtube_oracle_config_from_env({})

        self.assertEqual(config.host, "")
        self.assertEqual(config.user, "")
        self.assertIsNone(config.key_path)
        self.assertIsNone(config.script_path)

    def test_parse_oracle_output_rejects_video_id_mismatch_and_empty_chat(self):
        mismatch = json.dumps({"type": "metadata", "video_id": "different01"})
        with self.assertRaises(ValueError):
            parse_youtube_oracle_output(mismatch, "WGTrmrSvZH0")

        with self.assertRaises(ValueError):
            parse_youtube_oracle_output(json.dumps({"type": "metadata", "video_id": "WGTrmrSvZH0"}), "WGTrmrSvZH0")

    def test_build_oracle_command_requires_remote_command_and_url_token(self):
        config = YoutubeOracleConfig(
            host="oracle.example.test",
            user="oracle-user",
            key_path=Path("test-ssh-key"),
            script_path=Path("test-oracle-script"),
        )
        self.assertEqual(build_oracle_command(config, "WGTrmrSvZH0")[-3:], ["oracle-user@oracle.example.test", "bash", "-s"])

    def test_fetch_uses_script_over_ssh_without_text_newline_conversion(self):
        config = YoutubeOracleConfig(
            host="oracle.example.test",
            user="oracle-user",
            # The runner is mocked here, so use this tracked test file instead
            # of requiring the developer's private key and external script.
            key_path=Path(__file__),
            script_path=Path(__file__),
        )
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    "__YOUTUBE_ORACLE_TSV_BEGIN__\n"
                    "video_offset\tposted_at_jst\n"
                    "00:00:01.000\t2026-09-13T22:20:13.000+09:00\n"
                    "__YOUTUBE_ORACLE_TSV_END__\n"
                ).encode("utf-8"),
            )

        result = fetch_youtube_video("WGTrmrSvZH0", config=config, runner=runner)

        self.assertEqual(len(result.chat.comments), 1)
        self.assertIsInstance(calls[0][1]["input"], bytes)
        self.assertIn("bash", calls[0][0])
        self.assertIn(b"WGTrmrSvZH0", calls[0][1]["input"])

    def test_youtube_provider_is_serialized_and_uses_oracle_chat_dispatch(self):
        source = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "Oracle archive",
            "published_at": "2026-07-25T00:00:00+00:00",
            "items": [],
            "activity_map": {},
        }
        public = serialization.to_public_video_entry(source)
        index = serialization.to_public_video_index_entry(source)
        self.assertEqual(public["provider"], "youtube")
        self.assertEqual(index["provider"], "youtube")

        with patch("youtube_sources.fetch_youtube_video") as fetch:
            fetch.return_value.chat.comments = [{"content_offset_seconds": 3.0}]
            result = vod_sources.fetch_chat_data(
                "WGTrmrSvZH0",
                vod_sources.FetchConfig(),
                provider="youtube",
                vod_url="https://www.youtube.com/watch?v=WGTrmrSvZH0",
            )
        self.assertEqual(result.comments, [{"content_offset_seconds": 3.0}])
        fetch.assert_called_once()

    def test_update_analysis_keeps_youtube_provider_and_oracle_metadata(self):
        source_video = {
            "provider": "youtube",
            "vod_id": "WGTrmrSvZH0",
            "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
            "title": "input title",
            "published_at": "2026-07-25T00:00:00+00:00",
            "thumbnail_url": "",
        }
        oracle_result = type(
            "YoutubeResult",
            (),
            {
                "video": {
                    "provider": "youtube",
                    "vod_id": "WGTrmrSvZH0",
                    "vod_url": "https://www.youtube.com/watch?v=WGTrmrSvZH0",
                    "title": "Oracle title",
                    "published_at": "2026-07-25T00:00:00+00:00",
                    "thumbnail_url": "https://i.ytimg.com/vi/WGTrmrSvZH0/hqdefault.jpg",
                    "duration_sec": 100,
                },
                "chat": vod_sources.ChatFetchResult(
                    comments=[{"content_offset_seconds": 20.0}],
                    duration_sec=100,
                ),
            },
        )()
        with patch("update_vods.fetch_youtube_video", return_value=oracle_result):
            with patch("update_vods.build_activity_map", return_value={"duration_sec": 100, "buckets": [1]}):
                with patch(
                    "update_vods.detect_items",
                    return_value=[{"id": "WGTrmrSvZH0_20_40", "start_sec": 20, "end_sec": 40}],
                ):
                    analyzed, status = uv.analyze_video_entry(
                        source_video,
                        datetime(2026, 7, 25, tzinfo=timezone.utc),
                    )

        self.assertEqual(status, "analyzed")
        self.assertEqual(analyzed["provider"], "youtube")
        self.assertEqual(analyzed["title"], "Oracle title")
        self.assertEqual(analyzed["duration_sec"], 100)

    def test_update_analysis_does_not_turn_tags_into_youtube_headline(self):
        source_video = {
            "provider": "youtube",
            "vod_id": "930HUhvRKHc",
            "vod_url": "https://www.youtube.com/watch?v=930HUhvRKHc",
            "title": "input title",
            "published_at": "2026-09-17T00:00:00+00:00",
            "thumbnail_url": "",
        }
        oracle_result = type(
            "YoutubeResult",
            (),
            {
                "video": source_video,
                "chat": vod_sources.ChatFetchResult(
                    comments=[{"content_offset_seconds": 20.0, "message": "すごいww"}],
                    duration_sec=100,
                ),
            },
        )()
        with patch("update_vods.fetch_youtube_video", return_value=oracle_result):
            with patch("update_vods.build_activity_map", return_value={"duration_sec": 100, "buckets": [1]}):
                with patch(
                    "update_vods.detect_items",
                    return_value=[
                        {
                            "id": "930HUhvRKHc_20_40",
                            "start_sec": 20,
                            "end_sec": 40,
                            "tags": ["ww"],
                        }
                    ],
                ):
                    analyzed, status = uv.analyze_video_entry(
                        source_video,
                        datetime(2026, 9, 17, tzinfo=timezone.utc),
                    )

        self.assertEqual(status, "analyzed")
        self.assertNotIn("headline", analyzed["items"][0])

    def test_cache_normalization_preserves_existing_twitch_duration(self):
        normalized = uv.normalize_cached_video(
            {
                "vod_id": "2873115795",
                "vod_url": "https://www.twitch.tv/videos/2873115795",
                "published_at": "2026-09-13T22:23:16+09:00",
                "duration_sec": 13714,
                "items": [],
            }
        )
        self.assertEqual(normalized["duration_sec"], 13714)


if __name__ == "__main__":
    unittest.main()
