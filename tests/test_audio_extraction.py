import unittest
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from transcription.audio_extraction import build_download_command, download_segment_media


class AudioExtractionCommandTests(unittest.TestCase):
    def test_youtube_segment_download_uses_lightweight_video_and_best_audio(self):
        command = build_download_command(
            vod_url="https://www.youtube.com/watch?v=930HUhvRKHc",
            start_label="03:45:35",
            end_label="03:48:05",
            output_template="C:/tmp/clip.%(ext)s",
            python_executable="python",
            youtube_format=(
                "worstvideo[protocol=https]+worstaudio[protocol=https]/"
                "worst[protocol=https]/worst"
            ),
            force_ipv4=True,
        )

        self.assertEqual(
            command[command.index("-f") + 1],
            "worstvideo[protocol=https]+worstaudio[protocol=https]/worst[protocol=https]/worst",
        )
        self.assertIn("--force-ipv4", command)

    def test_twitch_segment_download_keeps_existing_format_selection(self):
        command = build_download_command(
            vod_url="https://www.twitch.tv/videos/2873115795",
            start_label="00:47:25",
            end_label="00:50:25",
            output_template="C:/tmp/clip.%(ext)s",
            python_executable="python",
            youtube_format=None,
            force_ipv4=False,
        )

        self.assertNotIn("-f", command)
        self.assertNotIn("--force-ipv4", command)

    def test_youtube_segment_download_can_skip_video_when_screenshots_are_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                (work_dir / "clip.webm").write_bytes(b"audio")
                return SimpleNamespace(returncode=0, stderr="", stdout="")

            with patch("transcription.audio_extraction.subprocess.run", side_effect=fake_run):
                download_segment_media(
                    vod_url="https://www.youtube.com/watch?v=930HUhvRKHc",
                    start_label="03:45:35",
                    end_label="03:48:05",
                    work_dir=work_dir,
                    python_executable="python",
                    timeout_sec=300,
                    video_required=False,
                )

        self.assertEqual(
            commands[0][commands[0].index("-f") + 1],
            "worstaudio[protocol=https]/bestaudio[protocol=https]",
        )
        self.assertIn("--force-ipv4", commands[0])

    def test_spoofed_youtube_path_keeps_generic_download_options(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            commands = []

            def fake_run(command, **_kwargs):
                commands.append(command)
                (work_dir / "clip.webm").write_bytes(b"audio")
                return SimpleNamespace(returncode=0, stderr="", stdout="")

            with patch("transcription.audio_extraction.subprocess.run", side_effect=fake_run):
                download_segment_media(
                    vod_url="https://attacker.example/youtube.com/watch?v=930HUhvRKHc",
                    start_label="03:45:35",
                    end_label="03:48:05",
                    work_dir=work_dir,
                    python_executable="python",
                    timeout_sec=300,
                    video_required=False,
                )

        self.assertNotIn("--force-ipv4", commands[0])
        self.assertNotIn("-f", commands[0])


if __name__ == "__main__":
    unittest.main()
