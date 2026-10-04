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
import locale
import math
import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from update_vods import analyze_video_entry
from vod_sources import ChatFetchResult
from vod_serialization import PUBLIC_VOD_RETENTION_DAYS
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
    def __init__(
        self,
        category: str,
        message: str,
        *,
        stage: str | None = None,
        reason_code: str | None = None,
    ):
        super().__init__(message)
        self.category = category
        self.stage = stage or _default_failure_stage(category)
        self.reason_code = reason_code or f"{category}_failed"


def _default_failure_stage(category: str) -> str:
    if category.startswith("yt_dlp") or category == "temporary_network_failure":
        return "youtube_download"
    if category == "live_chat_zero":
        return "live_chat"
    if category == "highlight_detection_failure":
        return "highlight_detection"
    if category.startswith("handoff_"):
        return "material_handoff"
    if category.startswith("github_dispatch"):
        return "github_dispatch"
    if category.startswith("cookie_") or category.startswith("youtube_"):
        return "youtube_access"
    if category == "public_vod_index_failure":
        return "archive_selection"
    return "oracle_runtime"


DEFAULT_YTDLP = "$HOME/yt-dlp"
DEFAULT_DENO = "$HOME/.local/bin/deno"
DEFAULT_COOKIES = "$HOME/youtube-cookies.txt"
DEFAULT_WORK_ROOT = "$HOME/ytprobe"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAX_STREAM_ARCHIVES_PER_RUN = 5
STREAM_DISCOVERY_DATE_BUFFER_DAYS = 2
MAX_FAILURE_RECORDS = 500
FAILURE_RECORD_RETENTION_DAYS = PUBLIC_VOD_RETENTION_DAYS
CAPTION_RETRY_STATE_VERSION = 1
MAX_CAPTION_RETRY_RECORDS = 500
MAX_CAPTION_RETRY_HISTORY = 500
MAX_CAPTION_RETRIES_PER_RUN = 15
CAPTION_RETRY_DAY_OFFSETS = {1: 1, 2: 3}
CAPTION_RETRY_REASON_CODES = {
    "caption_track_not_found",
    "caption_download_error",
    "caption_download_incomplete",
    "caption_payload_empty_or_invalid",
    "caption_available",
    "legacy_initial_state_unknown",
    "caption_bundle_dispatched",
    "captions_published",
}
CAPTION_SOURCE_OUTCOMES = {
    "not_attempted",
    "track_not_found",
    "download_error",
    "empty_payload",
    "invalid_payload",
    "available",
    "unknown",
}
JST = dt.timezone(dt.timedelta(hours=9))

# Transient YouTube extraction failures (for example "The page needs to be
# reloaded.") come and go within minutes, so the same yt-dlp call is retried
# with a short backoff before the daily job gives up.
YTDLP_TRANSIENT_RETRY_ATTEMPTS = 3
YTDLP_TRANSIENT_RETRY_BACKOFF_SECONDS = 20
TRANSIENT_YTDLP_CATEGORIES = {"temporary_network_failure", "yt_dlp_failure"}
PROCESS_GROUP_TERMINATION_GRACE_SECONDS = 2.0


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _path_env(name: str, default: str) -> str:
    return os.path.expandvars(os.path.expanduser(_env(name, default)))


def _terminate_process_group(process_group_id: int) -> None:
    if os.name != "posix":
        return
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + PROCESS_GROUP_TERMINATION_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_captured_output(stream: Any) -> str:
    stream.flush()
    stream.seek(0)
    return stream.read().decode(locale.getpreferredencoding(False), errors="replace")


def _run_captured(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    if os.name != "posix":
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)

    # File-backed capture lets wait() observe the command even if a child inherits stdout/stderr.
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
        process = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            start_new_session=True,
        )
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_group(process.pid)
            try:
                process.wait(timeout=PROCESS_GROUP_TERMINATION_GRACE_SECONDS + 1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            stdout = _read_captured_output(stdout_file)
            stderr = _read_captured_output(stderr_file)
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from exc
        except BaseException:
            _terminate_process_group(process.pid)
            try:
                process.wait(timeout=PROCESS_GROUP_TERMINATION_GRACE_SECONDS + 1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise

        _terminate_process_group(process.pid)
        return subprocess.CompletedProcess(
            command,
            return_code,
            stdout=_read_captured_output(stdout_file),
            stderr=_read_captured_output(stderr_file),
        )


def _run(command: list[str], *, category: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        completed = _run_captured(command, timeout=timeout)
    except FileNotFoundError as exc:
        raise OracleJobFailure(category, "required runtime was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise OracleJobFailure(category, "runtime timed out") from exc
    if completed.returncode != 0:
        _log_runtime_failure("runtime", completed)
        raise OracleJobFailure(category, "runtime returned a non-zero exit status")
    return completed


def _classify_ytdlp_failure(completed: subprocess.CompletedProcess[str]) -> str:
    text = f"{completed.stdout}\n{completed.stderr}".lower()
    if any(marker in text for marker in ("sign in", "authentication", "cookies", "login", "age-restricted")):
        return "cookie_authentication_failure"
    if any(marker in text for marker in ("members-only", "join this channel")):
        return "youtube_access_failure"
    if any(marker in text for marker in ("not a bot", "captcha", "challenge", "confirm you're not")):
        return "youtube_bot_challenge_failure"
    if "deno" in text or "javascript runtime" in text or "remote-components" in text:
        return "yt_dlp_deno_failure"
    if any(marker in text for marker in ("timed out", "timeout", "connection", "network", "reset by peer")):
        return "temporary_network_failure"
    return "yt_dlp_failure"


def _log_runtime_failure(label: str, completed: subprocess.CompletedProcess[str]) -> None:
    output = str(completed.stderr or "").strip() or str(completed.stdout or "").strip()
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    detail = " | ".join(lines[-3:])
    print(f"{label} failed: exit={completed.returncode} detail={detail[:600]}", flush=True)


def _run_ytdlp(
    command: list[str],
    *,
    timeout: int = 900,
    attempts: int = YTDLP_TRANSIENT_RETRY_ATTEMPTS,
    safe_failure_context: str | None = None,
) -> subprocess.CompletedProcess[str]:
    bounded_attempts = max(1, int(attempts))
    for attempt in range(1, bounded_attempts + 1):
        try:
            completed = _run_captured(command, timeout=timeout)
        except FileNotFoundError as exc:
            raise OracleJobFailure("yt_dlp_deno_failure", "yt-dlp or its runtime was not found") from exc
        except subprocess.TimeoutExpired as exc:
            # A stalled transfer is transient: retry the same command within
            # the remaining attempts before the caller gives up.
            if safe_failure_context:
                print(
                    f"{safe_failure_context} timed out: timeout={timeout}s"
                    f" attempt={attempt}/{bounded_attempts}",
                    flush=True,
                )
            else:
                print(f"yt-dlp timed out: timeout={timeout}s attempt={attempt}/{bounded_attempts}", flush=True)
            if attempt == bounded_attempts:
                raise OracleJobFailure("temporary_network_failure", "yt-dlp timed out") from exc
            time.sleep(YTDLP_TRANSIENT_RETRY_BACKOFF_SECONDS * attempt)
            continue
        if completed.returncode == 0:
            return completed
        category = _classify_ytdlp_failure(completed)
        if safe_failure_context:
            print(
                f"{safe_failure_context} failed: category={category}"
                f" attempt={attempt}/{bounded_attempts}",
                flush=True,
            )
        else:
            _log_runtime_failure("yt-dlp", completed)
        if category not in TRANSIENT_YTDLP_CATEGORIES or attempt == bounded_attempts:
            raise OracleJobFailure(category, "yt-dlp failed")
        time.sleep(YTDLP_TRANSIENT_RETRY_BACKOFF_SECONDS * attempt)
    raise OracleJobFailure("yt_dlp_failure", "yt-dlp failed after retries")


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


def _resolve_stream_archive_records(
    streams_url: str,
    ytdlp: str,
    deno: str,
    cookies: str,
    *,
    now: dt.datetime | None = None,
) -> list[dict[str, str]]:
    now_utc = now or _utc_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=dt.timezone.utc)
    cutoff_date = (
        now_utc.astimezone(dt.timezone.utc)
        - dt.timedelta(days=PUBLIC_VOD_RETENTION_DAYS + STREAM_DISCOVERY_DATE_BUFFER_DAYS)
    ).strftime("%Y%m%d")
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
            "--extractor-args",
            "youtubetab:approximate_date",
            "--dateafter",
            cutoff_date,
            "--print",
            "%(.{id,upload_date,timestamp})j",
            "--quiet",
            "--no-warnings",
            streams_url,
        ],
        timeout=300,
    )
    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for line in completed.stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        try:
            video_id = parse_youtube_video_id(str(record.get("id") or ""))
        except ValueError:
            continue
        if video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        records.append(
            {
                "id": video_id,
                "upload_date": str(record.get("upload_date") or ""),
                "timestamp": str(record.get("timestamp") or ""),
            }
        )
    if completed.stdout.strip() and not records:
        raise OracleJobFailure("yt_dlp_failure", "YouTube streams page returned unreadable archive metadata")
    return records


def _stream_record_times(record: dict[str, Any]) -> tuple[dt.datetime | None, dt.datetime | None, str]:
    """Return archive date, sort time, and a valid timestamp string if present."""
    upload_date = str(record.get("upload_date") or "").strip()
    published_at: dt.datetime | None = None
    if re.fullmatch(r"\d{8}", upload_date):
        try:
            published_at = dt.datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            pass

    timestamp_at: dt.datetime | None = None
    raw_timestamp = str(record.get("timestamp") or "").strip()
    if raw_timestamp:
        try:
            timestamp_at = dt.datetime.fromtimestamp(float(raw_timestamp), tz=dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass

    return published_at or timestamp_at, timestamp_at or published_at, raw_timestamp if timestamp_at else ""


def _select_unpublished_stream_urls(
    records: list[dict[str, str]],
    *,
    published_ids: set[str],
    limit: int,
    now: dt.datetime | None = None,
) -> list[str]:
    bounded_limit = max(1, min(int(limit), MAX_STREAM_ARCHIVES_PER_RUN))
    now_utc = now or _utc_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=dt.timezone.utc)
    now_utc = now_utc.astimezone(dt.timezone.utc)
    cutoff = now_utc - dt.timedelta(days=PUBLIC_VOD_RETENTION_DAYS)
    seen_ids: set[str] = set()
    eligible: list[tuple[dt.datetime, str]] = []
    for record in records:
        video_id = str(record.get("id") or "").strip()
        if not video_id or video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        # Dispatch history does not prove that downstream GitHub publication succeeded.
        if video_id in published_ids:
            continue
        published_at, sort_at, _timestamp = _stream_record_times(record)
        if published_at is None or sort_at is None:
            continue
        if published_at < cutoff or published_at > now_utc:
            continue
        eligible.append((sort_at, video_id))
    eligible.sort(key=lambda item: item[0], reverse=True)
    return [
        f"https://www.youtube.com/watch?v={video_id}"
        for _published_at, video_id in eligible[:bounded_limit]
    ]


def _read_published_video_ids() -> set[str]:
    index_path = REPOSITORY_ROOT / "data" / "vod_index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OracleJobFailure("public_vod_index_failure", "public VOD index is unavailable") from exc
    videos = payload.get("videos") if isinstance(payload, dict) else None
    if not isinstance(videos, list):
        raise OracleJobFailure("public_vod_index_failure", "public VOD index has invalid structure")
    return {
        str(video.get("vod_id") or "").strip()
        for video in videos
        if isinstance(video, dict) and str(video.get("vod_id") or "").strip()
    }


def _state_path() -> Path:
    return Path(_env("YOUTUBE_ORACLE_STATE_PATH", "/var/lib/youtube-highlight/state.json"))


def _read_state() -> dict[str, Any]:
    path = _state_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _merge_discovered_stream_records(
    current_records: list[dict[str, Any]],
    cached_records: list[dict[str, Any]],
    *,
    published_ids: set[str],
    now: dt.datetime | None = None,
) -> list[dict[str, str]]:
    now_utc = now or _utc_now()
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=dt.timezone.utc)
    now_utc = now_utc.astimezone(dt.timezone.utc)
    cutoff = now_utc - dt.timedelta(days=PUBLIC_VOD_RETENTION_DAYS)
    merged: dict[str, tuple[dt.datetime, dict[str, str]]] = {}

    for source_records in (cached_records, current_records):
        for record in source_records:
            if not isinstance(record, dict):
                continue
            try:
                video_id = parse_youtube_video_id(str(record.get("id") or ""))
            except ValueError:
                continue
            if video_id in published_ids:
                continue
            upload_date = str(record.get("upload_date") or "").strip()
            published_at, sort_at, timestamp = _stream_record_times(record)
            if published_at is None or sort_at is None:
                continue
            if published_at < cutoff or published_at > now_utc:
                continue
            if not re.fullmatch(r"\d{8}", upload_date):
                upload_date = published_at.strftime("%Y%m%d")
            existing = merged.get(video_id)
            if existing and not timestamp:
                timestamp = existing[1]["timestamp"]
                if timestamp:
                    sort_at = dt.datetime.fromtimestamp(float(timestamp), tz=dt.timezone.utc)
            normalized = {"id": video_id, "upload_date": upload_date, "timestamp": timestamp}
            merged[video_id] = (sort_at, normalized)

    return [item[1] for item in sorted(merged.values(), key=lambda item: item[0], reverse=True)]


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _record_failure(video_id: str, failure: OracleJobFailure, *, now: dt.datetime | None = None) -> None:
    """Persist a bounded, privacy-safe reason for a failed archive attempt."""

    normalized_id = parse_youtube_video_id(video_id)
    timestamp = now or _utc_now()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    timestamp = timestamp.astimezone(dt.timezone.utc)
    cutoff = timestamp - dt.timedelta(days=FAILURE_RECORD_RETENTION_DAYS)
    record = {
        "video_id": normalized_id,
        "failed_at": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "category": failure.category,
        "stage": failure.stage,
        "reason_code": failure.reason_code,
    }

    state = _read_state()
    old_records = state.get("failure_records")
    retained: list[tuple[dt.datetime, dict[str, str]]] = []
    if isinstance(old_records, list):
        for old_record in old_records:
            if not isinstance(old_record, dict):
                continue
            try:
                old_id = parse_youtube_video_id(str(old_record.get("video_id") or ""))
                old_timestamp = dt.datetime.fromisoformat(
                    str(old_record.get("failed_at") or "").replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                continue
            if old_timestamp.tzinfo is None:
                old_timestamp = old_timestamp.replace(tzinfo=dt.timezone.utc)
            old_timestamp = old_timestamp.astimezone(dt.timezone.utc)
            if old_timestamp < cutoff or old_timestamp > timestamp + dt.timedelta(minutes=5):
                continue
            old_category = str(old_record.get("category") or "")
            old_stage = str(old_record.get("stage") or "")
            old_reason_code = str(old_record.get("reason_code") or "")
            if not all(
                re.fullmatch(r"[a-z0-9_]{1,64}", value)
                for value in (old_category, old_stage, old_reason_code)
            ):
                continue
            retained.append(
                (
                    old_timestamp,
                    {
                        "video_id": old_id,
                        "failed_at": old_timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
                        "category": old_category,
                        "stage": old_stage,
                        "reason_code": old_reason_code,
                    },
                )
            )

    if not all(
        re.fullmatch(r"[a-z0-9_]{1,64}", record[key])
        for key in ("category", "stage", "reason_code")
    ):
        raise OracleJobFailure(
            "state_persistence_failure",
            "failure diagnostic fields were invalid",
            stage="state_write",
            reason_code="invalid_failure_diagnostic",
        )
    retained.append((timestamp, record))
    retained.sort(key=lambda item: item[0])
    state["failure_records"] = [item[1] for item in retained[-MAX_FAILURE_RECORDS:]]
    try:
        _write_state(state)
    except OSError as exc:
        print(
            f"failure diagnostic persistence failed: video_id={normalized_id} category={failure.category}",
            flush=True,
        )
        raise OracleJobFailure(
            "state_persistence_failure",
            "failure diagnostic could not be retained",
            stage="state_write",
            reason_code="failure_record_write_failed",
        ) from exc
    print(
        f"failure video_id={normalized_id} category={failure.category}"
        f" stage={failure.stage} reason={failure.reason_code}",
        flush=True,
    )


def _raise_batch_failure(video_urls: list[str], failure: OracleJobFailure) -> None:
    for video_url in video_urls:
        _record_failure(parse_youtube_video_id(video_url), failure)
    raise failure


def _safe_caption_source_outcomes(outcomes: Any) -> dict[str, str]:
    raw = outcomes if isinstance(outcomes, dict) else {}
    return {
        source: (str(raw.get(source)) if str(raw.get(source)) in CAPTION_SOURCE_OUTCOMES else "unknown")
        for source in ("manual", "automatic")
    }


def _caption_retry_record(
    video_id: str,
    reason_code: str,
    *,
    source_outcomes: Any = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    timestamp = now or _utc_now()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    timestamp = timestamp.astimezone(dt.timezone.utc)
    jst_date = timestamp.astimezone(JST).date().isoformat()
    safe_reason = reason_code if reason_code in CAPTION_RETRY_REASON_CODES else "caption_download_error"
    return {
        "video_id": parse_youtube_video_id(video_id),
        "first_attempt_at": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "first_attempt_date": jst_date,
        "last_attempt_at": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "attempts": 1,
        "last_reason_code": safe_reason,
        "last_source_outcomes": _safe_caption_source_outcomes(source_outcomes),
        "attempt_history": [
            {
                "attempt": 1,
                "attempted_at": timestamp.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "outcome": "unknown" if safe_reason == "legacy_initial_state_unknown" else "missing",
                "reason_code": safe_reason,
                "source_outcomes": _safe_caption_source_outcomes(source_outcomes),
            }
        ],
        "awaiting_publication": False,
    }


def _caption_retry_due(record: dict[str, Any], now: dt.datetime) -> bool:
    if bool(record.get("awaiting_publication")):
        return False
    try:
        attempts = int(record.get("attempts") or 0)
        first_attempt = dt.datetime.fromisoformat(str(record.get("first_attempt_at") or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    day_offset = CAPTION_RETRY_DAY_OFFSETS.get(attempts)
    if day_offset is None:
        return False
    if first_attempt.tzinfo is None:
        first_attempt = first_attempt.replace(tzinfo=dt.timezone.utc)
    current = now if now.tzinfo is not None else now.replace(tzinfo=dt.timezone.utc)
    return current.astimezone(dt.timezone.utc) >= first_attempt.astimezone(dt.timezone.utc) + dt.timedelta(days=day_offset)


def _select_due_caption_retry_urls(
    state: dict[str, Any],
    *,
    published_ids: set[str],
    caption_ids: set[str],
    now: dt.datetime,
) -> list[str]:
    records = state.get("caption_retry_records")
    if not isinstance(records, list):
        return []
    due: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            video_id = parse_youtube_video_id(str(record.get("video_id") or ""))
        except ValueError:
            continue
        if video_id not in published_ids or video_id in caption_ids or not _caption_retry_due(record, now):
            continue
        due.append((str(record.get("first_attempt_date") or "9999-12-31"), video_id))
    due.sort()
    return [
        f"https://www.youtube.com/watch?v={video_id}"
        for _attempt_date, video_id in due[:MAX_CAPTION_RETRIES_PER_RUN]
    ]


def _append_caption_retry_history(state: dict[str, Any], entry: dict[str, Any]) -> None:
    old_history = state.get("caption_retry_history")
    history = [item for item in old_history if isinstance(item, dict)] if isinstance(old_history, list) else []
    history.append(entry)
    state["caption_retry_history"] = history[-MAX_CAPTION_RETRY_HISTORY:]


def _record_caption_retry_failure(
    video_id: str,
    reason_code: str,
    *,
    source_outcomes: Any = None,
    now: dt.datetime | None = None,
) -> str:
    normalized_id = parse_youtube_video_id(video_id)
    timestamp = now or _utc_now()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    timestamp = timestamp.astimezone(dt.timezone.utc)
    timestamp_text = timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")
    safe_reason = reason_code if reason_code in CAPTION_RETRY_REASON_CODES else "caption_download_error"
    state = _read_state()
    records = state.get("caption_retry_records")
    records = [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []
    record = next((item for item in records if item.get("video_id") == normalized_id), None)
    if record is None:
        return "missing_record"
    if bool(record.get("awaiting_publication")):
        record["last_attempt_at"] = timestamp_text
        record["last_reason_code"] = safe_reason
        record["last_source_outcomes"] = _safe_caption_source_outcomes(source_outcomes)
        state["caption_retry_records"] = records
        _write_state(state)
        print(
            f"caption retry video_id={normalized_id} attempt=pending_publication"
            f" outcome=not_published reason={safe_reason}",
            flush=True,
        )
        return "awaiting_publication"

    try:
        attempts = int(record.get("attempts") or 1) + 1
    except (TypeError, ValueError):
        attempts = 2
    record["attempts"] = attempts
    record["last_attempt_at"] = timestamp_text
    record["last_reason_code"] = safe_reason
    record["last_source_outcomes"] = _safe_caption_source_outcomes(source_outcomes)
    attempt_history = record.get("attempt_history")
    attempt_history = [item for item in attempt_history if isinstance(item, dict)] if isinstance(attempt_history, list) else []
    attempt_history.append(
        {
            "attempt": attempts,
            "attempted_at": timestamp_text,
            "outcome": "missing",
            "reason_code": safe_reason,
            "source_outcomes": _safe_caption_source_outcomes(source_outcomes),
        }
    )
    record["attempt_history"] = attempt_history[-3:]
    if attempts >= 3:
        state["caption_retry_records"] = [item for item in records if item is not record]
        _append_caption_retry_history(
            state,
            {
                "video_id": normalized_id,
                "first_attempt_at": str(record.get("first_attempt_at") or timestamp_text),
                "completed_at": timestamp_text,
                "attempts": attempts,
                "outcome": "abandoned",
                "reason_code": safe_reason,
                "source_outcomes": _safe_caption_source_outcomes(source_outcomes),
                "attempt_history": record["attempt_history"],
            },
        )
        outcome = "abandoned"
    else:
        state["caption_retry_records"] = records
        outcome = "retry_scheduled"
    _write_state(state)
    print(
        f"caption retry video_id={normalized_id} attempt={attempts}/3"
        f" outcome={outcome} reason={safe_reason}",
        flush=True,
    )
    return outcome


def _mark_caption_retry_pending_publication(
    video_id: str,
    *,
    source_outcomes: Any = None,
    now: dt.datetime | None = None,
) -> None:
    normalized_id = parse_youtube_video_id(video_id)
    timestamp = now or _utc_now()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
    timestamp_text = timestamp.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    state = _read_state()
    records = state.get("caption_retry_records")
    records = [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []
    record = next((item for item in records if item.get("video_id") == normalized_id), None)
    if record is None:
        return
    try:
        attempts = int(record.get("attempts") or 1) + 1
    except (TypeError, ValueError):
        attempts = 2
    source_results = _safe_caption_source_outcomes(source_outcomes)
    attempt_history = record.get("attempt_history")
    attempt_history = [item for item in attempt_history if isinstance(item, dict)] if isinstance(attempt_history, list) else []
    attempt_history.append(
        {
            "attempt": attempts,
            "attempted_at": timestamp_text,
            "outcome": "caption_available",
            "reason_code": "caption_available",
            "source_outcomes": source_results,
        }
    )
    record["attempts"] = attempts
    record["attempt_history"] = attempt_history[-3:]
    record["awaiting_publication"] = True
    record["last_attempt_at"] = timestamp_text
    record["last_reason_code"] = "caption_bundle_dispatched"
    record["last_source_outcomes"] = source_results
    state["caption_retry_records"] = records
    _write_state(state)
    print(
        f"caption retry video_id={normalized_id} attempt={attempts}/3"
        f" outcome=awaiting_publication reason=caption_bundle_dispatched"
        f" manual={source_results['manual']} automatic={source_results['automatic']}",
        flush=True,
    )


def _read_caption_ids() -> set[str]:
    captions_dir = REPOSITORY_ROOT / "data" / "captions"
    if not captions_dir.is_dir():
        return set()
    return {
        path.stem
        for path in captions_dir.glob("*.json")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", path.stem)
    }


def _seed_caption_retry_records(
    state: dict[str, Any],
    *,
    published_ids: set[str],
    caption_ids: set[str],
    now: dt.datetime,
) -> None:
    if int(state.get("caption_retry_migration_version") or 0) >= CAPTION_RETRY_STATE_VERSION:
        return
    state["caption_retry_records"] = [
        item for item in state.get("caption_retry_records", []) if isinstance(item, dict)
    ] if isinstance(state.get("caption_retry_records"), list) else []
    processed_path = REPOSITORY_ROOT / "data" / "processed_vods.json"
    try:
        payload = json.loads(processed_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return
    videos = payload.get("videos") if isinstance(payload, dict) else None
    if not isinstance(videos, list):
        return
    state["caption_retry_migration_version"] = CAPTION_RETRY_STATE_VERSION
    current_date = now.astimezone(JST).date()
    existing_ids = {str(item.get("video_id") or "") for item in state["caption_retry_records"]}
    for video in videos:
        if not isinstance(video, dict):
            continue
        try:
            video_id = parse_youtube_video_id(str(video.get("vod_id") or ""))
            analyzed_at = dt.datetime.fromisoformat(str(video.get("analyzed_at") or ""))
        except (TypeError, ValueError):
            continue
        if video_id not in published_ids or video_id in caption_ids or video_id in existing_ids:
            continue
        if analyzed_at.tzinfo is None:
            analyzed_at = analyzed_at.replace(tzinfo=dt.timezone.utc)
        attempted_date = analyzed_at.astimezone(JST).date()
        age_days = (current_date - attempted_date).days
        if age_days < 0 or age_days > 3:
            continue
        record = _caption_retry_record(video_id, "legacy_initial_state_unknown", now=analyzed_at)
        state["caption_retry_records"].append(record)
        existing_ids.add(video_id)
        print(
            f"caption retry initialized video_id={video_id} attempt=1/3"
            " reason=legacy_initial_state_unknown",
            flush=True,
        )
    state["caption_retry_records"] = state["caption_retry_records"][-MAX_CAPTION_RETRY_RECORDS:]


def _reconcile_caption_retry_records(
    state: dict[str, Any],
    *,
    published_ids: set[str],
    caption_ids: set[str],
    now: dt.datetime,
) -> None:
    raw_records = state.get("caption_retry_records")
    records = raw_records if isinstance(raw_records, list) else []
    retained: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            video_id = parse_youtube_video_id(str(record.get("video_id") or ""))
            first_attempt = dt.datetime.fromisoformat(str(record.get("first_attempt_at") or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if first_attempt.tzinfo is None:
            first_attempt = first_attempt.replace(tzinfo=dt.timezone.utc)
        age_days = (now.astimezone(JST).date() - first_attempt.astimezone(JST).date()).days
        if video_id not in published_ids or age_days > PUBLIC_VOD_RETENTION_DAYS:
            continue
        if video_id in caption_ids:
            _append_caption_retry_history(
                state,
                {
                    "video_id": video_id,
                    "first_attempt_at": first_attempt.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "completed_at": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "attempts": int(record.get("attempts") or 1),
                    "outcome": "resolved",
                    "reason_code": "captions_published",
                    "attempt_history": record.get("attempt_history", []),
                },
            )
            continue
        retained.append(record)
    state["caption_retry_records"] = retained[-MAX_CAPTION_RETRY_RECORDS:]


def _mark_processed(
    video_id: str,
    *,
    captions_found: bool | None = None,
    caption_reason_code: str | None = None,
    caption_source_outcomes: Any = None,
    now: dt.datetime | None = None,
) -> None:
    state = _read_state()
    processed = [str(item).strip() for item in state.get("processed_video_ids", []) if str(item).strip()]
    processed = [item for item in processed if item != video_id]
    processed.append(video_id)
    state["processed_video_ids"] = processed
    state["last_processed_video_id"] = video_id
    if captions_found is False:
        records = state.get("caption_retry_records")
        records = [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []
        retry_record = _caption_retry_record(
            video_id,
            caption_reason_code or "caption_track_not_found",
            source_outcomes=caption_source_outcomes,
            now=now,
        )
        records = [item for item in records if item.get("video_id") != video_id]
        records.append(retry_record)
        state["caption_retry_records"] = records[-MAX_CAPTION_RETRY_RECORDS:]
        print(
            f"caption acquisition video_id={video_id} result=missing"
            f" reason={retry_record['last_reason_code']} retry=next_day,day_3",
            flush=True,
        )
    elif captions_found is True:
        source_results = _safe_caption_source_outcomes(caption_source_outcomes)
        records = state.get("caption_retry_records")
        records = [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []
        state["caption_retry_records"] = [
            item
            for item in records
            if isinstance(item, dict) and item.get("video_id") != video_id
        ]
        print(
            f"caption acquisition video_id={video_id} result=available"
            f" manual={source_results['manual']} automatic={source_results['automatic']}",
            flush=True,
        )
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
    for attempt in range(1, YTDLP_TRANSIENT_RETRY_ATTEMPTS + 1):
        try:
            _run_ytdlp(
                _yt_dlp_base(ytdlp, deno, cookies)
                + ["--skip-download", "--write-subs", "--sub-langs", "live_chat", "-o", str(stem), video_url],
                attempts=1,
            )
            break
        except OracleJobFailure as exc:
            # Some yt-dlp versions finish writing the live-chat JSON and then
            # return 403 while probing an unrelated video format. Keep the chat
            # artifact only when it exists; the parser below remains authoritative
            # for rejecting empty or malformed output.  When nothing was written,
            # transient extraction failures are retried before the daily job
            # gives up.
            if list(work_dir.glob("*.live_chat.json")):
                break
            if exc.category not in TRANSIENT_YTDLP_CATEGORIES:
                raise
            if attempt == YTDLP_TRANSIENT_RETRY_ATTEMPTS:
                raise
            time.sleep(YTDLP_TRANSIENT_RETRY_BACKOFF_SECONDS * attempt)
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
) -> dict[str, Any]:
    video_id = parse_youtube_video_id(video_url)
    output_template = str(work_dir / "captions.%(ext)s")
    attempts = (
        ("--write-subs", CAPTIONS_SOURCE_MANUAL),
        ("--write-auto-subs", CAPTIONS_SOURCE_AUTOMATIC),
    )
    source_outcomes = {"manual": "not_attempted", "automatic": "not_attempted"}
    download_errors = 0
    empty_payloads = 0
    for write_flag, source in attempts:
        source_key = "manual" if write_flag == "--write-subs" else "automatic"
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
                safe_failure_context=f"youtube_caption_{source_key}",
            )
        except OracleJobFailure:
            source_outcomes[source_key] = "download_error"
            download_errors += 1
            continue
        subtitle_file, language_source = pick_best_json3_file(sorted(work_dir.glob("captions*.json3")))
        if subtitle_file is None:
            source_outcomes[source_key] = "track_not_found"
            continue
        try:
            payload = convert_json3_file(
                video_id=video_id,
                json3_path=subtitle_file,
                language_source=language_source,
                source=source,
            )
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            source_outcomes[source_key] = "invalid_payload"
            empty_payloads += 1
            continue
        if not payload.get("cues"):
            source_outcomes[source_key] = "empty_payload"
            empty_payloads += 1
            continue
        destination = work_dir / "captions.json"
        try:
            write_captions_payload(destination, payload, expected_video_id=video_id)
        except (OSError, ValueError, TypeError):
            source_outcomes[source_key] = "invalid_payload"
            empty_payloads += 1
            continue
        source_outcomes[source_key] = "available"
        return {"path": destination, "reason_code": None, "source_outcomes": source_outcomes}
    if empty_payloads:
        reason_code = "caption_payload_empty_or_invalid"
    elif download_errors == len(attempts):
        reason_code = "caption_download_error"
    elif download_errors:
        reason_code = "caption_download_incomplete"
    else:
        reason_code = "caption_track_not_found"
    print(
        f"caption acquisition video_id={video_id} result=missing"
        f" manual={source_outcomes['manual']} automatic={source_outcomes['automatic']}"
        f" reason={reason_code}",
        flush=True,
    )
    return {"path": None, "reason_code": reason_code, "source_outcomes": source_outcomes}


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
        raise OracleJobFailure(
            "yt_dlp_failure",
            "selected media section was not created",
            stage="media_cut",
            reason_code="media_section_not_created",
        )
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
    caption_result = _download_captions(video_url, work_dir, ytdlp, deno, cookies)
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
        "captions_file": caption_result["path"],
        "caption_reason_code": caption_result["reason_code"],
        "caption_source_outcomes": caption_result["source_outcomes"],
        "chat_total": len(comments),
        "highlights": len(items),
        "media_bytes": sum(path.stat().st_size for path in media_files.values()),
    }


def _run_one(video_url: str) -> dict[str, Any]:
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
            "caption_reason_code": prepared["caption_reason_code"],
            "caption_source_outcomes": prepared["caption_source_outcomes"],
            "media_bytes": prepared["media_bytes"],
        }


def run(video_url: str) -> dict[str, Any]:
    video_id = parse_youtube_video_id(video_url)
    try:
        return _run_one(video_url)
    except OracleJobFailure as exc:
        _record_failure(video_id, exc)
        raise
    except Exception:
        # Preserve the traceback while storing only a non-sensitive reason code.
        failure = OracleJobFailure(
            "oracle_runtime_failure",
            "unexpected processing failure",
            stage="archive_processing",
            reason_code="unexpected_exception",
        )
        _record_failure(video_id, failure)
        raise


def run_batch(video_urls: list[str], *, caption_retry_urls: list[str] | None = None) -> list[dict[str, Any]]:
    """Acquire archives and caption-only retries for one checked Actions run."""

    caption_retry_urls = caption_retry_urls or []
    if not video_urls and not caption_retry_urls:
        raise OracleJobFailure("yt_dlp_failure", "no YouTube archives selected")
    ytdlp = _path_env("YOUTUBE_ORACLE_YTDLP_PATH", DEFAULT_YTDLP)
    deno = _path_env("YOUTUBE_ORACLE_DENO_PATH", DEFAULT_DENO)
    cookies = _path_env("YOUTUBE_ORACLE_COOKIES_PATH", DEFAULT_COOKIES)
    upload_url = _env("YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL")
    if not upload_url:
        _raise_batch_failure(
            video_urls,
            OracleJobFailure("handoff_configuration", "bundle upload PAR is not configured"),
        )
    if not Path(cookies).is_file():
        _raise_batch_failure(
            video_urls,
            OracleJobFailure("cookie_authentication_failure", "YouTube cookies file is missing"),
        )

    work_root = Path(_path_env("YOUTUBE_ORACLE_WORK_ROOT", DEFAULT_WORK_ROOT))
    try:
        work_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        _raise_batch_failure(
            video_urls,
            OracleJobFailure(
                "oracle_runtime_failure",
                "working directory is unavailable",
                stage="batch_setup",
                reason_code="work_root_unavailable",
            ),
        )
    prepared_entries: list[tuple[dict[str, Any], dict[str, Path], Path | None]] = []
    results: list[dict[str, Any]] = []
    caption_updates: list[tuple[str, Path]] = []
    caption_retry_outcomes: dict[str, Any] = {}
    try:
        batch_directory = tempfile.TemporaryDirectory(prefix="batch-", dir=work_root)
    except OSError:
        _raise_batch_failure(
            video_urls,
            OracleJobFailure(
                "oracle_runtime_failure",
                "batch working directory is unavailable",
                stage="batch_setup",
                reason_code="batch_work_dir_unavailable",
            ),
        )
    with batch_directory as temp_dir:
        root = Path(temp_dir)
        for video_url in video_urls:
            video_id = parse_youtube_video_id(video_url)
            try:
                prepared = _prepare_material(video_url, root / video_id, ytdlp, deno, cookies)
            except OracleJobFailure as exc:
                # One bad archive must not block the rest of the daily batch.
                # The skipped video stays unprocessed and the next timer run
                # retries it.
                _record_failure(video_id, exc)
                print(
                    f"skipped video_id={video_id} category={exc.category}"
                    f" stage={exc.stage} reason={exc.reason_code}",
                    flush=True,
                )
                continue
            except Exception:
                # Keep unexpected exceptions fatal after persisting a safe marker.
                failure = OracleJobFailure(
                    "oracle_runtime_failure",
                    "unexpected processing failure",
                    stage="archive_processing",
                    reason_code="unexpected_exception",
                )
                _record_failure(video_id, failure)
                raise
            prepared_entries.append((prepared["manifest"], prepared["media_files"], prepared["captions_file"]))
            results.append(
                {
                    "video_id": video_id,
                    "chat_total": prepared["chat_total"],
                    "highlights": prepared["highlights"],
                    "captions": bool(prepared["captions_file"]),
                    "caption_reason_code": prepared.get("caption_reason_code"),
                    "caption_source_outcomes": prepared.get("caption_source_outcomes"),
                    "media_bytes": prepared["media_bytes"],
                }
            )
        for video_url in caption_retry_urls:
            video_id = parse_youtube_video_id(video_url)
            caption_dir = root / "caption-retries" / video_id
            caption_dir.mkdir(parents=True, exist_ok=True)
            try:
                caption_result = _download_captions(video_url, caption_dir, ytdlp, deno, cookies)
            except OracleJobFailure:
                caption_result = {
                    "path": None,
                    "reason_code": "caption_download_error",
                    "source_outcomes": {"manual": "download_error", "automatic": "download_error"},
                }
            if caption_result.get("path") is None:
                _record_caption_retry_failure(
                    video_id,
                    str(caption_result.get("reason_code") or "caption_download_error"),
                    source_outcomes=caption_result.get("source_outcomes"),
                )
                continue
            caption_updates.append((video_id, caption_result["path"]))
            caption_retry_outcomes[video_id] = caption_result.get("source_outcomes")

        if not results and not caption_updates:
            if video_urls:
                raise OracleJobFailure("yt_dlp_failure", "no YouTube archives could be prepared")
            return []
        try:
            bundle_path = root / "youtube-material-batch.tar.gz"
            create_material_batch_bundle(bundle_path, prepared_entries, caption_updates=caption_updates)
            upload_bundle_to_url(bundle_path, upload_url)
            dispatched_ids = list(dict.fromkeys(
                [item["video_id"] for item in results]
                + [video_id for video_id, _caption_path in caption_updates]
            ))
            _dispatch_github(dispatched_ids)
            for video_id, _caption_path in caption_updates:
                _mark_caption_retry_pending_publication(
                    video_id,
                    source_outcomes=caption_retry_outcomes.get(video_id),
                )
        except OracleJobFailure as exc:
            for result in results:
                _record_failure(result["video_id"], exc)
            raise
        except (OSError, error.URLError, TimeoutError, RuntimeError) as exc:
            failure = OracleJobFailure("handoff_upload_failure", "temporary material upload failed")
            for result in results:
                _record_failure(result["video_id"], failure)
            raise failure from exc
        except Exception as exc:
            failure = OracleJobFailure(
                "oracle_runtime_failure",
                "unexpected batch handoff failure",
                stage="batch_handoff",
                reason_code="unexpected_batch_handoff_failure",
            )
            for result in results:
                _record_failure(result["video_id"], failure)
            raise failure from exc
        if video_urls and not results:
            raise OracleJobFailure("yt_dlp_failure", "no YouTube archives could be prepared")
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
        caption_retry_urls: list[str] = []
        if args.streams_url:
            if not Path(cookies).is_file():
                raise OracleJobFailure("cookie_authentication_failure", "YouTube cookies file is missing")
            run_started_at = _utc_now()
            state = _read_state()
            cached_records = state.get("discovered_stream_records")
            if not isinstance(cached_records, list):
                cached_records = []
            published_ids = _read_published_video_ids()
            caption_ids = _read_caption_ids()
            _seed_caption_retry_records(
                state,
                published_ids=published_ids,
                caption_ids=caption_ids,
                now=run_started_at,
            )
            _reconcile_caption_retry_records(
                state,
                published_ids=published_ids,
                caption_ids=caption_ids,
                now=run_started_at,
            )
            current_records = _resolve_stream_archive_records(
                args.streams_url,
                ytdlp,
                deno,
                cookies,
                now=run_started_at,
            )
            records = _merge_discovered_stream_records(
                current_records,
                cached_records,
                published_ids=published_ids,
                now=run_started_at,
            )
            state["discovered_stream_records"] = records
            video_urls = _select_unpublished_stream_urls(
                records,
                published_ids=published_ids,
                limit=args.max_videos,
                now=run_started_at,
            )
            caption_retry_urls = _select_due_caption_retry_urls(
                state,
                published_ids=published_ids,
                caption_ids=caption_ids,
                now=run_started_at,
            )
            _write_state(state)
            if not video_urls and not caption_retry_urls:
                _notify(None)
                print("oracle YouTube job skipped: reason=no_recent_unprocessed_archives")
                return 0
            for video_url in video_urls:
                print(f"selected video_id={parse_youtube_video_id(video_url)}", flush=True)
            for video_url in caption_retry_urls:
                print(f"selected caption_retry video_id={parse_youtube_video_id(video_url)}", flush=True)
        else:
            video_urls = [args.video_url] if args.video_url else []
            if video_urls:
                video_id = parse_youtube_video_id(video_urls[0])
                print(f"selected video_id={video_id}", flush=True)
                if video_id in _read_published_video_ids():
                    if video_id in _read_caption_ids():
                        _notify(None)
                        print(f"skipped video_id={video_id} category=already_published", flush=True)
                        return 0
                    # A published VOD without captions is not reprocessed, but
                    # an explicit request refreshes only its captions now.
                    caption_retry_urls = video_urls
                    video_urls = []
                    print(f"selected caption_retry video_id={video_id}", flush=True)
        if not video_urls and not caption_retry_urls:
            raise OracleJobFailure("handoff_configuration", "YOUTUBE_ORACLE_STREAMS_URL or video URL is required")
        if len(video_urls) == 1 and not caption_retry_urls:
            results = [run(video_urls[0])]
        elif caption_retry_urls:
            results = run_batch(video_urls, caption_retry_urls=caption_retry_urls)
        else:
            results = run_batch(video_urls)
        for result in results:
            if "caption_reason_code" in result or "caption_source_outcomes" in result:
                _mark_processed(
                    result["video_id"],
                    captions_found=bool(result.get("captions")),
                    caption_reason_code=result.get("caption_reason_code"),
                    caption_source_outcomes=result.get("caption_source_outcomes"),
                )
            else:
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
