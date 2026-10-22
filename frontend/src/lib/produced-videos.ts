import type { ProducedVideo, ProducedVideoChapter } from "../domain/vod.js";
import { normalizeAssetPath } from "./vod-data.js";

function normalizeString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeVideoUrl(value: string): string {
  if (/^https?:\/\//i.test(value)) return value;
  if (value.startsWith("/")) return value;
  return `/${value.replace(/^\.?\/*/, "")}`;
}

export function isSameOriginAsset(url: string): boolean {
  return !/^https?:\/\//i.test(url);
}

function normalizeChapters(value: unknown): ProducedVideoChapter[] {
  if (!Array.isArray(value)) return [];
  const chapters: ProducedVideoChapter[] = [];
  for (const raw of value) {
    if (!raw || typeof raw !== "object") continue;
    const entry = raw as Record<string, unknown>;
    const startSec = Number(entry.start_sec);
    const label = normalizeString(entry.label);
    if (!Number.isFinite(startSec) || startSec < 0 || !label) continue;
    chapters.push({ start_sec: Math.floor(startSec), label });
  }
  chapters.sort((a, b) => a.start_sec - b.start_sec);
  return chapters.filter((chapter, index) => index === 0 || chapter.start_sec !== chapters[index - 1].start_sec);
}

export function normalizeProducedVideos(payload: unknown): ProducedVideo[] {
  const videos = (payload as { videos?: unknown } | null | undefined)?.videos;
  if (!Array.isArray(videos)) return [];
  const normalized: ProducedVideo[] = [];
  for (const raw of videos) {
    if (!raw || typeof raw !== "object") continue;
    const entry = raw as Record<string, unknown>;
    const videoId = normalizeString(entry.video_id);
    const title = normalizeString(entry.title);
    const videoUrl = normalizeString(entry.video_url);
    if (!videoId || !title || !videoUrl) continue;
    const duration = Number(entry.duration_sec);
    const poster = normalizeString(entry.poster_url);
    normalized.push({
      video_id: videoId,
      title,
      description: normalizeString(entry.description),
      credits: normalizeString(entry.credits),
      duration_sec: Number.isFinite(duration) && duration > 0 ? duration : undefined,
      published_at: normalizeString(entry.published_at),
      poster_url: poster ? normalizeAssetPath(poster) : "",
      video_url: normalizeVideoUrl(videoUrl),
      chapters: normalizeChapters(entry.chapters),
    });
  }
  return normalized;
}

export function findProducedVideo(videos: ProducedVideo[], videoId: string): ProducedVideo | null {
  if (!videoId) return null;
  return videos.find((video) => video.video_id === videoId) || null;
}

export function currentChapterIndex(chapters: ProducedVideoChapter[], positionSec: number): number {
  let index = -1;
  for (let cursor = 0; cursor < chapters.length; cursor += 1) {
    if (chapters[cursor].start_sec <= positionSec) index = cursor;
    else break;
  }
  return index;
}

export async function isVideoAvailable(video: ProducedVideo, fetcher: typeof fetch = fetch): Promise<boolean> {
  if (!isSameOriginAsset(video.video_url)) return true;
  try {
    const response = await fetcher(video.video_url, { method: "HEAD", cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}
