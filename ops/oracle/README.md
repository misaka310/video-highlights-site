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
# Discover recent archives from this channel tab on every timer run.
YOUTUBE_ORACLE_STREAMS_URL=https://www.youtube.com/@dotitube/streams
# One timer run hands off up to five newest unprocessed archives from the last 60 days.
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

When `YOUTUBE_ORACLE_STREAMS_URL` is set, the timer discovers archives from the
last 60 days, removes IDs already present in the repository's published
`data/vod_index.json`, then selects up to five in newest-first order for one
Actions run. Oracle state also keeps discovered archive IDs, upload dates, and
timestamps for the 60-day window. Each run merges that cache with the current
`/streams` listing, so a temporary listing omission does not lose an archive
that was already discovered. The cache contains no titles, chat, or captions;
published IDs and expired records are pruned before selection. Separate
caption-retry state stores only video IDs, per-attempt dates/counts, safe reason
codes, and manual/automatic subtitle source outcomes; it retries published
VODs without captions at the first daily run at least 24 and 72 hours after the
initial attempt, then stops after the initial attempt plus two retries. A
successful fetch waits for the existing checked publication path instead of
fetching again. The caption content is sent only in the existing short-lived
OCI bundle when an Oracle retry succeeds.
State records of
discovery or successful handoff do not suppress unpublished archives: a later
GitHub processing or publication failure must leave the archive eligible for
retry. `YOUTUBE_ORACLE_MAX_VIDEOS` can lower the five-item bound. A larger
backlog advances from the newest eligible archives by up to five per daily run.
Older unprocessed archives inside the 60-day window are retained and become
eligible as newer archives are published. An archive whose Oracle acquisition
or material preparation fails is not marked processed and is retried on a later
run. Published IDs are excluded from full chat/highlight processing, while the
separate caption-only retry path may update a missing `data/captions/<id>.json`
without reprocessing a published VOD. A fixed
`YOUTUBE_ORACLE_VIDEO_URL` remains supported as a one-video manual fallback
when streams discovery is unset.
That direct-video path also checks the published `data/vod_index.json` IDs
before acquisition. A published ID that already has `data/captions/<id>.json`
is logged as `already_published` and exits without downloading media or
dispatching another GitHub run. A published ID without that file is not
reprocessed; the run fetches only its captions immediately (the same caption-only
path as the scheduled retry) and logs the manual/automatic outcome or the reason.

Install and enable the timer:

```bash
sudo install -m 0644 ops/oracle/youtube-highlight.service /etc/systemd/system/youtube-highlight.service
sudo install -m 0644 ops/oracle/youtube-highlight.timer /etc/systemd/system/youtube-highlight.timer
sudo systemctl daemon-reload
sudo systemctl enable --now youtube-highlight.timer
systemctl list-timers youtube-highlight.timer
```

Before the acquisition service starts, its installed `ExecStartPre` hook
fast-forwards the clean Oracle checkout to the repository's public `main`.
This runs immediately before the daily 06:07 JST job and before a manual service
start; there is no separate periodic code-sync timer, and sync alone does not
start this acquisition job.
Archives that appear after the 06:07 JST check stay unprocessed until the next
acquisition run. Unprocessed archives inside the 60-day window are not
discarded; each run chooses the newest eligible five (or fewer) and later runs
continue through the remaining backlog. Archives older than 60 days are outside the
processing window.

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
