import { Empty } from "@cloudflare/kumo";
import { QuotesIcon } from "@phosphor-icons/react";
import type { AnosaStatement } from "../lib/captions.js";
import { formatClock } from "../lib/formatters.js";

type AnosaListProps = {
  phrase: "あのさ" | "あのね";
  statements: AnosaStatement[];
  positionSec: number;
  captionsAvailable: boolean;
  onSelect: (statement: AnosaStatement) => void;
};

export function AnosaList({ phrase, statements, positionSec, captionsAvailable, onSelect }: AnosaListProps) {
  if (!captionsAvailable) {
    return <Empty title="字幕なし" description="この配信ではYouTube字幕を取得できていません。" />;
  }

  if (statements.length === 0) {
    return <Empty title={`「${phrase}」なし`} description={`この配信では「${phrase}」は検出されませんでした。`} />;
  }

  return (
    <div className="anosa-list">
      <div className="anosa-list-head">
        <span>字幕から抽出</span>
        <strong>{statements.length}件</strong>
      </div>
      {statements.map((statement) => {
        const selected = positionSec >= statement.start_sec && positionSec <= statement.end_sec + 1.5;
        return (
          <button
            key={`${statement.start_sec}-${statement.end_sec}-${statement.text}`}
            type="button"
            className={`anosa-item${selected ? " is-selected" : ""}`}
            data-start-sec={statement.start_sec}
            aria-pressed={selected}
            onClick={() => onSelect(statement)}
          >
            <span className="anosa-time">
              <QuotesIcon weight="fill" />
              {formatClock(statement.start_sec)}
            </span>
            <span className="anosa-transcript">
              {statement.text}
              {statement.boundary_split ? <span className="phrase-marker">字幕境界</span> : null}
              {statement.partial ? <span className="phrase-marker">字幕断片</span> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}
