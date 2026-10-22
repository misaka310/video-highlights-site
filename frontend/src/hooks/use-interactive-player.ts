import { useEffect, useRef, type RefObject } from "react";
import { usePositionPolling } from "./use-position-polling.js";
import { decideMountContinuation, decidePlayback } from "../player/playback-decision.js";
import { mountFallbackIframe as replaceWithFallbackIframe } from "../player/iframe-fallback.js";
import { createPlaybackRequest } from "../player/playback-request.js";
import type { PlaybackOptions, PlaybackRequest, PlaybackStatus } from "../player/playback-types.js";
import {
  addPlayerListener,
  destroyPlayer,
  safePause,
  safePlay,
  safeSeek,
  safeSetMuted,
  type TwitchPlayerInstance,
} from "../player/twitch-player-adapter.js";
import { ensurePlayerScript, getTwitchPlayerConstructor } from "../player/twitch-sdk-loader.js";
import { formatTwitchTime, getTwitchParents } from "../player/twitch-url.js";
import { createYoutubePlayerAdapter } from "../player/youtube-player-adapter.js";
import { ensureYoutubePlayerScript, getYoutubePlayerConstructor } from "../player/youtube-sdk-loader.js";

const INTERACTIVE_SEEK_STABILIZE_MS = 2500;

export type InteractivePlayerController = {
  requestPlayback: (vodId: string, startSec: number, options?: PlaybackOptions) => void;
  getCurrentTime: (options?: { preferPendingSeek?: boolean }) => number | null;
  pause: () => void;
};

type UseInteractivePlayerOptions = {
  frameRef: RefObject<HTMLDivElement | null>;
  hostRef: RefObject<HTMLDivElement | null>;
  onPositionChange: (seconds: number) => void;
  onStatusChange: (label: string, status: PlaybackStatus) => void;
};

export function useInteractivePlayer({
  frameRef,
  hostRef,
  onPositionChange,
  onStatusChange,
}: UseInteractivePlayerOptions): InteractivePlayerController {
  const playerRef = useRef<TwitchPlayerInstance | null>(null);
  const desiredRef = useRef<PlaybackRequest | null>(null);
  const requestSequenceRef = useRef(0);
  const mountInFlightRef = useRef(false);
  const mountVodIdRef = useRef("");
  const mountProviderRef = useRef<"twitch" | "youtube">("twitch");
  const playerVodIdRef = useRef("");
  const playerProviderRef = useRef<"twitch" | "youtube">("twitch");
  const playerReadyRef = useRef(false);
  const lastKnownPositionRef = useRef(0);
  const lastSeekTargetRef = useRef<number | null>(null);
  const lastSeekAtRef = useRef(0);

  const setUiState = (
    status: PlaybackStatus,
    request: PlaybackRequest | null,
    label: string,
    mode: "iframe" | "interactive" | "",
  ) => {
    const frame = frameRef.current;
    if (frame) {
      frame.dataset.playerStatus = status;
      frame.dataset.currentVodId = request?.vodId || "";
      frame.dataset.playerProvider = request?.provider || "twitch";
      frame.dataset.currentStartSec = request ? String(request.startSec) : "";
      frame.dataset.playerMode = mode;
      frame.dataset.expectedAutoplay = String(request?.autoplay === true);
      frame.dataset.expectedMuted = String(request?.muted === true);
      frame.dataset.triggeredByUser = String(request?.triggeredByUser === true);
    }
    onStatusChange(label, status);
  };

  const getCurrentTime = (options: { preferPendingSeek?: boolean } = {}): number | null => {
    if (options.preferPendingSeek && lastSeekTargetRef.current != null) {
      const seekAge = Date.now() - lastSeekAtRef.current;
      if (seekAge >= 0 && seekAge <= INTERACTIVE_SEEK_STABILIZE_MS) {
        return lastSeekTargetRef.current;
      }
    }
    const player = playerRef.current;
    if (player?.getCurrentTime) {
      try {
        const current = Number(player.getCurrentTime());
        if (Number.isFinite(current) && current >= 0) return current;
      } catch {
        // Fall back to the last known position.
      }
    }
    return Number.isFinite(lastKnownPositionRef.current) ? lastKnownPositionRef.current : null;
  };

  const pause = () => {
    safePause(playerRef.current);
  };

  const syncCurrentTime = () => {
    const current = getCurrentTime();
    if (current == null) return;
    const seekTarget = lastSeekTargetRef.current;
    const seekAge = Date.now() - lastSeekAtRef.current;
    if (
      seekTarget != null
      && seekAge >= 0
      && seekAge <= INTERACTIVE_SEEK_STABILIZE_MS
      && Math.abs(current - seekTarget) > 5
    ) {
      return;
    }
    if (
      seekTarget != null
      && (seekAge > INTERACTIVE_SEEK_STABILIZE_MS || Math.abs(current - seekTarget) <= 6)
    ) {
      lastSeekTargetRef.current = null;
      lastSeekAtRef.current = 0;
    }
    const floored = Math.max(0, Math.floor(current));
    lastKnownPositionRef.current = floored;
    const frame = frameRef.current;
    if (frame) frame.dataset.currentStartSec = String(floored);
    onPositionChange(floored);
  };

  const { startPolling, stopPolling } = usePositionPolling(syncCurrentTime);

  const destroyInteractivePlayer = () => {
    stopPolling();
    playerReadyRef.current = false;
    playerVodIdRef.current = "";
    playerProviderRef.current = "twitch";
    mountProviderRef.current = "twitch";
    const player = playerRef.current;
    playerRef.current = null;
    destroyPlayer(player);
  };

  const mountFallbackIframe = (request: PlaybackRequest) => {
    const host = hostRef.current;
    if (!host) return;
    replaceWithFallbackIframe({
      host,
      request,
      hostname: location.hostname,
      onLoaded: () => {
        if (desiredRef.current?.requestId !== request.requestId || playerReadyRef.current) return;
        setUiState(
          "ready",
          request,
          request.autoplay ? "再生準備完了" : "待機中",
          "iframe",
        );
      },
    });
  };

  const seekInteractivePlayer = (request: PlaybackRequest) => {
    const player = playerRef.current;
    const provider = request.provider || "twitch";
    if (
      !player
      || !playerReadyRef.current
      || playerVodIdRef.current !== request.vodId
      || playerProviderRef.current !== provider
    ) return false;
    safeSetMuted(player, request.muted);
    lastSeekTargetRef.current = request.startSec;
    lastSeekAtRef.current = Date.now();
    lastKnownPositionRef.current = request.startSec;
    safeSeek(player, request.startSec);
    onPositionChange(request.startSec);
    setUiState(
      "ready",
      request,
      request.autoplay ? "再生準備完了" : "待機中",
      "interactive",
    );
    if (request.autoplay) safePlay(player);
    window.setTimeout(syncCurrentTime, 180);
    window.setTimeout(syncCurrentTime, 520);
    window.setTimeout(syncCurrentTime, 1100);
    return true;
  };

  const mountYoutubeInteractivePlayer = async (request: PlaybackRequest): Promise<void> => {
    if (mountInFlightRef.current) return;
    mountInFlightRef.current = true;
    mountVodIdRef.current = request.vodId;
    mountProviderRef.current = "youtube";

    const scriptLoaded = await ensureYoutubePlayerScript();
    const latestAfterLoad = desiredRef.current;
    const PlayerClass = getYoutubePlayerConstructor();
    if (!scriptLoaded || !PlayerClass) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      if (latestAfterLoad?.provider === "youtube") {
        setUiState("error", latestAfterLoad, "YouTubeプレイヤーを読み込めませんでした", "");
      }
      return;
    }

    const continuation = decideMountContinuation(request, latestAfterLoad);
    if (continuation === "stop") {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      return;
    }
    if (continuation === "restart" && latestAfterLoad) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      void mountYoutubeInteractivePlayer(latestAfterLoad);
      return;
    }

    destroyInteractivePlayer();
    const host = hostRef.current;
    if (!host) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      return;
    }

    const inner = document.createElement("div");
    inner.className = "player-embed-slot";
    host.replaceChildren(inner);

    let player: TwitchPlayerInstance | null = null;
    const rawPlayer = new PlayerClass(inner, {
      videoId: request.vodId,
      playerVars: {
        autoplay: request.autoplay ? 1 : 0,
        controls: 1,
        playsinline: 1,
        start: request.startSec,
        origin: location.origin,
      },
      events: {
        onReady: () => {
          if (playerRef.current !== player) return;
          playerReadyRef.current = true;
          mountInFlightRef.current = false;
          mountVodIdRef.current = "";
          mountProviderRef.current = "youtube";
          startPolling();

          const latest = desiredRef.current;
          if (!latest) return;
          if (latest.vodId !== request.vodId || (latest.provider || "twitch") !== "youtube") {
            destroyInteractivePlayer();
            void mountInteractivePlayer(latest);
            return;
          }

          safeSetMuted(player, latest.muted);
          lastKnownPositionRef.current = latest.startSec;
          if (latest.startSec !== request.startSec) {
            seekInteractivePlayer(latest);
            return;
          }
          onPositionChange(latest.startSec);
          setUiState(
            "ready",
            latest,
            latest.autoplay ? "再生準備完了" : "待機中",
            "interactive",
          );
          if (latest.autoplay) safePlay(player);
        },
        onStateChange: (event) => {
          if (playerRef.current !== player) return;
          if (event.data === 1) setUiState("playing", desiredRef.current, "再生中", "interactive");
          if (event.data === 2 || event.data === 0) setUiState("ready", desiredRef.current, "待機中", "interactive");
        },
        onError: () => {
          if (playerRef.current !== player) return;
          mountInFlightRef.current = false;
          mountVodIdRef.current = "";
          mountProviderRef.current = "twitch";
          setUiState("error", desiredRef.current, "YouTubeプレイヤーでエラーが発生しました", "interactive");
        },
      },
    });
    player = createYoutubePlayerAdapter(rawPlayer);
    playerRef.current = player;
    playerVodIdRef.current = request.vodId;
    playerProviderRef.current = "youtube";
    playerReadyRef.current = false;
  };

  const mountInteractivePlayer = async (request: PlaybackRequest): Promise<void> => {
    if (request.provider === "youtube") {
      await mountYoutubeInteractivePlayer(request);
      return;
    }
    if (mountInFlightRef.current) return;
    mountInFlightRef.current = true;
    mountVodIdRef.current = request.vodId;
    mountProviderRef.current = "twitch";

    const scriptLoaded = await ensurePlayerScript();
    const latestAfterLoad = desiredRef.current;
    const PlayerClass = getTwitchPlayerConstructor();
    if (!scriptLoaded || !PlayerClass) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      if (latestAfterLoad) setUiState("ready", latestAfterLoad, "プレイヤー準備完了", "iframe");
      return;
    }
    const continuation = decideMountContinuation(request, latestAfterLoad);
    if (continuation === "stop") {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      return;
    }
    if (continuation === "restart" && latestAfterLoad) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      void mountInteractivePlayer(latestAfterLoad);
      return;
    }

    destroyInteractivePlayer();
    const host = hostRef.current;
    if (!host) {
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      return;
    }

    const inner = document.createElement("div");
    inner.className = "player-embed-slot";
    host.replaceChildren(inner);

    const player = new PlayerClass(inner, {
      width: "100%",
      height: "100%",
      video: request.vodId,
      parent: getTwitchParents(location.hostname),
      autoplay: request.autoplay,
      muted: request.muted,
      time: formatTwitchTime(request.startSec),
      playsinline: true,
    });

    playerRef.current = player;
    playerVodIdRef.current = request.vodId;
    playerProviderRef.current = "twitch";
    playerReadyRef.current = false;

    const readyEvent = PlayerClass.READY || "ready";
    const playEvent = PlayerClass.PLAY || "play";
    const playingEvent = PlayerClass.PLAYING || "playing";
    const pauseEvent = PlayerClass.PAUSE || "pause";
    const endedEvent = PlayerClass.ENDED || "ended";
    const blockedEvent = PlayerClass.PLAYBACK_BLOCKED || "playback_blocked";

    addPlayerListener(player, readyEvent, () => {
      if (playerRef.current !== player) return;
      playerReadyRef.current = true;
      mountInFlightRef.current = false;
      mountVodIdRef.current = "";
      mountProviderRef.current = "twitch";
      startPolling();

      const latest = desiredRef.current;
      if (!latest) return;
      if (latest.vodId !== request.vodId || (latest.provider || "twitch") !== "twitch") {
        if ((latest.provider || "twitch") === "twitch") mountFallbackIframe(latest);
        void mountInteractivePlayer(latest);
        return;
      }

      safeSetMuted(player, latest.muted);
      lastKnownPositionRef.current = latest.startSec;
      if (latest.startSec !== request.startSec) {
        seekInteractivePlayer(latest);
        return;
      }
      onPositionChange(latest.startSec);
      setUiState(
        "ready",
        latest,
        latest.autoplay ? "再生準備完了" : "待機中",
        "interactive",
      );
      if (latest.autoplay) safePlay(player);
    });

    addPlayerListener(player, playEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("playing", desiredRef.current, "再生中", "interactive");
    });
    if (playingEvent !== playEvent) {
      addPlayerListener(player, playingEvent, () => {
        if (playerRef.current !== player) return;
        setUiState("playing", desiredRef.current, "再生中", "interactive");
      });
    }
    addPlayerListener(player, pauseEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("ready", desiredRef.current, "待機中", "interactive");
    });
    addPlayerListener(player, endedEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("ready", desiredRef.current, "待機中", "interactive");
    });
    addPlayerListener(player, blockedEvent, () => {
      if (playerRef.current !== player) return;
      setUiState("blocked", desiredRef.current, "再生がブロックされました", "interactive");
    });
  };

  const requestPlayback = (vodId: string, startSec: number, options: PlaybackOptions = {}) => {
    const request = createPlaybackRequest(requestSequenceRef.current + 1, vodId, startSec, options);
    if (!request) return;
    requestSequenceRef.current = request.requestId;

    desiredRef.current = request;
    lastKnownPositionRef.current = request.startSec;
    onPositionChange(request.startSec);
    setUiState(
      "loading",
      request,
      request.triggeredByUser ? "再生を開始中" : "プレイヤー読込中",
      playerReadyRef.current ? "interactive" : "iframe",
    );

    const decision = decidePlayback(request, {
      playerReady: playerReadyRef.current,
      playerVodId: playerVodIdRef.current,
      mountInFlight: mountInFlightRef.current,
      mountVodId: mountVodIdRef.current,
      hasInteractivePlayer: playerRef.current != null,
      playerProvider: playerProviderRef.current,
      mountProvider: mountProviderRef.current,
    });
    if (decision.seekInteractive && seekInteractivePlayer(request)) return;
    if (decision.mountFallback && (request.provider || "twitch") === "twitch") mountFallbackIframe(request);
    if (decision.waitForMount) return;
    if (decision.destroyInteractive) destroyInteractivePlayer();
    if (decision.mountInteractive) void mountInteractivePlayer(request);
  };

  useEffect(() => () => destroyInteractivePlayer(), []); // eslint-disable-line react-hooks/exhaustive-deps -- controller cleanup runs only on unmount

  return { requestPlayback, getCurrentTime, pause };
}
