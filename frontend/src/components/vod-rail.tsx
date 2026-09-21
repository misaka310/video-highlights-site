import { useState } from "react";
import { LayerCard, Pagination, Tabs } from "@cloudflare/kumo";
import type { HighlightSegment, VodData } from "../domain/vod.js";
import { VOD_PAGE_SIZE } from "../domain/vod.js";
import type { AnosaStatement } from "../lib/captions.js";
import { formatDate } from "../lib/formatters.js";
import { AnosaList } from "./anosa-list.js";
import { HighlightList } from "./highlight-list.js";
import { StreamSummary } from "./stream-summary.js";

type VodRailProps = {
  vods: VodData[];
  activeVod: VodData;
  segments: HighlightSegment[];
  activeSegmentId: string;
  anosaStatements: AnosaStatement[];
  captionsAvailable: boolean;
  durationSec: number;
  playerState: string;
  positionSec: number;
  page: number;
  totalCount: number;
  onSelectVod: (vodId: string) => void;
  onSelectSegment: (segment: HighlightSegment) => void;
  onSelectAnosa: (statement: AnosaStatement) => void;
  onSetPage: (page: number) => void;
};

export function VodRail({
  vods,
  activeVod,
  segments,
  activeSegmentId,
  anosaStatements,
  captionsAvailable,
  durationSec,
  playerState,
  positionSec,
  page,
  totalCount,
  onSelectVod,
  onSelectSegment,
  onSelectAnosa,
  onSetPage,
}: VodRailProps) {
  const [contentTab, setContentTab] = useState<"highlights" | "anosa">("highlights");
  const tabItems = vods.map((vod) => ({
    value: vod.vod_id,
    label: formatDate(vod.published_at, { month: "numeric", day: "numeric", weekday: "short" }),
  }));

  return (
    <aside className="highlight-column" aria-label="VODと見どころ一覧">
      <LayerCard className="vod-list-card">
        <LayerCard.Primary>
          <div className="rail-content">
            <Tabs tabs={tabItems} value={activeVod.vod_id} onValueChange={onSelectVod} />
            <div className="content-tabs" role="tablist" aria-label="見どころ表示">
              <button
                type="button"
                role="tab"
                aria-selected={contentTab === "highlights"}
                className={contentTab === "highlights" ? "is-active" : ""}
                onClick={() => setContentTab("highlights")}
              >
                見どころ
                <span>{segments.length}</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={contentTab === "anosa"}
                className={contentTab === "anosa" ? "is-active" : ""}
                onClick={() => setContentTab("anosa")}
              >
                あのさ
                <span>{captionsAvailable ? anosaStatements.length : "—"}</span>
              </button>
            </div>

            {contentTab === "highlights" ? (
              <HighlightList
                vodId={activeVod.vod_id}
                provider={activeVod.provider}
                vodThumbnailUrl={activeVod.thumbnail_url}
                segments={segments}
                activeSegmentId={activeSegmentId}
                onSelect={onSelectSegment}
              />
            ) : (
              <AnosaList
                statements={anosaStatements}
                positionSec={positionSec}
                captionsAvailable={captionsAvailable}
                onSelect={onSelectAnosa}
              />
            )}
          </div>
        </LayerCard.Primary>
      </LayerCard>

      <LayerCard className="stream-summary-card">
        <LayerCard.Primary>
          <StreamSummary
            vod={activeVod}
            durationSec={durationSec}
            playerState={playerState}
            positionSec={positionSec}
          />
        </LayerCard.Primary>
      </LayerCard>

      <div className="pagination-wrap" aria-label="ページ移動">
        <Pagination
          page={page}
          perPage={VOD_PAGE_SIZE}
          totalCount={totalCount}
          setPage={onSetPage}
          controls="full"
        />
      </div>
    </aside>
  );
}
