"""Oracle-side YouTube acquisition and OCI PAR handoff.

Run this on the dedicated Oracle VM.  It performs the only YouTube network
access, detects the same chat-z-score highlights as the repository pipeline,
cuts only those intervals, and uploads a short-lived OCI Object Storage PAR
object.  Whisper is intentionally not run on the small Oracle VM.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib import error, request

from update_vods import analyze_video_entry
from vod_sources import ChatFetchResult
from youtube_handoff import (
    build_material_manifest,
    create_material_batch_bundle,
    create_material_bundle,
    upload_bundle_to_url,
)
from youtube_captions import (
    CAPTIONS_SOURCE_AUTOMATIC,
    CAPTIONS_SOURCE_MANUAL,
    convert_json3_file,
    pick_best_json3_file,
    write_captions_payload,
)
from youtube_sources import parse_youtube_video_id


class OracleJobFailure(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


DEFAULT_YTDLP = "$HOME/yt-dlp"
DEFAULT_DENO = "$HOME/.local/bin/deno"
DEFAULT_COOKIES = "$HOME/youtube-cookies.txt"
DEFAULT_WORK_ROOT = "$HOME/ytprobe"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _path_env(name: str, default: str) -> str:
    return os.path.expandvars(os.path.expanduser(_env(name, default)))


def _run(command: list[str], *, category: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise OracleJobFailure(category, "required runtime was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise OracleJobFailure(category, "runtime timed out") from exc
    if completed.returncode != 0:
        raise OracleJobFailure(category, "runtime returned a non-zero exit status")
    return completed


def _classify_ytdlp_failure(completed: subprocess.CompletedProcess[str]) -> str:
    text = f"{completed.stdout}\n{completed.stderr}".lower()
    if any(marker in text for marker in ("sign in", "authentication", "cookies", "login", "age-restricted")):
        return "cookie_authentication_failure"
    if any(marker in text for marker in ("not a bot", "captcha", "challenge", "confirm you're not")):
        return "youtube_bot_challenge_failure"
    if "deno" in text or "javascript runtime" in text or "remote-components" in text:
        return "yt_dlp_deno_failure"
    if any(marker in text for marker in ("timed out", "timeout", "connection", "network", "reset by peer")):
        return "temporary_network_failure"
    return "yt_dlp_failure"


def _run_ytdlp(command: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise OracleJobFailure("yt_dlp_deno_failure", "yt-dlp or its runtime was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise OracleJobFailure("temporary_network_failure", "yt-dlp timed out") from exc
    if completed.returncode != 0:
        raise OracleJobFailure(_classify_ytdlp_failure(completed), "yt-dlp failed")
    return completed


def _yt_dlp_base(ytdlp: str, deno: str, cookies: str) -> list[str]:
    return [
        ytdlp,
        "--js-runtimes",
        f"deno:{deno}",
        "--remote-components",
        "ejs:github",
        "--cookies",
        cookies,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
    ]


def _resolve_stream_urls(streams_url: str, ytdlp: str, deno: str, cookies: str, *, limit: int) -> list[str]:
    bounded_limit = max(1, min(int(limit), 8))
    completed = _run_ytdlp(
        [
            ytdlp,
            "--js-runtimes",
            f"deno:{deno}",
            "--remote-components",
            "ejs:github",
            "--cookies",
            cookies,
            "--flat-playlist",
            "--playlist-end",
            str(bounded_limit),
            "--print",
            "%(id)s",
            "--quiet",
            "--no-warnings",
            streams_url,
        ],
        timeout=120,
    )
    urls: list[str] = []
    seen_ids: set[str] = set()
    for line in completed.stdout.splitlines():
        candidate = line.strip()
        try:
            video_id = parse_youtube_video_id(candidate)
        except ValueError:
            continue
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        urls.append(f"https://www.youtube.com/watch?v={video_id}")
        if len(urls) >= bounded_limit:
            break
    if not urls:
        raise OracleJobFailure("yt_dlp_failure", "YouTube streams page returned no archive")
    return urls


def _resolve_latest_stream_url(streams_url: str, ytdlp: str, deno: str, cookies: str) -> str:
    return _resolve_stream_urls(streams_url, ytdlp, deno, cookies, limit=1)[0]


def _state_path() -> Path:
    return Path(_env("YOUTUBE_ORACLE_STATE_PATH", "/var/lib/youtube-highlight/state.json"))


def _read_state() -> dict[str, Any]:
    path = _state_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _mark_processed(video_id: str) -> None:
    state = _read_state()
    processed = [str(item).strip() for item in state.get("processed_video_ids", []) if str(item).strip()]
    processed = [item for item in processed if item != video_id]
    processed.append(video_id)
    state["processed_video_ids"] = processed[-30:]
    state["last_processed_video_id"] = video_id
    _write_state(state)


def _find_offset(value: Any) -> int | None:
    if isinstance(value, dict):
        if "videoOffsetTimeMsec" in value:
            try:
                offset = int(value["videoOffsetTimeMsec"])
            except (TypeError, ValueError):
                return None
            return offset if offset >= 0 else None
        for child in value.values():
            result = _find_offset(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_offset(child)
            if result is not None:
                return result
    return None


def _find_renderer(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        renderer = value.get("liveChatTextMessageRenderer")
        if isinstance(renderer, dict):
            return renderer
        for child in value.values():
            result = _find_renderer(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_renderer(child)
            if result is not None:
                return result
    return None


def _renderer_text(renderer: dict[str, Any] | None) -> str:
    if not renderer:
        return ""
    message = renderer.get("message")
    if not isinstance(message, dict):
        return ""
    simple = message.get("simpleText")
    if simple:
        return str(simple).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    runs = message.get("runs") or []
    return "".join(str(run.get("text") or "") for run in runs if isinstance(run, dict)).strip()


def _read_live_chat(path: Path) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for raw_line in source:
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            offset_ms = _find_offset(record)
            if offset_ms is None:
                continue
            comment: dict[str, Any] = {"content_offset_seconds": offset_ms / 1000.0}
            text = _renderer_text(_find_renderer(record))
            if text:
                # This text exists in memory only for the detector/tag rules.
                comment["message"] = text
            comments.append(comment)
    return comments


def _metadata(completed: subprocess.CompletedProcess[str], video_id: str, video_url: str) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for line in completed.stdout.splitlines():
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            record = candidate
            break
    upload_date = str(record.get("upload_date") or "").strip()
    published_at = ""
    if re.fullmatch(r"\d{8}", upload_date):
        published_at = dt.datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=dt.timezone.utc).isoformat()
    else:
        published_at = upload_date
    duration = record.get("duration")
    try:
        duration_sec = int(math.ceil(float(duration))) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_sec = None
    video = {
        "provider": "youtube",
        "vod_id": video_id,
        "vod_url": video_url,
        "title": str(record.get("title") or f"YouTube archive {video_id}").strip(),
        "published_at": published_at,
        "thumbnail_url": str(record.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg").strip(),
    }
    if duration_sec and duration_sec > 0:
        video["duration_sec"] = duration_sec
    return video


def _download_chat_and_metadata(video_url: str, work_dir: Path, ytdlp: str, deno: str, cookies: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    video_id = parse_youtube_video_id(video_url)
    stem = work_dir / "archive"
    try:
        _run_ytdlp(
            _yt_dlp_base(ytdlp, deno, cookies)
            + ["--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", str(stem), video_url]
        )
    except OracleJobFailure as exc:
        # Some yt-dlp versions finish writing the live-chat JSON and then
        # return 403 while probing an unrelated video format. Keep the chat
        # artifact only when it exists; the parser below remains authoritative
        # for rejecting empty or malformed output.
        if exc.category != "yt_dlp_failure":
            raise
    chat_files = list(work_dir.glob("*.live_chat.json"))
    if not chat_files:
        raise OracleJobFailure("live_chat_zero", "yt-dlp returned no live chat file")
    comments = _read_live_chat(chat_files[0])
    for path in chat_files:
        path.unlink(missing_ok=True)
    if not comments:
        raise OracleJobFailure("live_chat_zero", "live chat contained no usable offsets")

    metadata_result = _run_ytdlp(
        _yt_dlp_base(ytdlp, deno, cookies)
        + ["--skip-download", "--print", "%(.{id,title,upload_date,duration,thumbnail})j", video_url]
    )
    return _metadata(metadata_result, video_id, video_url), comments


def _download_captions(
    video_url: str,
    work_dir: Path,
    ytdlp: str,
    deno: str,
    cookies: str,
) -> Path | None:
    video_id = parse_youtube_video_id(video_url)
    output_template = str(work_dir / "captions.%(ext)s")
    attempts = (
        ("--write-subs", CAPTIONS_SOURCE_MANUAL),
        ("--write-auto-subs", CAPTIONS_SOURCE_AUTOMATIC),
    )
    for write_flag, source in attempts:
        for stale in work_dir.glob("captions*.json3"):
            stale.unlink(missing_ok=True)
        try:
            _run_ytdlp(
                _yt_dlp_base(ytdlp, deno, cookies)
                + [
                    "--skip-download",
                    "--ignore-no-formats",
                    write_flag,
                    "--sub-langs",
                    "ja-orig,ja,ja-JP",
                    "--sub-format",
                    "json3",
                    "-o",
                    output_template,
                    video_url,
                ],
                timeout=180,
            )
        except OracleJobFailure:
            continue
        subtitle_file, language_source = pick_best_json3_file(sorted(work_dir.glob("captions*.json3")))
        if subtitle_file is None:
            continue
        payload = convert_json3_file(
            video_id=video_id,
            json3_path=subtitle_file,
            language_source=language_source,
            source=source,
        )
        if not payload.get("cues"):
            continue
        destination = work_dir / "captions.json"
        write_captions_payload(destination, payload, expected_video_id=video_id)
        return destination
    return None


def _cut_media(video_url: str, item: dict[str, Any], index: int, work_dir: Path, ytdlp: str, deno: str, cookies: str) -> tuple[Path, Path]:
    start = int(item["start_sec"])
    end = int(item["end_sec"])
    source_prefix = work_dir / f"source-{index}"
    _run_ytdlp(
        _yt_dlp_base(ytdlp, deno, cookies)
        + [
            "--download-sections",
            f"*{start}-{end}",
            "--force-keyframes-at-cuts",
            "-f",
            "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
            "--merge-output-format",
            "mp4",
            "-o",
            f"{source_prefix}.%(ext)s",
            video_url,
        ],
        timeout=1200,
    )
    sources = [path for path in work_dir.glob(f"{source_prefix.name}.*") if path.suffix not in {".part", ".ytdl"}]
    if not sources:
        raise OracleJobFailure("yt_dlp_failure", "selected media section was not created")
    source = max(sources, key=lambda path: path.stat().st_size)
    audio = work_dir / f"clip-{index}.wav"
    screenshot = work_dir / f"clip-{index}.webp"
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(audio),
        ],
        category="oracle_runtime_failure",
    )
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "1",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=192:108:force_original_aspect_ratio=decrease,pad=192:108:(ow-iw)/2:(oh-ih)/2",
            "-c:v",
            "libwebp",
            "-quality",
            "75",
            str(screenshot),
        ],
        category="oracle_runtime_failure",
    )
    if audio.stat().st_size <= 0 or screenshot.stat().st_size <= 0:
        raise OracleJobFailure("oracle_runtime_failure", "selected media output was empty")
    source.unlink(missing_ok=True)
    return audio, screenshot


def _dispatch_github(video_ids: list[str]) -> None:
    token = _env("YOUTUBE_ORACLE_GITHUB_TOKEN")
    repository = _env("YOUTUBE_ORACLE_GITHUB_REPOSITORY")
    if not token or not repository:
        raise OracleJobFailure("github_dispatch_configuration", "GitHub dispatch configuration is missing")
    url = f"https://api.github.com/repos/{repository}/dispatches"
    payload = json.dumps(
        {
            "event_type": "youtube-material-ready",
            "client_payload": {"video_id": video_ids[0], "video_ids": video_ids},
        }
    ).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with request.urlopen(req, timeout=60) as response:
            if int(getattr(response, "status", 200)) >= 300:
                raise OracleJobFailure("github_dispatch_failure", "GitHub dispatch failed")
    except (error.URLError, TimeoutError) as exc:
        raise OracleJobFailure("github_dispatch_failure", "GitHub dispatch failed") from exc


def _notify(category: str | None) -> None:
    webhook = _env("DISCORD_WEBHOOK_URL")
    state = _read_state()
    previous = str(state.get("failure_category") or "")
    if category:
        should_send = bool(webhook) and (previous != category or not bool(state.get("failure_notified")))
        if should_send:
            _send_discord(webhook, f"YouTube取得に失敗しました\ncategory: {category}\nprovider: youtube")
        state["failure_category"] = category
        state["failure_notified"] = bool(webhook)
    elif previous:
        if webhook:
            _send_discord(webhook, "YouTube取得が復旧しました\nprovider: youtube")
        state["failure_category"] = ""
        state["failure_notified"] = False
    _write_state(state)


def _send_discord(webhook: str, content: str) -> None:
    req = request.Request(
        webhook,
        data=json.dumps({"content": content}, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=30):
            pass
    except (error.URLError, TimeoutError):
        pass


def _prepare_material(
    video_url: str,
    work_dir: Path,
    ytdlp: str,
    deno: str,
    cookies: str,
) -> dict[str, Any]:
    video_id = parse_youtube_video_id(video_url)
    work_dir.mkdir(parents=True, exist_ok=True)
    video, comments = _download_chat_and_metadata(video_url, work_dir, ytdlp, deno, cookies)
    captions_file = _download_captions(video_url, work_dir, ytdlp, deno, cookies)
    analyzed, status = analyze_video_entry(
        video,
        dt.datetime.now().astimezone(),
        chat_data_override=ChatFetchResult(comments=comments, duration_sec=video.get("duration_sec")),
        metadata_override=video,
    )
    if not analyzed or status != "analyzed":
        raise OracleJobFailure("highlight_detection_failure", "chat offsets produced no highlights")
    items = list(analyzed.get("items") or [])
    media_files: dict[str, Path] = {}
    for index, item in enumerate(items):
        audio, screenshot = _cut_media(video_url, item, index, work_dir, ytdlp, deno, cookies)
        media_files[f"clips/clip-{index}.wav"] = audio
        media_files[f"clips/clip-{index}.webp"] = screenshot
    return {
        "video_id": video_id,
        "manifest": build_material_manifest(video, comments, items),
        "media_files": media_files,
        "captions_file": captions_file,
        "chat_total": len(comments),
        "highlights": len(items),
        "media_bytes": sum(path.stat().st_size for path in media_files.values()),
    }


def run(video_url: str) -> dict[str, Any]:
    ytdlp = _path_env("YOUTUBE_ORACLE_YTDLP_PATH", DEFAULT_YTDLP)
    deno = _path_env("YOUTUBE_ORACLE_DENO_PATH", DEFAULT_DENO)
    cookies = _path_env("YOUTUBE_ORACLE_COOKIES_PATH", DEFAULT_COOKIES)
    upload_url = _env("YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL")
    if not upload_url:
        raise OracleJobFailure("handoff_configuration", "bundle upload PAR is not configured")
    if not Path(cookies).is_file():
        raise OracleJobFailure("cookie_authentication_failure", "YouTube cookies file is missing")

    work_root = Path(_path_env("YOUTUBE_ORACLE_WORK_ROOT", DEFAULT_WORK_ROOT))
    work_root.mkdir(parents=True, exist_ok=True)
    video_id = parse_youtube_video_id(video_url)
    with tempfile.TemporaryDirectory(prefix=f"job-{video_id}-", dir=work_root) as temp_dir:
        work_dir = Path(temp_dir)
        prepared = _prepare_material(video_url, work_dir, ytdlp, deno, cookies)
        bundle_path = work_dir / f"youtube-material-{video_id}.tar.gz"
        create_material_bundle(
            bundle_path,
            prepared["manifest"],
            prepared["media_files"],
            captions_file=prepared["captions_file"],
        )
        try:
            upload_bundle_to_url(bundle_path, upload_url)
        except (OSError, error.URLError, TimeoutError, RuntimeError) as exc:
            raise OracleJobFailure("handoff_upload_failure", "temporary material upload failed") from exc
        _dispatch_github([video_id])
        return {
            "video_id": video_id,
            "chat_total": prepared["chat_total"],
            "highlights": prepared["highlights"],
            "captions": bool(prepared["captions_file"]),
            "media_bytes": prepared["media_bytes"],
        }


def run_batch(video_urls: list[str]) -> list[dict[str, Any]]:
    """Acquire several archives and hand them to one checked Actions run."""

    if not video_urls:
        raise OracleJobFailure("yt_dlp_failure", "no YouTube archives selected")
    ytdlp = _path_env("YOUTUBE_ORACLE_YTDLP_PATH", DEFAULT_YTDLP)
    deno = _path_env("YOUTUBE_ORACLE_DENO_PATH", DEFAULT_DENO)
    cookies = _path_env("YOUTUBE_ORACLE_COOKIES_PATH", DEFAULT_COOKIES)
    upload_url = _env("YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL")
    if not upload_url:
        raise OracleJobFailure("handoff_configuration", "bundle upload PAR is not configured")
    if not Path(cookies).is_file():
        raise OracleJobFailure("cookie_authentication_failure", "YouTube cookies file is missing")

    work_root = Path(_path_env("YOUTUBE_ORACLE_WORK_ROOT", DEFAULT_WORK_ROOT))
    work_root.mkdir(parents=True, exist_ok=True)
    prepared_entries: list[tuple[dict[str, Any], dict[str, Path], Path | None]] = []
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="batch-", dir=work_root) as temp_dir:
        root = Path(temp_dir)
        for video_url in video_urls:
            video_id = parse_youtube_video_id(video_url)
            prepared = _prepare_material(video_url, root / video_id, ytdlp, deno, cookies)
            prepared_entries.append((prepared["manifest"], prepared["media_files"], prepared["captions_file"]))
            results.append(
                {
                    "video_id": video_id,
                    "chat_total": prepared["chat_total"],
                    "highlights": prepared["highlights"],
                    "captions": bool(prepared["captions_file"]),
                    "media_bytes": prepared["media_bytes"],
                }
            )
        bundle_path = root / "youtube-material-batch.tar.gz"
        create_material_batch_bundle(bundle_path, prepared_entries)
        try:
            upload_bundle_to_url(bundle_path, upload_url)
        except (OSError, error.URLError, TimeoutError, RuntimeError) as exc:
            raise OracleJobFailure("handoff_upload_failure", "temporary material upload failed") from exc
        _dispatch_github([item["video_id"] for item in results])
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire YouTube archives on Oracle and hand off selected material.")
    parser.add_argument("--streams-url", default=_env("YOUTUBE_ORACLE_STREAMS_URL"))
    parser.add_argument("--video-url", default=_env("YOUTUBE_ORACLE_VIDEO_URL"))
    parser.add_argument("--max-videos", type=int, default=int(_env("YOUTUBE_ORACLE_MAX_VIDEOS", "5")))
    args = parser.parse_args()
    try:
        ytdlp = _path_env("YOUTUBE_ORACLE_YTDLP_PATH", DEFAULT_YTDLP)
        deno = _path_env("YOUTUBE_ORACLE_DENO_PATH", DEFAULT_DENO)
        cookies = _path_env("YOUTUBE_ORACLE_COOKIES_PATH", DEFAULT_COOKIES)
        if args.streams_url:
            if not Path(cookies).is_file():
                raise OracleJobFailure("cookie_authentication_failure", "YouTube cookies file is missing")
            video_urls = _resolve_stream_urls(
                args.streams_url,
                ytdlp,
                deno,
                cookies,
                limit=args.max_videos,
            )
            processed_ids = {
                str(item).strip()
                for item in _read_state().get("processed_video_ids", [])
                if str(item).strip()
            }
            if not processed_ids:
                previous = str(_read_state().get("last_processed_video_id") or "").strip()
                if previous:
                    processed_ids.add(previous)
            video_urls = [
                url for url in video_urls if parse_youtube_video_id(url) not in processed_ids
            ]
            if not video_urls:
                _notify(None)
                print("oracle YouTube job skipped: reason=all_selected_archives_already_processed")
                return 0
        else:
            video_urls = [args.video_url] if args.video_url else []
        if not video_urls:
            raise OracleJobFailure("handoff_configuration", "YOUTUBE_ORACLE_STREAMS_URL or video URL is required")
        results = run(video_urls[0]) if len(video_urls) == 1 else run_batch(video_urls)
        for result in results:
            _mark_processed(result["video_id"])
        _notify(None)
        print(f"oracle YouTube job complete: videos={len(results)}")
        for result in results:
            print(
                f" video_id={result['video_id']}"
                f" chat_offsets={result['chat_total']}"
                f" highlights={result['highlights']}"
                f" captions={'yes' if result['captions'] else 'no'}"
                f" media_bytes={result['media_bytes']}"
            )
        return 0
    except OracleJobFailure as exc:
        _notify(exc.category)
        print(f"oracle YouTube job failed: category={exc.category}")
        return 1
    except Exception:
        _notify("oracle_runtime_failure")
        print("oracle YouTube job failed: category=oracle_runtime_failure")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
