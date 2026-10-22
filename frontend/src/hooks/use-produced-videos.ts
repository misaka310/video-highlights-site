import { useEffect, useState } from "react";
import type { ProducedVideo } from "../domain/vod.js";
import { isVideoAvailable, normalizeProducedVideos } from "../lib/produced-videos.js";

const PRODUCED_VIDEO_PATH = "/data/produced_videos.json";

export function useProducedVideos(): { videos: ProducedVideo[] } {
  const [videos, setVideos] = useState<ProducedVideo[]>([]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const response = await fetch(PRODUCED_VIDEO_PATH, { cache: "no-store" });
        if (!response.ok) return;
        const normalized = normalizeProducedVideos(await response.json());
        const available = await Promise.all(
          normalized.map(async (video) => ((await isVideoAvailable(video)) ? video : null)),
        );
        if (!cancelled) setVideos(available.filter((video): video is ProducedVideo => video !== null));
      } catch {
        // 制作動画がない環境では導線自体を出さない。
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return { videos };
}
