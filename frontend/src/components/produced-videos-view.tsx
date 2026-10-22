import { useCallback, useEffect, useRef, useState } from "react";
import { LayerCard } from "@cloudflare/kumo";
import { PlayIcon } from "@phosphor-icons/react";
import type { ProducedVideo } from "../domain/vod.js";
import { useHlsVideo } from "../hooks/use-hls-video.js";
import { formatDate, formatMinuteClock } from "../lib/formatters.js";
import { currentChapterIndex } from "../lib/produced-videos.js";
import { isHlsSource } from "../lib/video-source.js";

type ProducedVideosViewProps = {
  videos: ProducedVideo[];
  activeVideo: ProducedVideo;
  onSelect: (videoId: string) => void;
};

export function ProducedVideosView({ videos, activeVideo, onSelect }: ProducedVideosViewProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playOnLoadRef = useRef(false);
  const [positionSec, setPositionSec] = useState(0);
  const [failed, setFailed] = useState(false);
  const hlsSource = isHlsSource(activeVideo.video_url);

  const playWhenReady = useCallback(() => {
    if (!playOnLoadRef.current) return;
    playOnLoadRef.current = false;
    void videoRef.current?.play().catch(() => undefined);
  }, []);

  const handleVideoError = useCallback(() => setFailed(true), []);

  useHlsVideo({
    videoRef,
    url: hlsSource ? activeVideo.video_url : "",
    onReady: playWhenReady,
    onError: handleVideoError,
  });

  useEffect(() => {
    setPositionSec(0);
    setFailed(false);
    const element = videoRef.current;
    if (!element || hlsSource) return;
    element.load();
    if (playOnLoadRef.current) {
      playOnLoadRef.current = false;
      void element.play().catch(() => undefined);
    }
  }, [activeVideo.video_id, hlsSource]);

  const activeChapter = currentChapterIndex(activeVideo.chapters, positionSec);
  const meta = [
    activeVideo.duration_sec ? formatMinuteClock(activeVideo.duration_sec) : "",
    activeVideo.published_at ? formatDate(activeVideo.published_at, { year: "numeric", month: "numeric", day: "numeric" }) : "",
  ]
    .filter(Boolean)
    .join(" ・ ");

  function selectVideo(videoId: string) {
    if (videoId === activeVideo.video_id) {
      void videoRef.current?.play().catch(() => undefined);
      return;
    }
    playOnLoadRef.current = true;
    onSelect(videoId);
  }

  function seekTo(startSec: number) {
    const element = videoRef.current;
    if (!element) return;
    element.currentTime = startSec;
    setPositionSec(startSec);
    void element.play().catch(() => undefined);
  }

  return (
    <main className="content-grid" aria-label="紹介動画">
      <section className="player-column">
        <LayerCard>
          <LayerCard.Primary>
            <div className="playback-surface">
              <div className="produced-stage">
                <video
                  ref={videoRef}
                  className="produced-element"
                  src={hlsSource ? undefined : activeVideo.video_url}
                  poster={activeVideo.poster_url || undefined}
                  controls
                  playsInline
                  preload="metadata"
                  onTimeUpdate={(event) => setPositionSec(event.currentTarget.currentTime)}
                  onError={handleVideoError}
                />
              </div>
              <div className="produced-detail">
                <div className="produced-title-row">
                  <div className="produced-titles">
                    <p className="video-eyebrow">{activeVideo.credits ? "はじめての方へ" : "紹介動画"}</p>
                    <h2>{activeVideo.title}</h2>
                  </div>
                  {meta ? <span className="produced-meta">{meta}</span> : null}
                </div>

                {failed ? <p className="video-error">動画を読み込めませんでした。</p> : null}

                {activeVideo.chapters.length ? (
                  <div className="video-chapters" aria-label="チャプター">
                    {activeVideo.chapters.map((chapter, index) => (
                      <button
                        key={`${chapter.start_sec}-${chapter.label}`}
                        type="button"
                        className={index === activeChapter ? "video-chapter is-active" : "video-chapter"}
                        onClick={() => seekTo(chapter.start_sec)}
                      >
                        <span className="video-chapter-time">{formatMinuteClock(chapter.start_sec)}</span>
                        <span className="video-chapter-label">{chapter.label}</span>
                      </button>
                    ))}
                  </div>
                ) : null}

                {activeVideo.description ? <p className="video-description">{activeVideo.description}</p> : null}
                {activeVideo.credits ? <p className="video-credits">{activeVideo.credits}</p> : null}
              </div>
            </div>
          </LayerCard.Primary>
        </LayerCard>
      </section>

      <aside className="highlight-column" aria-label="紹介動画の一覧">
        <LayerCard className="produced-list-card">
          <LayerCard.Primary>
            <div className="rail-content">
              <div className="produced-list-head">
                <strong>紹介動画</strong>
                <span>{videos.length}本</span>
              </div>
              <div className="produced-list">
                {videos.map((video) => {
                  const selected = video.video_id === activeVideo.video_id;
                  return (
                    <button
                      key={video.video_id}
                      type="button"
                      className={selected ? "produced-item is-selected" : "produced-item"}
                      aria-current={selected ? "true" : undefined}
                      onClick={() => selectVideo(video.video_id)}
                    >
                      <span className="thumb-wrap">
                        {video.poster_url ? (
                          <img src={video.poster_url} alt="" loading="lazy" />
                        ) : (
                          <span className="thumb-fallback">
                            <PlayIcon weight="fill" aria-hidden="true" />
                          </span>
                        )}
                        {video.duration_sec ? (
                          <span className="time-chip">{formatMinuteClock(video.duration_sec)}</span>
                        ) : null}
                      </span>
                      <span className="produced-copy">
                        <strong>{video.title}</strong>
                        <span className="produced-item-meta">
                          {video.published_at
                            ? formatDate(video.published_at, { year: "numeric", month: "numeric", day: "numeric" })
                            : "―"}
                          {video.chapters.length ? ` ・ チャプター${video.chapters.length}` : ""}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          </LayerCard.Primary>
        </LayerCard>
      </aside>
    </main>
  );
}
