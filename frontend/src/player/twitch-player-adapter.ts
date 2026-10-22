export type TwitchPlayerInstance = {
  addEventListener?: (eventName: string, callback: () => void) => void;
  destroy?: () => void;
  getCurrentTime?: () => number;
  pause?: () => void;
  play?: () => void | Promise<void>;
  seek?: (seconds: number) => void;
  setMuted?: (muted: boolean) => void;
};

export type TwitchPlayerConstructor = {
  new (element: HTMLElement, options: Record<string, unknown>): TwitchPlayerInstance;
  READY?: string;
  PLAY?: string;
  PLAYING?: string;
  PAUSE?: string;
  ENDED?: string;
  PLAYBACK_BLOCKED?: string;
};

export function safePlay(player: TwitchPlayerInstance | null): void {
  if (!player?.play) return;
  try {
    const result = player.play();
    if (result && typeof result.catch === "function") result.catch(() => undefined);
  } catch {
    // Browser autoplay policy can reject playback even after initialization.
  }
}

export function safePause(player: TwitchPlayerInstance | null): void {
  if (!player?.pause) return;
  try {
    player.pause();
  } catch {
    // Ignore transient SDK errors during player initialization.
  }
}

export function safeSetMuted(player: TwitchPlayerInstance | null, muted: boolean): void {
  if (!player?.setMuted) return;
  try {
    player.setMuted(muted);
  } catch {
    // Ignore transient SDK errors during player initialization.
  }
}

export function safeSeek(player: TwitchPlayerInstance | null, seconds: number): void {
  if (!player?.seek) return;
  try {
    player.seek(Math.max(0, seconds));
  } catch {
    // Ignore transient SDK errors during player initialization.
  }
}

export function addPlayerListener(
  player: TwitchPlayerInstance,
  eventName: string | undefined,
  callback: () => void,
): void {
  if (!eventName || typeof player.addEventListener !== "function") return;
  player.addEventListener(eventName, callback);
}

export function destroyPlayer(player: TwitchPlayerInstance | null): void {
  if (!player) return;
  try {
    player.pause?.();
  } catch {
    // Ignore cleanup errors.
  }
  try {
    player.destroy?.();
  } catch {
    // Ignore cleanup errors.
  }
}
