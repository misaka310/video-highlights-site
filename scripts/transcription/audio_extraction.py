from __future__ import annotations

import subprocess
from pathlib import Path

from youtube_url import is_youtube_url


def build_download_command(
    *,
    vod_url: str,
    start_label: str,
    end_label: str,
    output_template: str,
    python_executable: str,
    youtube_format: str | None,
    force_ipv4: bool = False,
) -> list[str]:
    command = [
        python_executable,
        "-m",
        "yt_dlp",
        "--force-overwrites",
        "--no-playlist",
        "--no-warnings",
        "--no-progress",
        "--download-sections",
        f"*{start_label}-{end_label}",
        "-o",
        output_template,
    ]
    if force_ipv4:
        command.insert(3, "--force-ipv4")
    if youtube_format:
        command.extend(["-f", youtube_format])
    command.append(vod_url)
    return command


def download_segment_media(
    *,
    vod_url: str,
    start_label: str,
    end_label: str,
    work_dir: Path,
    python_executable: str,
    timeout_sec: int,
    video_required: bool = True,
) -> Path:
    output_template = work_dir / "clip.%(ext)s"
    is_youtube = is_youtube_url(vod_url)
    command = build_download_command(
        vod_url=vod_url,
        start_label=start_label,
        end_label=end_label,
        output_template=str(output_template),
        python_executable=python_executable,
        youtube_format=(
            (
                (
                    "worstvideo[protocol=https]+worstaudio[protocol=https]/"
                    "worst[protocol=https]/worst"
                )
                if video_required
                else "worstaudio[protocol=https]/bestaudio[protocol=https]"
            )
            if is_youtube
            else None
        ),
        force_ipv4=is_youtube,
    )
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, int(timeout_sec)),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"yt-dlp timed out after {timeout_sec}s") from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "yt-dlp failed").strip()
        raise RuntimeError(stderr[:500])

    media_files = [
        path
        for path in sorted(work_dir.iterdir())
        if path.is_file() and path.suffix not in {".part", ".ytdl"}
    ]
    if not media_files:
        raise RuntimeError("yt-dlp did not produce a media file")
    return media_files[0]

