import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { Empty, LayerCard } from "@cloudflare/kumo";
import { ActivityMap } from "./components/activity-map.js";
import { CaptionPanel } from "./components/caption-panel.js";
import { SiteHeader } from "./components/site-header.js";
import { VodRail } from "./components/vod-rail.js";
import type { HighlightSegment } from "./domain/vod.js";
import { useMediaQuery } from "./hooks/use-media-query.js";
import { useSiteMetadata } from "./hooks/use-site-metadata.js";
import { useVodPage } from "./hooks/use-vod-page.js";
import { createActivityGeometry, createActivityOverlay } from "./lib/activity-geometry.js";
import { extractAnosaStatements, resolveCaptionWindow, type AnosaStatement, type CaptionData } from "./lib/captions.js";
import { createVodSwitchPlaybackOptions } from "./player/playback-request.js";
import { getVodProvider, pageUrl, parsePageSearch, resolveDurationSec } from "./lib/vod-data.js";
import { TwitchPlayer, type TwitchPlayerHandle } from "./twitch-player";

export default function App() {
  const [page, setPageState] = useState(() => parsePageSearch(location.search));
  const { data, error } = useVodPage(page);
  const playerRef = useRef<TwitchPlayerHandle>(null);
  const [activeVodId, setActiveVodId] = useState("");
  const [activeSegmentId, setActiveSegmentId] = useState("");
  const [positionSec, setPositionSec] = useState(0);
  const [playerState, setPlayerState] = useState("待機中");
  const [captions, setCaptions] = useState<CaptionData | null>(null);
  const compactActivityMap = useMediaQuery("(max-width: 600px)");

  useSiteMetadata(data?.siteConfig);

  useEffect(() => {
    if (!data) return;
    const firstVod = data.vods[0];
    const firstSegment = firstVod?.items?.[0];
    setActiveVodId(firstVod?.vod_id || "");
    setActiveSegmentId(firstSegment?.id || "");
    setPositionSec(Number(firstSegment?.start_sec || 0));
  }, [data]);

  useEffect(() => {
    if (!data || data.requestedPage !== page || data.page === page) return;
    history.replaceState({}, "", pageUrl(location.href, data.page));
    setPageState(data.page);
  }, [data, page]);

  useEffect(() => {
    let cancelled = false;
    setCaptions(null);
    if (!activeVodId) {
      return () => {
        cancelled = true;
      };
    }

    void fetch(`/data/captions/${activeVodId}.json`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return null;
        const payload = (await response.json()) as CaptionData;
        if (payload.video_id !== activeVodId || !Array.isArray(payload.cues)) return null;
        return payload;
      })
      .then((payload) => {
        if (!cancelled) setCaptions(payload);
      })
      .catch(() => {
        if (!cancelled) setCaptions(null);
      });

    return () => {
      cancelled = true;
    };
  }, [activeVodId]);

  useEffect(() => {
    const firstVod = data?.vods[0];
    const firstSegment = firstVod?.items?.[0];
    if (!firstVod || !playerRef.current) return;
    playerRef.current.requestPlayback(firstVod.vod_id, Number(firstSegment?.start_sec || 0), {
      autoplay: false,
      muted: true,
      triggeredByUser: false,
      provider: getVodProvider(firstVod),
    });
  }, [data]);

  const activeVod = data?.vods.find((vod) => vod.vod_id === activeVodId) || data?.vods[0] || null;
  const segments = useMemo(() => activeVod?.items?.slice(0, 3) || [], [activeVod]);
  const activeSegment = segments.find((segment) => segment.id === activeSegmentId) || segments[0] || null;
  const durationSec = resolveDurationSec(activeVod);
  const activityGeometry = useMemo(
    () => createActivityGeometry(activeVod?.activity_map?.buckets || [], compactActivityMap),
    [activeVod?.activity_map?.buckets, compactActivityMap],
  );
  const activityOverlay = useMemo(
    () => createActivityOverlay({
      durationSec,
      positionSec,
      segmentStartSec: activeSegment?.start_sec,
      segmentEndSec: activeSegment?.end_sec,
      lastCommentSec: activeVod?.activity_map?.last_comment_sec,
    }),
    [activeSegment?.end_sec, activeSegment?.start_sec, activeVod?.activity_map?.last_comment_sec, durationSec, positionSec],
  );

  const anosaStatements = useMemo(
    () => extractAnosaStatements(captions?.cues || []),
    [captions?.cues],
  );
  const captionWindow = useMemo(
    () => resolveCaptionWindow(captions?.cues || [], positionSec),
    [captions?.cues, positionSec],
  );

  function setPage(nextPage: number) {
    const safePage = Math.max(1, nextPage);
    history.replaceState({}, "", pageUrl(location.href, safePage));
    setPageState(safePage);
  }

  function requestUserPlayback(vodId: string, startSec: number, provider = getVodProvider(activeVod)) {
    const safeStartSec = Math.max(0, Math.floor(Number(startSec) || 0));
    setPositionSec(safeStartSec);
    playerRef.current?.requestPlayback(vodId, safeStartSec, {
      autoplay: true,
      muted: false,
      triggeredByUser: true,
      provider,
    });
  }

  function selectVod(vodId: string) {
    const vod = data?.vods.find((entry) => entry.vod_id === vodId);
    const first = vod?.items?.[0];
    const startSec = Number(first?.start_sec || 0);
    setActiveVodId(vodId);
    setActiveSegmentId(first?.id || "");
    setPositionSec(Math.max(0, Math.floor(startSec)));
    playerRef.current?.requestPlayback(vodId, startSec, createVodSwitchPlaybackOptions(getVodProvider(vod)));
  }

  function selectSegment(segment: HighlightSegment) {
    setActiveSegmentId(segment.id);
    requestUserPlayback(activeVod?.vod_id || "", segment.start_sec);
  }

  function selectAnosa(statement: AnosaStatement) {
    setActiveSegmentId("");
    requestUserPlayback(activeVod?.vod_id || "", statement.start_sec);
  }

  function seekByMap(event: MouseEvent<HTMLButtonElement>) {
    if (!durationSec || !activeVod) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    requestUserPlayback(activeVod.vod_id, Math.floor(durationSec * ratio));
  }

  function rewindTenSeconds() {
    if (!activeVod) return;
    const current = playerRef.current?.getCurrentTime({ preferPendingSeek: true });
    const base = current == null ? positionSec : current;
    requestUserPlayback(activeVod.vod_id, Math.max(0, Math.floor(base) - 10));
  }

  if (error) {
    return (
      <main className="preview-shell preview-shell--empty">
        <Empty title="表示データがありません" description={error} />
      </main>
    );
  }

  if (!data) {
    return <main className="loading-state">読み込み中...</main>;
  }

  if (!activeVod) {
    return (
      <main className="preview-shell preview-shell--empty">
        <Empty title="表示データがありません" description="公開中のVODデータがまだありません。" />
      </main>
    );
  }

  const siteName = String(data.siteConfig.site?.name || "YouTube Highlights").trim();

  return (
    <div className="preview-shell">
      <SiteHeader
        siteName={siteName}
        updatedAt={data.updatedAt}
        nextUpdateAt={data.nextUpdateAt}
        feedbackUrl={data.siteConfig.site?.feedback_url || ""}
      />

      <main className="content-grid">
        <section className="player-column" aria-label="再生エリア">
          <LayerCard>
            <LayerCard.Primary>
              <div className="playback-surface">
                <TwitchPlayer
                  ref={playerRef}
                  onPositionChange={setPositionSec}
                  onStatusChange={(label) => setPlayerState(label)}
                />
                <div className={captions ? "playback-assist-panel" : "playback-assist-panel playback-assist-panel--map-only"}>
                  <ActivityMap
                    geometry={activityGeometry}
                    overlay={activityOverlay}
                    positionSec={positionSec}
                    onSeek={seekByMap}
                    onRewind={rewindTenSeconds}
                  />
                  {captions ? <CaptionPanel window={captionWindow} /> : null}
                </div>
              </div>
            </LayerCard.Primary>
          </LayerCard>
        </section>

        <VodRail
          vods={data.vods}
          activeVod={activeVod}
          segments={segments}
          activeSegmentId={activeSegment?.id || ""}
          anosaStatements={anosaStatements}
          captionsAvailable={Boolean(captions)}
          durationSec={durationSec}
          playerState={playerState}
          positionSec={positionSec}
          page={page}
          totalCount={data.totalCount}
          onSelectVod={selectVod}
          onSelectSegment={selectSegment}
          onSelectAnosa={selectAnosa}
          onSetPage={setPage}
        />
      </main>
    </div>
  );
}
