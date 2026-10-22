import Hls from "hls.js";

export function supportsNativeHls(video: HTMLVideoElement): boolean {
  if (typeof video.canPlayType !== "function") return false;
  return video.canPlayType("application/vnd.apple.mpegurl") !== "";
}

export type HlsHandle = { destroy: () => void };

export type HlsHandlers = {
  onReady?: () => void;
  onError?: () => void;
};

/** HLSを再生できる形でvideoへ接続する。ネイティブ再生（Safari）や非HLSではnullを返す。 */
export function attachHlsSource(video: HTMLVideoElement, url: string, handlers: HlsHandlers = {}): HlsHandle | null {
  if (supportsNativeHls(video)) {
    video.src = url;
    return null;
  }
  if (!Hls.isSupported()) {
    handlers.onError?.();
    return null;
  }

  const hls = new Hls({ enableWorker: true });
  hls.on(Hls.Events.MANIFEST_PARSED, () => handlers.onReady?.());
  hls.on(Hls.Events.ERROR, (_event, data) => {
    if (data?.fatal) handlers.onError?.();
  });
  hls.loadSource(url);
  hls.attachMedia(video);
  return {
    destroy: () => {
      hls.destroy();
      video.removeAttribute("src");
      video.load();
    },
  };
}
