import { PlayIcon } from "@phosphor-icons/react";
import { formatNextUpdate, formatUpdate } from "../lib/formatters.js";

type SiteHeaderProps = {
  siteName: string;
  updatedAt: string;
  nextUpdateAt: string;
  feedbackUrl?: string;
};

export function SiteHeader({ siteName, updatedAt, nextUpdateAt, feedbackUrl = "" }: SiteHeaderProps) {
  return (
    <header className="site-header">
      <div>
        <div className="brand-line">
          <PlayIcon weight="fill" aria-hidden="true" />
          <h1>{siteName}</h1>
        </div>
        <p>直近2ヶ月の配信の見どころをすぐ再生［非公式ファンサイト］</p>
      </div>
      <div className="update-stack" aria-label="更新情報">
        <span>データ更新: {formatUpdate(updatedAt)}</span>
        <span>次回更新予定: {formatNextUpdate(nextUpdateAt)}</span>
        {feedbackUrl ? (
          <a className="feedback-link" href={feedbackUrl} target="_blank" rel="noreferrer">
            要望・誤り報告はこちら
          </a>
        ) : null}
      </div>
    </header>
  );
}
