import type { VodData, VodProvider } from "../domain/vod.js";

export function formatClock(totalSeconds: number): string {
  const total = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = String(Math.floor(total / 3600)).padStart(2, "0");
  const minutes = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const seconds = String(total % 60).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

export function formatDate(value: string, options: Intl.DateTimeFormatOptions): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "―";
  return new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", ...options }).format(date);
}

export function formatUpdate(value: string): string {
  return formatDate(value, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatNextUpdate(value: string, now = new Date()): string {
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) return "―";

  const elapsed = now.getTime() - target.getTime();
  if (elapsed >= 0) {
    const dailyIntervalMs = 24 * 60 * 60 * 1000;
    const intervals = Math.floor(elapsed / dailyIntervalMs) + 1;
    target.setTime(target.getTime() + intervals * dailyIntervalMs);
  }

  return formatUpdate(target.toISOString());
}

export function localizeReason(reason = ""): string {
  const text = String(reason).trim();
  const match = text.match(/^Chat activity spike around (.+?) \(z-score=[^)]+\)\.?$/i);
  if (match) return "コメントが集中した場面";
  return text
    .replace(/^\d+h\d+m\d+s\s*/i, "")
    .replace(/\s*\(z-score=[^)]+\)\.?/gi, "")
    .trim();
}

export function resolveHighlightTitle(
  headline: string | undefined,
  reason: string | undefined,
  provider: VodProvider,
): string {
  const normalizedHeadline = String(headline || "").trim();
  if (normalizedHeadline) return normalizedHeadline;
  if (provider === "youtube") return "コメントが集中した場面";
  return localizeReason(reason || "") || "見どころ";
}

export function formatChatVolume(vod: VodData): string {
  if (vod.chat_total == null || vod.comments_per_hour == null) return "―";
  const chatTotal = Number(vod.chat_total);
  const commentsPerHour = Number(vod.comments_per_hour);
  if (!Number.isFinite(chatTotal) || chatTotal < 0 || !Number.isFinite(commentsPerHour) || commentsPerHour < 0) {
    return "―";
  }
  return `${Math.floor(chatTotal).toLocaleString("ja-JP")}件 / 時間あたり約${Math.round(commentsPerHour).toLocaleString("ja-JP")}件`;
}
