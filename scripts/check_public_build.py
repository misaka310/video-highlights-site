from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
DATA = ROOT / "data"
REQUIRED_FILES = (
    "index.html",
    "favicon.svg",
    "site-config.json",
    "robots.txt",
    "sitemap.xml",
    "data/vods.json",
    "data/vod_index.json",
)
ALLOWED_SITE_CONFIG_SECTIONS = {"site", "twitch"}
FORBIDDEN_KEY_FRAGMENTS = (
    "secret",
    "token",
    "password",
    "api_key",
    "prompt",
    "extra_tag_rules",
    "transcript",
)


def fail(message: str) -> None:
    raise SystemExit(f"public build check failed: {message}")


def read_json(path: Path) -> Any:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        fail(f"UTF-8 BOM is not allowed: {path.relative_to(ROOT)}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"invalid UTF-8 JSON: {path.relative_to(ROOT)}: {exc}")


def walk_keys(value: Any, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.append(path)
            keys.extend(walk_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            keys.extend(walk_keys(child, f"{prefix}[{index}]"))
    return keys


def check_required_files() -> None:
    for relative_path in REQUIRED_FILES:
        path = PUBLIC / relative_path
        if not path.is_file():
            fail(f"missing required file: public/{relative_path}")
    if not any((PUBLIC / "assets").glob("*.js")):
        fail("missing JavaScript bundle under public/assets")
    if not any((PUBLIC / "assets").glob("*.css")):
        fail("missing CSS bundle under public/assets")


def check_public_json_matches_sources() -> None:
    for relative_path in ("vods.json", "vod_index.json"):
        source = read_json(DATA / relative_path)
        published = read_json(PUBLIC / "data" / relative_path)
        if published != source:
            fail(f"public/data/{relative_path} differs structurally from data/{relative_path}")

    source_captions = DATA / "captions"
    public_captions = PUBLIC / "data" / "captions"
    if source_captions.is_dir():
        for source_path in sorted(source_captions.glob("*.json")):
            public_path = public_captions / source_path.name
            if not public_path.is_file():
                fail(f"missing captions JSON: {public_path.relative_to(ROOT)}")
            if read_json(public_path) != read_json(source_path):
                fail(f"published captions differ from source: {source_path.name}")

    source_details = DATA / "vods"
    public_details = PUBLIC / "data" / "vods"
    if source_details.is_dir():
        for source_path in sorted(source_details.glob("*.json")):
            public_path = public_details / source_path.name
            if not public_path.is_file():
                fail(f"missing VOD detail JSON: {public_path.relative_to(ROOT)}")
            if read_json(public_path) != read_json(source_path):
                fail(f"published VOD detail differs from source: {source_path.name}")


def check_site_config() -> None:
    payload = read_json(PUBLIC / "site-config.json")
    if not isinstance(payload, dict):
        fail("site-config.json must be an object")
    unexpected = set(payload) - ALLOWED_SITE_CONFIG_SECTIONS
    if unexpected:
        fail(f"site-config.json contains unexpected sections: {sorted(unexpected)}")
    for key_path in walk_keys(payload):
        lowered = key_path.lower()
        if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
            fail(f"site-config.json exposes an internal key: {key_path}")


def check_static_metadata() -> None:
    index_html = (PUBLIC / "index.html").read_text(encoding="utf-8")
    site_config = read_json(PUBLIC / "site-config.json")
    site = site_config.get("site") if isinstance(site_config, dict) else {}
    site = site if isinstance(site, dict) else {}

    if "__SITE_" in index_html:
        fail("index.html still contains unresolved site metadata placeholders")

    name = html.escape(str(site.get("name") or "YouTube Highlights").strip(), quote=True)
    description = html.escape(
        str(site.get("description") or "YouTubeライブアーカイブのコメント量から見どころを表示する非公式サイトです。").strip(),
        quote=True,
    )
    language = html.escape(str(site.get("language") or "ja").strip(), quote=True)
    base_url = html.escape(str(site.get("base_url") or "").strip().rstrip("/"), quote=True)
    required_fragments = (
        f'<html lang="{language}"',
        f'<title>{name}</title>',
        f'<meta name="description" content="{description}"',
        f'<meta property="og:title" content="{name}"',
        f'<meta property="og:description" content="{description}"',
        f'<meta property="og:url" content="{base_url}"',
    )
    missing = [fragment for fragment in required_fragments if fragment not in index_html]
    if missing:
        fail(f"index.html metadata does not match site-config.json: {missing}")


def check_thumbnail_references() -> None:
    details_dir = PUBLIC / "data" / "vods"
    if not details_dir.is_dir():
        return
    for detail_path in sorted(details_dir.glob("*.json")):
        payload = read_json(detail_path)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            fail(f"items must be an array: {detail_path.relative_to(ROOT)}")
        for item in items:
            if not isinstance(item, dict):
                continue
            screenshot_url = str(item.get("screenshot_url") or "").strip()
            if not screenshot_url:
                continue
            relative = screenshot_url.split("?", 1)[0].lstrip("/")
            candidate = PUBLIC / relative
            if not candidate.is_file():
                fail(f"missing referenced thumbnail: {relative}")


def check_produced_videos() -> None:
    source = DATA / "produced_videos.json"
    if not source.is_file():
        return
    published = PUBLIC / "data" / "produced_videos.json"
    if not published.is_file():
        fail("missing public/data/produced_videos.json")

    sys.path.insert(0, str(ROOT / "scripts"))
    from export_produced_videos import build_public_payload

    if read_json(published) != build_public_payload(read_json(source)):
        fail("public/data/produced_videos.json was not filtered by export_produced_videos.py")

    payload = read_json(published)
    videos = payload.get("videos", []) if isinstance(payload, dict) else []
    for video in videos:
        for key in ("video_id", "title", "video_url"):
            if not str(video.get(key) or "").strip():
                fail(f"produced video entry is missing {key}")
        poster = str(video.get("poster_url") or "").strip()
        if not poster or poster.startswith(("http://", "https://")):
            continue
        candidate = PUBLIC / poster.lstrip("/") if poster.startswith("/") else PUBLIC / "data" / poster.lstrip("/")
        if not candidate.is_file():
            fail(f"missing produced video poster: {poster}")


def check_render_target() -> None:
    render_text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    if "staticPublishPath: public" not in render_text:
        fail("render.yaml must publish public/")


def main() -> None:
    check_required_files()
    check_public_json_matches_sources()
    check_site_config()
    check_static_metadata()
    check_thumbnail_references()
    check_produced_videos()
    check_render_target()
    print("public build check passed")


if __name__ == "__main__":
    main()
