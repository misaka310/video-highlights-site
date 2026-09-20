import type { PlaybackOptions, PlaybackRequest } from "./playback-types.js";

export function normalizeVodId(vodId: string): string {
  return String(vodId || "").trim().replace(/^v/i, "");
}

export function createVodSwitchPlaybackOptions(provider: PlaybackOptions["provider"]): PlaybackOptions {
  return {
    autoplay: false,
    muted: true,
    triggeredByUser: false,
    ...(provider ? { provider } : {}),
  };
}

export function createPlaybackRequest(
  requestId: number,
  vodId: string,
  startSec: number,
  options: PlaybackOptions = {},
): PlaybackRequest | null {
  const normalizedVodId = normalizeVodId(vodId);
  if (!normalizedVodId) return null;
  return {
    requestId: Math.max(1, Math.floor(Number(requestId) || 1)),
    vodId: normalizedVodId,
    startSec: Math.max(0, Math.floor(Number(startSec) || 0)),
    autoplay: options.autoplay !== false,
    muted: options.muted !== false,
    triggeredByUser: options.triggeredByUser === true,
    ...(options.provider ? { provider: options.provider } : {}),
  };
}
