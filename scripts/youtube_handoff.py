"""Safe handoff contract for Oracle-selected YouTube material.

The bundle deliberately contains only publishable metadata, comment offsets,
and the selected media clips.  Raw chat, user identity, and transcription
artifacts are rejected before a bundle is written or extracted.
"""

from __future__ import annotations

import json
import math
import re
import tarfile
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib import request


MATERIAL_BUNDLE_VERSION = 1
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CLIP_MEMBER_RE = re.compile(r"^clips/clip-(\d+)\.(wav|webp)$")
_SAFE_MEMBER_RE = re.compile(r"^(manifest\.json|captions\.json|clips/clip-\d+\.(wav|webp))$")
_BATCH_MEMBER_RE = re.compile(r"^(batch\.json|videos/[A-Za-z0-9_-]{11}/(?:captions\.json|clips/clip-\d+\.(?:wav|webp)))$")
_FORBIDDEN_KEYS = {
    "author",
    "author_name",
    "chat",
    "comment",
    "comments",
    "message",
    "messages",
    "raw_chat",
    "timestamp",
    "transcript",
    "transcripts",
    "username",
    "user_name",
}


def _finite_nonnegative(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def _safe_key(key: Any) -> str:
    value = str(key or "").strip().lower()
    if value in _FORBIDDEN_KEYS or any(part in value for part in ("transcript", "raw_chat", "username")):
        raise ValueError(f"material manifest contains forbidden field: {value}")
    return value


def _assert_no_private_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _safe_key(key)
            _assert_no_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_private_fields(child)


def _safe_video(video: Mapping[str, Any]) -> dict[str, Any]:
    video_id = str(video.get("vod_id") or "").strip()
    if not _VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("material manifest requires a valid YouTube video id")
    provider = str(video.get("provider") or "youtube").strip().lower()
    if provider != "youtube":
        raise ValueError("material manifest provider must be youtube")
    return {
        "provider": "youtube",
        "vod_id": video_id,
        "vod_url": str(video.get("vod_url") or f"https://www.youtube.com/watch?v={video_id}").strip(),
        "title": str(video.get("title") or "").strip(),
        "published_at": str(video.get("published_at") or "").strip(),
        "thumbnail_url": str(video.get("thumbnail_url") or "").strip(),
        "duration_sec": int(_finite_nonnegative(video["duration_sec"], "video.duration_sec"))
        if video.get("duration_sec") not in (None, "")
        else None,
    }


def _safe_highlight(item: Mapping[str, Any], index: int) -> dict[str, Any]:
    item_id = str(item.get("id") or "").strip()
    if not item_id:
        raise ValueError(f"highlight {index} has no id")
    start = int(_finite_nonnegative(item.get("start_sec"), f"highlight[{index}].start_sec"))
    end = int(_finite_nonnegative(item.get("end_sec"), f"highlight[{index}].end_sec"))
    if end <= start:
        raise ValueError(f"highlight {index} has an invalid interval")
    return {
        "index": index,
        "id": item_id,
        "rank": int(item.get("rank") or index + 1),
        "start_sec": start,
        "end_sec": end,
        "duration_sec": end - start,
    }


def build_material_manifest(
    video: Mapping[str, Any],
    comments: Iterable[Mapping[str, Any]],
    items: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a privacy-safe manifest from in-memory Oracle processing data."""

    safe_comments: list[dict[str, float]] = []
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        if "content_offset_seconds" not in comment:
            continue
        safe_comments.append(
            {"content_offset_seconds": _finite_nonnegative(comment["content_offset_seconds"], "chat offset")}
        )
    if not safe_comments:
        raise ValueError("material manifest requires at least one chat offset")

    safe_items = [_safe_highlight(item, index) for index, item in enumerate(items)]
    if not safe_items:
        raise ValueError("material manifest requires at least one highlight")
    if len(safe_items) > 8:
        raise ValueError("material manifest contains too many highlights")

    manifest = {
        "schema_version": MATERIAL_BUNDLE_VERSION,
        "video": _safe_video(video),
        "chat_offsets": safe_comments,
        "selected_highlights": safe_items,
        "media": [
            {
                "index": item["index"],
                "item_id": item["id"],
                "audio_path": f"clips/clip-{item['index']}.wav",
                "screenshot_path": f"clips/clip-{item['index']}.webp",
                "start_sec": item["start_sec"],
                "end_sec": item["end_sec"],
            }
            for item in safe_items
        ],
    }
    _assert_no_private_fields(manifest)
    return manifest


def validate_material_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping) or int(manifest.get("schema_version") or 0) != MATERIAL_BUNDLE_VERSION:
        raise ValueError("unsupported YouTube material bundle schema")
    _assert_no_private_fields(manifest)
    video = manifest.get("video")
    offsets = manifest.get("chat_offsets")
    selected = manifest.get("selected_highlights")
    media = manifest.get("media")
    if not isinstance(video, Mapping) or not isinstance(offsets, list) or not isinstance(selected, list) or not isinstance(media, list):
        raise ValueError("material manifest has an invalid shape")
    safe_video = _safe_video(video)
    if not offsets:
        raise ValueError("material manifest has no chat offsets")
    safe_offsets = [
        {"content_offset_seconds": _finite_nonnegative(item.get("content_offset_seconds"), "chat offset")}
        for item in offsets
        if isinstance(item, Mapping)
    ]
    if len(safe_offsets) != len(offsets):
        raise ValueError("material manifest contains an invalid chat offset")
    safe_items = [_safe_highlight(item, index) for index, item in enumerate(selected)]
    if len(media) != len(safe_items):
        raise ValueError("material manifest media count does not match highlights")
    safe_media: list[dict[str, Any]] = []
    for index, item in enumerate(media):
        if not isinstance(item, Mapping) or int(item.get("index", -1)) != index:
            raise ValueError("material manifest media indexes must be contiguous")
        expected_id = safe_items[index]["id"]
        if str(item.get("item_id") or "") != expected_id:
            raise ValueError("material manifest media item id mismatch")
        audio_path = str(item.get("audio_path") or "")
        screenshot_path = str(item.get("screenshot_path") or "")
        if not (_SAFE_MEMBER_RE.fullmatch(audio_path) and audio_path.endswith(".wav")):
            raise ValueError("material manifest audio path is unsafe")
        if not (_SAFE_MEMBER_RE.fullmatch(screenshot_path) and screenshot_path.endswith(".webp")):
            raise ValueError("material manifest screenshot path is unsafe")
        safe_media.append(
            {
                "index": index,
                "item_id": expected_id,
                "audio_path": audio_path,
                "screenshot_path": screenshot_path,
                "start_sec": safe_items[index]["start_sec"],
                "end_sec": safe_items[index]["end_sec"],
            }
        )
    return {
        "schema_version": MATERIAL_BUNDLE_VERSION,
        "video": safe_video,
        "chat_offsets": safe_offsets,
        "selected_highlights": safe_items,
        "media": safe_media,
    }


def validate_material_batch_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, Mapping) or int(manifest.get("schema_version") or 0) != 2:
        raise ValueError("unsupported YouTube material batch schema")
    _assert_no_private_fields(manifest)
    raw_videos = manifest.get("videos")
    if not isinstance(raw_videos, list) or not raw_videos or len(raw_videos) > 8:
        raise ValueError("material batch must contain between one and eight videos")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_entry in raw_videos:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("material batch entry must be an object")
        video = raw_entry.get("video")
        if not isinstance(video, Mapping):
            raise ValueError("material batch entry has no video")
        safe_video = _safe_video(video)
        video_id = safe_video["vod_id"]
        if video_id in seen_ids:
            raise ValueError("material batch contains a duplicate video")
        seen_ids.add(video_id)
        prefix = f"videos/{video_id}/"

        raw_media = raw_entry.get("media")
        if not isinstance(raw_media, list):
            raise ValueError("material batch entry has no media")
        local_media: list[dict[str, Any]] = []
        for raw_media_item in raw_media:
            if not isinstance(raw_media_item, Mapping):
                raise ValueError("material batch media entry must be an object")
            local_item = dict(raw_media_item)
            for key in ("audio_path", "screenshot_path"):
                path = str(local_item.get(key) or "")
                if not path.startswith(prefix):
                    raise ValueError("material batch media path is not isolated")
                local_item[key] = path[len(prefix) :]
            local_media.append(local_item)

        local_entry = dict(raw_entry)
        local_entry["schema_version"] = MATERIAL_BUNDLE_VERSION
        local_entry["video"] = safe_video
        local_entry["media"] = local_media
        safe_local = validate_material_manifest(local_entry)
        safe_local["video"] = safe_video
        safe_local["media"] = [
            {
                **item,
                "audio_path": f"{prefix}{item['audio_path']}",
                "screenshot_path": f"{prefix}{item['screenshot_path']}",
            }
            for item in safe_local["media"]
        ]

        captions_path = str(raw_entry.get("captions_path") or "").strip()
        if captions_path:
            expected_captions_path = f"{prefix}captions.json"
            if captions_path != expected_captions_path:
                raise ValueError("material batch captions path is not isolated")
            safe_local["captions_path"] = expected_captions_path
        normalized.append(safe_local)

    return {"schema_version": 2, "videos": normalized}


def _member_name(value: str) -> str:
    name = str(value or "").replace("\\", "/")
    if not _SAFE_MEMBER_RE.fullmatch(name):
        raise ValueError(f"unsafe material bundle member: {name}")
    return name


def create_material_bundle(
    bundle_path: Path,
    manifest: Mapping[str, Any],
    media_files: Mapping[str, Path],
    *,
    captions_file: Path | None = None,
) -> Path:
    """Create a gzip tar bundle containing validated material and optional public captions."""

    safe_manifest = validate_material_manifest(manifest)
    expected_members = {"manifest.json"}
    for media in safe_manifest["media"]:
        expected_members.update((media["audio_path"], media["screenshot_path"]))
    provided = {_member_name(name): Path(path) for name, path in media_files.items()}
    if set(provided) != expected_members - {"manifest.json"}:
        raise ValueError("material bundle media files do not match manifest")
    for name, path in provided.items():
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"material bundle media file is missing: {name}")

    safe_captions_path: Path | None = None
    if captions_file is not None:
        from youtube_captions import validate_captions_payload

        safe_captions_path = Path(captions_file)
        if not safe_captions_path.is_file() or safe_captions_path.stat().st_size <= 0:
            raise ValueError("captions file is missing")
        captions_payload = json.loads(safe_captions_path.read_text(encoding="utf-8"))
        validate_captions_payload(captions_payload, expected_video_id=safe_manifest["video"]["vod_id"])

    bundle_path = Path(bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(safe_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with tarfile.open(bundle_path, mode="w:gz") as archive:
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(payload)
        manifest_info.mode = 0o600
        archive.addfile(manifest_info, fileobj=_BytesReader(payload))
        if safe_captions_path is not None:
            captions_info = archive.gettarinfo(str(safe_captions_path), arcname="captions.json")
            captions_info.mode = 0o600
            captions_info.uid = captions_info.gid = 0
            captions_info.uname = captions_info.gname = ""
            with safe_captions_path.open("rb") as source:
                archive.addfile(captions_info, source)
        for name in sorted(provided):
            path = provided[name]
            info = archive.gettarinfo(str(path), arcname=name)
            info.mode = 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as source:
                archive.addfile(info, source)
    return bundle_path


def create_material_batch_bundle(
    bundle_path: Path,
    entries: Iterable[tuple[Mapping[str, Any], Mapping[str, Path], Path | None]],
) -> Path:
    """Create one privacy-safe archive containing several independent videos."""

    raw_entries = list(entries)
    if not raw_entries:
        raise ValueError("material batch must contain at least one video")
    normalized_entries: list[dict[str, Any]] = []
    files: dict[str, Path] = {}
    for manifest, media_files, captions_file in raw_entries:
        safe = validate_material_manifest(manifest)
        video_id = safe["video"]["vod_id"]
        prefix = f"videos/{video_id}/"
        expected = {media["audio_path"] for media in safe["media"]} | {
            media["screenshot_path"] for media in safe["media"]
        }
        provided = {_member_name(name): Path(path) for name, path in media_files.items()}
        if set(provided) != expected:
            raise ValueError("material batch media files do not match manifest")
        for name, path in provided.items():
            if not path.is_file() or path.stat().st_size <= 0:
                raise ValueError(f"material batch media file is missing: {name}")
            files[f"{prefix}{name}"] = path

        entry = dict(safe)
        entry["media"] = [
            {
                **media,
                "audio_path": f"{prefix}{media['audio_path']}",
                "screenshot_path": f"{prefix}{media['screenshot_path']}",
            }
            for media in safe["media"]
        ]
        if captions_file is not None:
            from youtube_captions import validate_captions_payload

            captions_path = Path(captions_file)
            if not captions_path.is_file() or captions_path.stat().st_size <= 0:
                raise ValueError("material batch captions file is missing")
            captions_payload = json.loads(captions_path.read_text(encoding="utf-8"))
            validate_captions_payload(captions_payload, expected_video_id=video_id)
            entry["captions_path"] = f"{prefix}captions.json"
            files[f"{prefix}captions.json"] = captions_path
        normalized_entries.append(entry)

    batch_manifest = validate_material_batch_manifest({"schema_version": 2, "videos": normalized_entries})
    payload = json.dumps(batch_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bundle_path = Path(bundle_path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle_path, mode="w:gz") as archive:
        manifest_info = tarfile.TarInfo("batch.json")
        manifest_info.size = len(payload)
        manifest_info.mode = 0o600
        archive.addfile(manifest_info, fileobj=_BytesReader(payload))
        for name in sorted(files):
            path = files[name]
            info = archive.gettarinfo(str(path), arcname=name)
            info.mode = 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as source:
                archive.addfile(info, source)
    return bundle_path


class _BytesReader:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._position = 0

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._payload) - self._position
        start = self._position
        self._position = min(len(self._payload), self._position + size)
        return self._payload[start : self._position]


def extract_material_bundle(bundle_path: Path, output_dir: Path) -> dict[str, Any]:
    """Safely extract and validate a material bundle."""

    with tarfile.open(bundle_path, mode="r:gz") as archive:
        names = {str(member.name or "").replace("\\", "/") for member in archive.getmembers()}
    if "batch.json" in names:
        return extract_material_batch_bundle(bundle_path, output_dir)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle_path, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            name = str(member.name or "").replace("\\", "/")
            if not _SAFE_MEMBER_RE.fullmatch(name):
                raise ValueError(f"unsafe material bundle member: {name}")
            if member.issym() or member.islnk() or not (member.isfile() or name == "manifest.json"):
                raise ValueError("material bundle contains a non-regular file")
            destination = (output_dir / name).resolve()
            if output_dir.resolve() not in destination.parents:
                raise ValueError("material bundle member escapes extraction directory")
        if "manifest.json" not in {member.name for member in members}:
            raise ValueError("material bundle has no manifest")
        archive.extractall(output_dir)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    safe_manifest = validate_material_manifest(manifest)
    captions_path = output_dir / "captions.json"
    if captions_path.is_file():
        from youtube_captions import validate_captions_payload

        captions_payload = json.loads(captions_path.read_text(encoding="utf-8"))
        validate_captions_payload(captions_payload, expected_video_id=safe_manifest["video"]["vod_id"])
    for media in safe_manifest["media"]:
        for key in ("audio_path", "screenshot_path"):
            path = output_dir / media[key]
            if not path.is_file() or path.stat().st_size <= 0:
                raise ValueError(f"material bundle member is missing: {media[key]}")
    return safe_manifest


def extract_material_batch_bundle(bundle_path: Path, output_dir: Path) -> dict[str, Any]:
    """Safely extract and validate a multi-video material bundle."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle_path, mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            name = str(member.name or "").replace("\\", "/")
            if not _BATCH_MEMBER_RE.fullmatch(name):
                raise ValueError(f"unsafe material batch member: {name}")
            if member.issym() or member.islnk() or not member.isfile():
                raise ValueError("material batch contains a non-regular file")
            destination = (output_dir / name).resolve()
            if output_dir.resolve() not in destination.parents:
                raise ValueError("material batch member escapes extraction directory")
        if "batch.json" not in {member.name for member in members}:
            raise ValueError("material batch has no manifest")
        archive.extractall(output_dir)

    batch_manifest = json.loads((output_dir / "batch.json").read_text(encoding="utf-8"))
    safe_batch = validate_material_batch_manifest(batch_manifest)
    for entry in safe_batch["videos"]:
        captions_path = entry.get("captions_path")
        if captions_path:
            from youtube_captions import validate_captions_payload

            captions_payload = json.loads((output_dir / captions_path).read_text(encoding="utf-8"))
            validate_captions_payload(captions_payload, expected_video_id=entry["video"]["vod_id"])
        for media in entry["media"]:
            for key in ("audio_path", "screenshot_path"):
                path = output_dir / media[key]
                if not path.is_file() or path.stat().st_size <= 0:
                    raise ValueError(f"material batch member is missing: {media[key]}")
    return safe_batch


def upload_bundle_to_url(bundle_path: Path, upload_url: str) -> None:
    """Upload a bundle to an OCI PAR URL without logging the URL."""

    url = str(upload_url or "").strip()
    if not url.lower().startswith("https://"):
        raise ValueError("bundle upload URL must use HTTPS")
    data = Path(bundle_path).read_bytes()
    request_obj = request.Request(url, data=data, method="PUT", headers={"Content-Type": "application/gzip"})
    with request.urlopen(request_obj, timeout=120) as response:
        if int(getattr(response, "status", 200)) >= 300:
            raise RuntimeError("bundle upload failed")


def download_bundle_from_url(read_url: str, bundle_path: Path) -> None:
    url = str(read_url or "").strip()
    if not url.lower().startswith("https://"):
        raise ValueError("bundle read URL must use HTTPS")
    with request.urlopen(url, timeout=120) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError("bundle download was empty")
    Path(bundle_path).write_bytes(payload)


__all__ = [
    "MATERIAL_BUNDLE_VERSION",
    "build_material_manifest",
    "create_material_bundle",
    "create_material_batch_bundle",
    "download_bundle_from_url",
    "extract_material_bundle",
    "extract_material_batch_bundle",
    "upload_bundle_to_url",
    "validate_material_batch_manifest",
    "validate_material_manifest",
]
