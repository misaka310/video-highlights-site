import { ArrowLeftIcon, PlayIcon } from "@phosphor-icons/react";
import { formatMinuteClock, formatNextUpdate, formatUpdate } from "../lib/formatters.js";

type HeaderNav = {
  icon: "play" | "back";
  label: string;
  count?: number;
  durationSec?: number;
  onClick: () => void;
};

type SiteHeaderProps = {
  siteName: string;
  updatedAt: string;
  nextUpdateAt: string;
  feedbackUrl?: string;
  nav?: HeaderNav;
};

export function SiteHeader({ siteName, updatedAt, nextUpdateAt, feedbackUrl = "", nav }: SiteHeaderProps) {
  return (
    <header className="site-header">
      <div>
        <div className="brand-line">
          <PlayIcon weight="fill" aria-hidden="true" />
          <h1>{siteName}</h1>
        </div>
        <p>直近2ヶ月の配信の見どころをすぐ再生［非公式ファンサイト］</p>
      </div>
      <div className="header-side">
        {nav ? (
          <button type="button" className="nav-pill" onClick={nav.onClick}>
            {nav.icon === "play" ? (
              <PlayIcon weight="fill" aria-hidden="true" />
            ) : (
              <ArrowLeftIcon weight="bold" aria-hidden="true" />
            )}
            <span>{nav.label}</span>
            {nav.count ? <span className="nav-pill-count">{nav.count}本</span> : null}
            {nav.durationSec ? <span className="nav-pill-count">{formatMinuteClock(nav.durationSec)}</span> : null}
          </button>
        ) : null}
        <div className="update-stack" aria-label="更新情報">
          <span>データ更新: {formatUpdate(updatedAt)}</span>
          <span>次回更新予定: {formatNextUpdate(nextUpdateAt)}</span>
          {feedbackUrl ? (
            <a className="feedback-link" href={feedbackUrl} target="_blank" rel="noreferrer">
              要望・誤り報告はこちら
            </a>
          ) : null}
        </div>
      </div>
    </header>
  );
}
