import type { CaptionWindow } from "../lib/captions.js";

type CaptionPanelProps = {
  window: CaptionWindow;
};

function CaptionLine({
  label,
  text,
  current = false,
}: {
  label: string;
  text: string;
  current?: boolean;
}) {
  return (
    <div className={current ? "caption-line caption-line--current" : "caption-line"}>
      <span className="caption-label">{label}</span>
      <span className="caption-text">{text || "―"}</span>
    </div>
  );
}

export function CaptionPanel({ window }: CaptionPanelProps) {
  if (!window.previous && !window.current && !window.next) return null;

  return (
    <section className="caption-panel" aria-label="文字起こし">
      <div className="caption-head">
        <strong>文字起こし</strong>
        <span>YouTube字幕</span>
      </div>
      <div className="caption-lines">
        <CaptionLine label="前" text={window.previous?.text || ""} />
        <CaptionLine label="今" text={window.current?.text || ""} current />
        <CaptionLine label="次" text={window.next?.text || ""} />
      </div>
    </section>
  );
}
