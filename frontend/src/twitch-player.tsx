import { forwardRef, useImperativeHandle, useRef } from "react";
import { useInteractivePlayer } from "./hooks/use-interactive-player.js";
import { usePlayerPortal } from "./hooks/use-player-portal.js";
import type { PlaybackOptions, PlaybackStatus } from "./player/playback-types.js";

export type TwitchPlayerHandle = {
  requestPlayback: (vodId: string, startSec: number, options?: PlaybackOptions) => void;
  getCurrentTime: (options?: { preferPendingSeek?: boolean }) => number | null;
  pause: () => void;
};

type TwitchPlayerProps = {
  onPositionChange: (seconds: number) => void;
  onStatusChange: (label: string, status: PlaybackStatus) => void;
};

export const TwitchPlayer = forwardRef<TwitchPlayerHandle, TwitchPlayerProps>(function TwitchPlayer(
  { onPositionChange, onStatusChange },
  ref,
) {
  const frameRef = useRef<HTMLDivElement>(null);
  const hostRef = usePlayerPortal(frameRef);
  const controller = useInteractivePlayer({
    frameRef,
    hostRef,
    onPositionChange,
    onStatusChange,
  });

  useImperativeHandle(ref, () => controller);

  return (
    <div
      id="player-frame"
      ref={frameRef}
      className="player-frame"
      data-player-status="idle"
      data-current-vod-id=""
      data-current-start-sec=""
      data-player-provider="twitch"
      data-player-mode=""
      data-expected-autoplay="false"
      data-expected-muted="true"
      data-triggered-by-user="false"
    >
      <span className="sr-only" aria-live="polite">動画プレイヤー</span>
    </div>
  );
});
