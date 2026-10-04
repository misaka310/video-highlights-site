import { Empty } from "@cloudflare/kumo";
import { PlayIcon } from "@phosphor-icons/react";
import type { HighlightSegment } from "../domain/vod.js";
import { formatClock, resolveHighlightTitle } from "../lib/formatters.js";
import { normalizeAssetPath } from "../lib/vod-data.js";

type HighlightListProps = {
  vodId: string;
  provider?: "twitch" | "youtube";
  vodThumbnailUrl?: string;
  segments: HighlightSegment[];
  activeSegmentId: string;
  onSelect: (segment: HighlightSegment) => void;
};

export function HighlightList({ vodId, provider = "twitch", vodThumbnailUrl, segments, activeSegmentId, onSelect }: HighlightListProps) {
  return (
    <div className="highlight-list">
      {segments.length > 0 ? segments.map((segment) => {
        const selected = segment.id === activeSegmentId;
        const title = resolveHighlightTitle(segment.headline, segment.reason, provider);
        const thumbnailUrl = segment.screenshot_url || vodThumbnailUrl;
        return (
          <button
            key={segment.id}
            type="button"
            className={`highlight-item${selected ? " is-selected" : ""}`}
            data-vod-id={vodId}
            data-start-sec={segment.start_sec}
            aria-pressed={selected}
            onClick={() => onSelect(segment)}
          >
            <span className="thumb-wrap">
              {thumbnailUrl ? (
                <img src={normalizeAssetPath(thumbnailUrl)} alt="" loading="lazy" />
              ) : (
                <span className="thumb-fallback"><PlayIcon weight="fill" /></span>
              )}
              <span className="time-chip">{segment.start_time || formatClock(segment.start_sec)}</span>
            </span>
            <span className="highlight-copy">
              <strong>{title}</strong>
            </span>
          </button>
        );
      }) : <Empty title="見どころなし" description="この配信には表示できる見どころがありません。" />}
    </div>
  );
}
