import { useEffect, type RefObject } from "react";
import { attachHlsSource } from "../player/hls-video.js";
import { isHlsSource } from "../lib/video-source.js";

type UseHlsVideoOptions = {
  videoRef: RefObject<HTMLVideoElement | null>;
  url: string;
  onReady?: () => void;
  onError?: () => void;
};

/** HLSの再生系をvideoへ接続し、URLが変わるたびに作り直す。 */
export function useHlsVideo({ videoRef, url, onReady, onError }: UseHlsVideoOptions): void {
  useEffect(() => {
    const element = videoRef.current;
    if (!element || !isHlsSource(url)) return;
    const handle = attachHlsSource(element, url, { onReady, onError });
    return () => handle?.destroy();
  }, [onError, onReady, url, videoRef]);
}
