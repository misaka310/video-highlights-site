from __future__ import annotations

from urllib.parse import urlparse


YOUTUBE_URL_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


def is_youtube_url(value: str) -> bool:
    """Return whether value is an HTTP(S) URL on an approved YouTube host."""

    try:
        parsed = urlparse(str(value or "").strip())
        hostname = (parsed.hostname or "").lower()
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and hostname in YOUTUBE_URL_HOSTS
