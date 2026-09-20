from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlparse

from vod_sources import ChatFetchResult
from youtube_url import YOUTUBE_URL_HOSTS


YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_ORACLE_HOST_ENV = "YOUTUBE_ORACLE_HOST"
YOUTUBE_ORACLE_USER_ENV = "YOUTUBE_ORACLE_USER"
YOUTUBE_ORACLE_KEY_ENV = "YOUTUBE_ORACLE_KEY_PATH"
YOUTUBE_ORACLE_SCRIPT_ENV = "YOUTUBE_ORACLE_SCRIPT_PATH"
YOUTUBE_ORACLE_TIMEOUT_ENV = "YOUTUBE_ORACLE_TIMEOUT_SEC"
YOUTUBE_ORACLE_REMOTE_TSV_ENV = "YOUTUBE_ORACLE_REMOTE_TSV_TEMPLATE"
YOUTUBE_ORACLE_REMOTE_YTDLP_ENV = "YOUTUBE_ORACLE_REMOTE_YTDLP_PATH"
YOUTUBE_ORACLE_REMOTE_DENO_ENV = "YOUTUBE_ORACLE_REMOTE_DENO_PATH"
YOUTUBE_ORACLE_REMOTE_COOKIES_ENV = "YOUTUBE_ORACLE_REMOTE_COOKIES_PATH"
YOUTUBE_ORACLE_TSV_BEGIN = "__YOUTUBE_ORACLE_TSV_BEGIN__"
YOUTUBE_ORACLE_TSV_END = "__YOUTUBE_ORACLE_TSV_END__"
YOUTUBE_ORACLE_METADATA_BEGIN = "__YOUTUBE_ORACLE_METADATA_BEGIN__"
YOUTUBE_ORACLE_METADATA_END = "__YOUTUBE_ORACLE_METADATA_END__"
DEFAULT_YOUTUBE_ORACLE_TSV_TEMPLATE = "$HOME/ytprobe/{video_id}-comment-times.tsv"
DEFAULT_YOUTUBE_ORACLE_REMOTE_YTDLP = "$HOME/yt-dlp"
DEFAULT_YOUTUBE_ORACLE_REMOTE_DENO = "$HOME/.local/bin/deno"
DEFAULT_YOUTUBE_ORACLE_REMOTE_COOKIES = "$HOME/youtube-cookies.txt"


@dataclass(frozen=True)
class YoutubeOracleConfig:
    host: str
    user: str
    key_path: Path | None
    script_path: Path | None
    timeout_sec: int = 300


@dataclass(frozen=True)
class YoutubeFetchResult:
    video: dict[str, Any]
    chat: ChatFetchResult


def parse_youtube_video_id(value: str) -> str:
    raw = str(value or "").strip()
    if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(raw):
        return raw

    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").lower()
    if hostname not in YOUTUBE_URL_HOSTS:
        raise ValueError("unsupported YouTube URL")

    if hostname in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    else:
        parts = [part for part in parsed.path.split("/") if part]
        candidate = parts[1] if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"} else ""

    if not YOUTUBE_VIDEO_ID_PATTERN.fullmatch(candidate):
        raise ValueError("missing or invalid YouTube video id")
    return candidate


def build_oracle_command(config: YoutubeOracleConfig, video_id: str) -> list[str]:
    if not config.host or not config.user:
        raise ValueError("YouTube Oracle host and user are required")
    if config.key_path is None:
        raise ValueError("YouTube Oracle SSH key path is required")
    if config.script_path is None:
        raise ValueError("YouTube Oracle script path is required")
    return [
        "ssh.exe",
        "-i",
        str(config.key_path),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        f"{config.user}@{config.host}",
        "bash",
        "-s",
    ]


def youtube_oracle_config_from_env(env: Mapping[str, str] | None = None) -> YoutubeOracleConfig:
    source = os.environ if env is None else env
    try:
        timeout_sec = int(str(source.get(YOUTUBE_ORACLE_TIMEOUT_ENV) or "300"))
    except ValueError:
        timeout_sec = 300
    if timeout_sec <= 0:
        timeout_sec = 300
    host = str(source.get(YOUTUBE_ORACLE_HOST_ENV) or "").strip()
    user = str(source.get(YOUTUBE_ORACLE_USER_ENV) or "").strip()
    configured_key_path = str(source.get(YOUTUBE_ORACLE_KEY_ENV) or "").strip()
    configured_script_path = str(source.get(YOUTUBE_ORACLE_SCRIPT_ENV) or "").strip()
    key_path = Path(configured_key_path) if configured_key_path else None
    script_path = Path(configured_script_path) if configured_script_path else None
    return YoutubeOracleConfig(
        host=host,
        user=user,
        key_path=key_path,
        script_path=script_path,
        timeout_sec=timeout_sec,
    )


def _remote_shell_path(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not (normalized.startswith("/") or normalized.startswith("$HOME/")) or any(
        char in normalized for char in "'\"\n\r`;&|"
    ):
        raise ValueError(f"{name} must be an absolute or $HOME-relative shell-safe path")
    return normalized


def fetch_youtube_video(
    video_url: str,
    config: YoutubeOracleConfig | None = None,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> YoutubeFetchResult:
    video_id = parse_youtube_video_id(video_url)
    oracle_config = config or youtube_oracle_config_from_env()
    if oracle_config.key_path is None:
        raise RuntimeError("YouTube Oracle SSH key path is not configured")
    if oracle_config.script_path is None:
        raise RuntimeError("YouTube Oracle script path is not configured")
    if not oracle_config.key_path.is_file():
        raise RuntimeError(f"YouTube Oracle SSH key was not found: {oracle_config.key_path}")
    if not oracle_config.script_path.is_file():
        raise RuntimeError(f"YouTube Oracle script was not found: {oracle_config.script_path}")
    command = build_oracle_command(oracle_config, video_id)
    script = oracle_config.script_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    script = script.replace("WGTrmrSvZH0", video_id).rstrip() + "\n"
    remote_tsv = _remote_shell_path(
        str(os.environ.get(YOUTUBE_ORACLE_REMOTE_TSV_ENV) or DEFAULT_YOUTUBE_ORACLE_TSV_TEMPLATE).format(video_id=video_id),
        YOUTUBE_ORACLE_REMOTE_TSV_ENV,
    )
    remote_ytdlp = _remote_shell_path(
        str(os.environ.get(YOUTUBE_ORACLE_REMOTE_YTDLP_ENV) or DEFAULT_YOUTUBE_ORACLE_REMOTE_YTDLP),
        YOUTUBE_ORACLE_REMOTE_YTDLP_ENV,
    )
    remote_deno = _remote_shell_path(
        str(os.environ.get(YOUTUBE_ORACLE_REMOTE_DENO_ENV) or DEFAULT_YOUTUBE_ORACLE_REMOTE_DENO),
        YOUTUBE_ORACLE_REMOTE_DENO_ENV,
    )
    remote_cookies = _remote_shell_path(
        str(os.environ.get(YOUTUBE_ORACLE_REMOTE_COOKIES_ENV) or DEFAULT_YOUTUBE_ORACLE_REMOTE_COOKIES),
        YOUTUBE_ORACLE_REMOTE_COOKIES_ENV,
    )
    script += (
        f"printf '%s\\n' '{YOUTUBE_ORACLE_TSV_BEGIN}'\n"
        f"cat \"{remote_tsv}\"\n"
        f"printf '%s\\n' '{YOUTUBE_ORACLE_TSV_END}'\n"
        f"rm -f \"{remote_tsv}\"\n"
        f"printf '%s\\n' '{YOUTUBE_ORACLE_METADATA_BEGIN}'\n"
        f"\"{remote_ytdlp}\" "
        f"--js-runtimes \"deno:{remote_deno}\" "
        "--remote-components ejs:github "
        f"--cookies \"{remote_cookies}\" "
        "--skip-download --no-playlist "
        "--print \"%(.{id,title,upload_date,duration,thumbnail})j\" "
        f"\"https://www.youtube.com/watch?v={video_id}\" 2>/dev/null\n"
        f"printf '%s\\n' '{YOUTUBE_ORACLE_METADATA_END}'\n"
    )
    completed = runner(
        command,
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=oracle_config.timeout_sec,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Oracle YouTube fetch failed for {video_id}")
    stdout = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, bytes) else completed.stdout
    return parse_youtube_oracle_output(stdout or "", video_url, allow_transport_logs=True)


def parse_youtube_oracle_output(
    output: str,
    expected_video: str,
    *,
    allow_transport_logs: bool = False,
) -> YoutubeFetchResult:
    expected_video_id = parse_youtube_video_id(expected_video)
    metadata: dict[str, Any] = {}
    offsets: list[float] = []
    messages: list[str | None] = []
    in_tsv = False
    in_metadata = False

    for line_number, raw_line in enumerate(str(output or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line == YOUTUBE_ORACLE_TSV_BEGIN:
            in_tsv = True
            continue
        if line == YOUTUBE_ORACLE_TSV_END:
            in_tsv = False
            continue
        if line == YOUTUBE_ORACLE_METADATA_BEGIN:
            in_metadata = True
            continue
        if line == YOUTUBE_ORACLE_METADATA_END:
            in_metadata = False
            continue
        if in_tsv:
            if line == "video_offset\tposted_at_jst":
                continue
            if line == "video_offset\tposted_at_jst\tmessage":
                continue
            parts = line.split("\t", 2)
            if len(parts) == 2:
                offset = _parse_clock_offset(parts[0])
                if offset is not None:
                    offsets.append(offset)
                    messages.append(None)
                    continue
            if len(parts) == 3:
                offset = _parse_clock_offset(parts[0])
                if offset is not None:
                    offsets.append(offset)
                    message = parts[2].strip()
                    messages.append(message or None)
                    continue
            raise ValueError(f"Oracle TSV line {line_number} is invalid")
        if in_metadata:
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Oracle metadata line {line_number} is not JSON") from exc
            before_count = len(offsets)
            _collect_oracle_record(record, metadata, offsets)
            messages.extend([None] * (len(offsets) - before_count))
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            if allow_transport_logs:
                continue
            raise ValueError(f"Oracle output line {line_number} is not JSON") from exc
        before_count = len(offsets)
        _collect_oracle_record(record, metadata, offsets)
        messages.extend([None] * (len(offsets) - before_count))

    metadata_video_id = str(metadata.get("video_id") or "").strip()
    if metadata_video_id and metadata_video_id != expected_video_id:
        raise ValueError("Oracle output video id does not match requested video")
    if not offsets:
        raise ValueError("Oracle output contains no YouTube live_chat offsets")

    video: dict[str, Any] = {
        "provider": "youtube",
        "vod_id": expected_video_id,
        "vod_url": f"https://www.youtube.com/watch?v={expected_video_id}",
        "title": str(metadata.get("title") or f"YouTube archive {expected_video_id}").strip(),
        "published_at": str(metadata.get("published_at") or "").strip(),
        "thumbnail_url": str(metadata.get("thumbnail_url") or f"https://i.ytimg.com/vi/{expected_video_id}/hqdefault.jpg").strip(),
    }
    duration_sec = _parse_duration(metadata.get("duration_sec"))
    if duration_sec is not None:
        video["duration_sec"] = duration_sec

    comments = []
    for index, offset in enumerate(offsets):
        comment: dict[str, Any] = {"content_offset_seconds": offset}
        if index < len(messages) and messages[index]:
            comment["message"] = messages[index]
        comments.append(comment)
    return YoutubeFetchResult(video=video, chat=ChatFetchResult(comments=comments, duration_sec=duration_sec))


def _collect_oracle_record(record: Any, metadata: dict[str, Any], offsets: list[float]) -> None:
    if isinstance(record, dict):
        record_type = str(record.get("type") or "").strip().lower()
        is_metadata_record = record_type in {"metadata", "video", "info"} or any(
            key in record
            for key in (
                "title",
                "published_at",
                "thumbnail_url",
                "duration_sec",
                "upload_date",
                "thumbnail",
                "duration",
                "id",
            )
        )
        if is_metadata_record:
            candidate_id = record.get("video_id") or record.get("videoId") or record.get("id")
            if candidate_id:
                metadata["video_id"] = str(candidate_id).strip()
            for key in ("title", "published_at", "thumbnail_url", "duration_sec"):
                if key in record and record[key] not in (None, ""):
                    metadata[key] = record[key]
            if record.get("thumbnail") not in (None, "") and not metadata.get("thumbnail_url"):
                metadata["thumbnail_url"] = record["thumbnail"]
            if record.get("duration") not in (None, "") and "duration_sec" not in metadata:
                metadata["duration_sec"] = record["duration"]
            if record.get("upload_date") not in (None, "") and not metadata.get("published_at"):
                metadata["published_at"] = _normalize_upload_date(record["upload_date"])
        if "videoOffsetTimeMsec" in record:
            offset = _parse_offset_seconds(record.get("videoOffsetTimeMsec"))
            if offset is not None:
                offsets.append(offset)
        for child in record.values():
            _collect_oracle_record(child, metadata, offsets)
    elif isinstance(record, list):
        for child in record:
            _collect_oracle_record(child, metadata, offsets)


def _parse_offset_seconds(value: Any) -> float | None:
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(milliseconds) or milliseconds < 0:
        return None
    return milliseconds / 1000.0


def _parse_clock_offset(value: str) -> float | None:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?", value.strip())
    if not match:
        return None
    hours, minutes, seconds = (int(match.group(index)) for index in range(1, 4))
    if minutes >= 60 or seconds >= 60:
        return None
    milliseconds = int((match.group(4) or "0").ljust(3, "0"))
    return float(hours * 3600 + minutes * 60 + seconds) + milliseconds / 1000.0


def _parse_duration(value: Any) -> int | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return int(math.ceil(duration))


def _normalize_upload_date(value: Any) -> str:
    raw = str(value).strip()
    if re.fullmatch(r"\d{8}", raw):
        return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
    return raw
