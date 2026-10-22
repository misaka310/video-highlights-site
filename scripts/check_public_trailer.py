"""Production smoke check for DOTITAO trailer without GUI or repository writes."""
from __future__ import annotations

import json
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

BASE = "https://dotitao-moments.onrender.com"
ORIGIN = BASE
EXPECTED_MASTER = BASE + "/media/dotitao-trailer/master.m3u8"
EXPECTED_TITLE = "ドチタオ トレーラー"


def fetch(url: str, *, binary: bool = False) -> bytes:
    last_error = None
    for attempt in range(4):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "DOTITAO-public-trailer-smoke/1.0",
                    "Origin": ORIGIN,
                    "Cache-Control": "no-cache",
                },
            )
            with urlopen(request, timeout=22) as response:
                if response.status != 200:
                    raise AssertionError(f"status {response.status}: {url}")
                if urlsplit(url).netloc != urlsplit(BASE).netloc:
                    cors = response.headers.get("Access-Control-Allow-Origin")
                    if cors not in ("*", ORIGIN):
                        raise AssertionError(f"cross-origin access blocked: {url} (CORS={cors})")
                payload = response.read(200000 if not binary else 512)
            print(f"PASS HTTP 200: {url}")
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2)
    raise AssertionError(f"Public URL failed after retries: {url}: {last_error}") from last_error


def lines(data: bytes) -> list[str]:
    text = data.decode("utf-8-sig")
    if not text.startswith("#EXTM3U"):
        raise AssertionError("Not an HLS playlist")
    return [line.strip() for line in text.splitlines() if line.strip()]


def main() -> None:
    entries = json.loads(fetch(BASE + "/data/produced_videos.json?smoke=trailer").decode("utf-8-sig"))
    videos = entries["videos"]
    trailer = next((v for v in videos if v.get("video_id") == "dotitao-trailer-2026"), None)
    if trailer is None:
        raise AssertionError("Trailer missing from deployed produced videos")
    if len(videos) < 3:
        raise AssertionError("Existing produced videos disappeared")
    if trailer["video_url"] != EXPECTED_MASTER:
        raise AssertionError(f"Not the versionless public master: {trailer['video_url']}")
    if trailer["title"] != EXPECTED_TITLE:
        raise AssertionError(f"Unexpected public title: {trailer['title']}")
    for field in ("title", "description", "credits", "poster_url", "video_url"):
        value = str(trailer[field])
        if any(token in value for token in ("v5", "正式採用", "制作正本", "177_dotitao")):
            raise AssertionError(f"Internal production metadata in public {field}: {value}")
    poster_url = BASE + "/data/" + trailer["poster_url"]
    if not fetch(poster_url, binary=True).startswith(b"\xff\xd8\xff"):
        raise AssertionError("Public poster is not JPEG")
    if not fetch(BASE + "/?view=videos&video=dotitao-trailer-2026").lstrip().lower().startswith(b"<!doctype html"):
        raise AssertionError("Production viewer is not HTML")

    master_lines = lines(fetch(EXPECTED_MASTER))
    variants = [line for line in master_lines if not line.startswith("#")]
    if len(variants) != 3:
        raise AssertionError(f"Expected 3 variants, found {variants}")
    for variant in variants:
        variant_url = urljoin(EXPECTED_MASTER, variant)
        playlist = lines(fetch(variant_url))
        fragments = [line for line in playlist if not line.startswith("#")]
        if len(fragments) != 13:
            raise AssertionError(f"Expected 13 HLS fragments, got {len(fragments)}: {variant_url}")
        for fragment in (fragments[0], fragments[-1]):
            url = urljoin(variant_url, fragment)
            first_bytes = fetch(url, binary=True)
            if not first_bytes or first_bytes[0] != 0x47:
                raise AssertionError(f"Missing MPEG-TS sync marker: {url}")
    print(f"PASS production trailer: {EXPECTED_TITLE}, {len(variants)} variants, stable URL")


if __name__ == "__main__":
    main()
