# Oracle YouTube handoff

The Oracle VM is the only component that connects to YouTube. It fetches
live-chat offsets with the configured `YOUTUBE_ORACLE_YTDLP_PATH`,
`YOUTUBE_ORACLE_DENO_PATH`, and `YOUTUBE_ORACLE_COOKIES_PATH` route, applies
the repository's existing chat z-score detector, and cuts only the selected
highlight intervals.

The selected WAV and WEBP files are sent to one short-lived OCI Object Storage
object through a Pre-Authenticated Request (PAR). GitHub Actions reads that
object, runs Whisper and the public-data checks, and OCI Object Lifecycle
Management removes the object within one day. The workflow never runs
`yt-dlp` against YouTube.

## Applied OCI settings (2026-09-17)

The following settings were applied to the YouTube-only resources. The
existing `shareclip` bucket is unrelated and must not be used by this flow.

- Region: `ap-osaka-1` (Japan Central (Osaka))
- Compartment: `kiralab` (root)
- Bucket: `youtube-material-upload` (private, Standard tier)
- Object: `youtube-material/latest.tar.gz`
- Upload PAR: `youtube-material-upload-par-20260917`, object write/overwrite, expires
  2027-03-17 07:00 UTC
- Read PAR: `youtube-material-read-par-20260917`, object read, expires 2027-03-17
  07:00 UTC
- Lifecycle rule: `delete-youtube-material-after-1-day`, enabled, delete
  Objects after 1 day, inclusion prefix `youtube-material/`
- IAM policy: `YouTubeMaterialLifecyclePolicy`, limited by
  `target.bucket.name='youtube-material-upload'` to the Object Storage service
  in `ap-osaka-1`

PAR URLs are intentionally not recorded in the repository or this document.
They are bearer credentials and must be stored only in the Oracle environment
file and the GitHub Actions secret described below. PARs are reusable until
their expiration; the 2026-09-17 rotation replaced PARs that still appeared
active in OCI after the target bucket had been recreated. Rotate both URLs
together before 2027-03-17 07:00 UTC.

## Install on Oracle

Install this repository at the operator-selected repository root, or copy the
`scripts/`, `config/`, and `ops/` files there. Keep the existing verified
Oracle acquisition prerequisites in place:

- `YOUTUBE_ORACLE_YTDLP_PATH`
- `YOUTUBE_ORACLE_DENO_PATH`
- `YOUTUBE_ORACLE_COOKIES_PATH` with mode `600`
- `ffmpeg`

Create `/etc/youtube-highlight/youtube.env` with mode `600`. Use real values
only on the VM; never commit this file:

```text
# Resolve the newest archive from this channel tab on every timer run.
YOUTUBE_ORACLE_STREAMS_URL=https://www.youtube.com/@dotitube/streams
# One timer run can hand off up to five unprocessed archives in one bundle.
YOUTUBE_ORACLE_MAX_VIDEOS=5
# Optional one-video fallback when streams discovery is intentionally disabled.
YOUTUBE_ORACLE_VIDEO_URL=https://www.youtube.com/watch?v=...
YOUTUBE_ORACLE_YTDLP_PATH=$HOME/yt-dlp
YOUTUBE_ORACLE_DENO_PATH=$HOME/.local/bin/deno
YOUTUBE_ORACLE_COOKIES_PATH=$HOME/youtube-cookies.txt
YOUTUBE_ORACLE_WORK_ROOT=$HOME/ytprobe
YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL=https://objectstorage.../par/...
YOUTUBE_ORACLE_GITHUB_TOKEN=...
YOUTUBE_ORACLE_GITHUB_REPOSITORY=owner/repository
DISCORD_WEBHOOK_URL=...
```

The PAR used for upload must be scoped to the single temporary object and
permit the Oracle `PUT` and overwrite of that object; the read PAR is stored
separately in GitHub. Each PAR can be reused until its expiration, so they do
not need to be recreated daily. A six-month lifetime is acceptable for this
fixed, narrowly scoped object; rotate both PARs before they expire. OCI
pre-authenticated requests cannot delete objects, so configure an OCI
lifecycle rule that deletes the temporary object within one day. The GitHub token must be limited to this repository's
`repository_dispatch` operation.

When `YOUTUBE_ORACLE_STREAMS_URL` is set, the timer resolves up to five
unprocessed archives from that channel's `/streams` tab and hands them to one
Actions run. `YOUTUBE_ORACLE_MAX_VIDEOS` can lower that bound. Processed video
IDs are kept in the state file, so a day without a new stream exits cleanly
without re-running Whisper preparation. A fixed
`YOUTUBE_ORACLE_VIDEO_URL` remains supported as a fallback.

Install and enable the timer:

```bash
sudo install -m 0644 ops/oracle/youtube-highlight.service /etc/systemd/system/youtube-highlight.service
sudo install -m 0644 ops/oracle/youtube-highlight.timer /etc/systemd/system/youtube-highlight.timer
sudo systemctl daemon-reload
sudo systemctl enable --now youtube-highlight.timer
systemctl list-timers youtube-highlight.timer
```

Useful one-shot checks are `systemctl start youtube-highlight.service` and
`journalctl -u youtube-highlight.service`. The job prints only classified
status and counts; it does not print cookies, keys, chat text, or PAR URLs.
If yt-dlp returns `yt_dlp_failure` after creating a non-empty live-chat JSON,
the job keeps that artifact and validates it before continuing; an absent or
empty artifact remains a hard failure.
## Refreshing YouTube authentication

The production cookie file configured by `YOUTUBE_ORACLE_COOKIES_PATH` on Oracle
must remain mode `600`. If YouTube authentication expires, sign in to YouTube
in the Oracle VM's Chrome profile, export the authenticated cookies from that
Oracle browser, replace the file, and rerun the one-shot test before starting
the service. The Windows Chrome cookie export is not a production fallback;
the service must use the Oracle VM's current login session. Never put the
cookie file, browser profile, or SSH key in the repository.

## GitHub Actions secrets

Add these repository Actions secrets:

- `YOUTUBE_ORACLE_BUNDLE_READ_URL`: read-only PAR for the temporary object.

The workflow is triggered by the Oracle `repository_dispatch` event
`youtube-material-ready`. Its normal checked-PR publication path remains
separate from the paused legacy `update-vods.yml` schedule.
