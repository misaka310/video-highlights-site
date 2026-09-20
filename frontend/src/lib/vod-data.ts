import type { HighlightSegment, VodData, VodProvider } from "../domain/vod.js";

const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "youtu.be",
  "www.youtu.be",
]);

function isYouTubeUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && YOUTUBE_HOSTS.has(parsed.hostname.toLowerCase());
  } catch {
    return false;
  }
}

export function getVodProvider(vod: { vod_id?: string; provider?: string; vod_url?: string } | null | undefined): VodProvider {
  if (String(vod?.provider || "").trim().toLowerCase() === "youtube") return "youtube";
  if (isYouTubeUrl(String(vod?.vod_url || "").trim())) return "youtube";
  return "twitch";
}

export function normalizeDataPath(path: string): string {
  const value = String(path || "").trim();
  if (value.startsWith("/data/")) return value;
  if (value.startsWith("data/")) return `/${value}`;
  return `/data/${value.replace(/^\/+/, "")}`;
}

export function normalizeAssetPath(path = ""): string {
  const value = String(path || "").trim();
  if (/^https?:\/\//i.test(value)) return value;
  return normalizeDataPath(value);
}

export function orderSegments(items?: HighlightSegment[]): HighlightSegment[] {
  return [...(Array.isArray(items) ? items : [])]
    .sort((a, b) => Number(a.rank ?? a.start_sec) - Number(b.rank ?? b.start_sec));
}

export function resolveDurationSec(vod: VodData | null): number {
  const direct = Number(vod?.duration_sec);
  if (Number.isFinite(direct) && direct > 0) return direct;
  const activity = Number(vod?.activity_map?.duration_sec);
  if (Number.isFinite(activity) && activity > 0) return activity;
  return Math.max(0, ...orderSegments(vod?.items).map((segment) => Number(segment.end_sec) || 0));
}

export function parsePageSearch(search: string): number {
  const value = Number.parseInt(new URLSearchParams(search).get("page") || "1", 10);
  return Math.max(1, value || 1);
}

export function pageUrl(currentUrl: string, nextPage: number): string {
  const safePage = Math.max(1, Math.floor(Number(nextPage) || 1));
  const url = new URL(currentUrl);
  url.searchParams.set("page", String(safePage));
  return url.toString();
}
