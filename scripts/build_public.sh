#!/usr/bin/env sh
set -eu

PYTHON_BIN="${PYTHON_BIN:-python}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "error: python runtime is required for build_public.sh"
    exit 2
  fi
fi

if ! command -v node >/dev/null 2>&1; then
  echo "error: Node.js 20 or later is required for build_public.sh"
  exit 2
fi
if [ ! -d node_modules ] || [ ! -d frontend/node_modules ]; then
  echo "error: dependencies are not installed; run npm run setup first"
  exit 2
fi

copy_json_without_bom() {
  src_path="$1"
  dest_path="$2"
  "${PYTHON_BIN}" - "$src_path" "$dest_path" <<'PY'
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
text = src.read_text(encoding="utf-8-sig")
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(text, encoding="utf-8")
PY
}

(
  cd frontend
  node node_modules/typescript/bin/tsc -b
  node node_modules/vite/bin/vite.js build
)

rm -rf public
mkdir -p public/data
cp -R frontend/dist/. public/

copy_json_without_bom data/vods.json public/data/vods.json
copy_json_without_bom data/vod_index.json public/data/vod_index.json

if [ -d data/vods ]; then
  mkdir -p public/data/vods
  find data/vods -maxdepth 1 -type f -name "*.json" | while IFS= read -r src_json; do
    [ -n "$src_json" ] || continue
    copy_json_without_bom "$src_json" "public/data/vods/$(basename "$src_json")"
  done
fi

if [ -d data/segment-thumbnails ]; then
  mkdir -p public/data/segment-thumbnails
  cp -R data/segment-thumbnails/. public/data/segment-thumbnails/
fi

if [ -d data/captions ]; then
  mkdir -p public/data/captions
  find data/captions -maxdepth 1 -type f -name "*.json" | while IFS= read -r src_json; do
    [ -n "$src_json" ] || continue
    copy_json_without_bom "$src_json" "public/data/captions/$(basename "$src_json")"
  done
fi

if [ -f data/produced_videos.json ]; then
  mkdir -p public/data
  "${PYTHON_BIN}" scripts/export_produced_videos.py data/produced_videos.json public/data/produced_videos.json
fi

if [ -d data/produced-video-posters ]; then
  mkdir -p public/data/produced-video-posters
  cp -R data/produced-video-posters/. public/data/produced-video-posters/
fi

node scripts/export-site-config.mjs public/site-config.json
"${PYTHON_BIN}" scripts/apply_site_metadata.py public/index.html public/site-config.json

"${PYTHON_BIN}" - <<'PY'
import json
from pathlib import Path

public = Path("public")
config = json.loads((public / "site-config.json").read_text(encoding="utf-8"))
base_url = str(config.get("site", {}).get("base_url", "")).strip().rstrip("/")
robots = "User-agent: *\nAllow: /\n"
if base_url:
    robots += f"Sitemap: {base_url}/sitemap.xml\n"
(public / "robots.txt").write_text(robots, encoding="utf-8")

if base_url:
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{base_url}/</loc></url>\n"
        "</urlset>\n"
    )
    (public / "sitemap.xml").write_text(sitemap, encoding="utf-8")
PY
