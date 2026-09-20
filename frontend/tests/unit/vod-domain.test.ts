import assert from "node:assert/strict";
import test from "node:test";
import {
  ACTIVITY_CHART_WIDTH,
  createActivityGeometry,
  createActivityOverlay,
  downsampleBuckets,
  smoothBuckets,
} from "../../src/lib/activity-geometry.js";
import { formatChatVolume, formatClock, localizeReason } from "../../src/lib/formatters.js";
import { resolveCaptionWindow } from "../../src/lib/captions.js";
import { loadVodPage } from "../../src/hooks/use-vod-page.js";
import { VOD_PAGE_SIZE } from "../../src/domain/vod.js";
import {
  normalizeDataPath,
  normalizeAssetPath,
  orderSegments,
  pageUrl,
  parsePageSearch,
  resolveDurationSec,
} from "../../src/lib/vod-data.js";

test("normalizes public data paths without changing canonical paths", () => {
  assert.equal(normalizeDataPath("/data/vods/1.json"), "/data/vods/1.json");
  assert.equal(normalizeDataPath("data/vods/1.json"), "/data/vods/1.json");
  assert.equal(normalizeDataPath("vods/1.json"), "/data/vods/1.json");
});

test("preserves remote thumbnail URLs for image fallbacks", () => {
  assert.equal(
    normalizeAssetPath("https://i.ytimg.com/vi/930HUhvRKHc/maxresdefault.jpg"),
    "https://i.ytimg.com/vi/930HUhvRKHc/maxresdefault.jpg",
  );
});

test("orders segments by rank and derives duration with existing precedence", () => {
  const ordered = orderSegments([
    { id: "third", rank: 3, start_sec: 30, end_sec: 40 },
    { id: "first", rank: 1, start_sec: 10, end_sec: 20 },
    { id: "second", rank: 2, start_sec: 20, end_sec: 30 },
  ]);
  assert.deepEqual(ordered.map((item) => item.id), ["first", "second", "third"]);
  assert.equal(resolveDurationSec({ vod_id: "1", title: "", published_at: "", duration_sec: 100 }), 100);
  assert.equal(resolveDurationSec({ vod_id: "1", title: "", published_at: "", activity_map: { duration_sec: 90 } }), 90);
  assert.equal(resolveDurationSec({ vod_id: "1", title: "", published_at: "", items: ordered }), 40);
});

test("preserves page navigation query behavior", () => {
  assert.equal(parsePageSearch("?page=2"), 2);
  assert.equal(parsePageSearch("?page=0"), 1);
  assert.equal(parsePageSearch("?page=invalid"), 1);
  assert.equal(pageUrl("https://example.test/?mode=preview&page=1", 3), "https://example.test/?mode=preview&page=3");
});

test("shows five YouTube VODs per page", () => {
  assert.equal(VOD_PAGE_SIZE, 5);
});

test("clamps out-of-range VOD pages to the last available page", async () => {
  const requestedPaths: string[] = [];
  const fetcher = async (input: string | URL | Request): Promise<Response> => {
    const path = String(input);
    requestedPaths.push(path);
    if (path === "/data/vod_index.json") {
      return Response.json({
        videos: [
          { provider: "twitch", vod_id: "legacy", detail_path: "data/vods/legacy.json", published_at: "2026-08-05T00:00:00Z" },
          { provider: "youtube", vod_id: "4", detail_path: "data/vods/4.json", published_at: "2026-08-04T00:00:00Z" },
          { provider: "youtube", vod_id: "3", detail_path: "data/vods/3.json", published_at: "2026-08-03T00:00:00Z" },
          { provider: "youtube", vod_id: "2", detail_path: "data/vods/2.json", published_at: "2026-08-02T00:00:00Z" },
          { provider: "youtube", vod_id: "1", detail_path: "data/vods/1.json", published_at: "2026-08-01T00:00:00Z" },
          { provider: "youtube", vod_id: "0", detail_path: "data/vods/0.json", published_at: "2026-07-31T00:00:00Z" },
          { provider: "youtube", vod_id: "-1", detail_path: "data/vods/-1.json", published_at: "2026-07-30T00:00:00Z" },
        ],
      });
    }
    if (path === "/site-config.json") return Response.json({ site: { name: "Example" } });
    if (path === "/data/vods/1.json") {
      return Response.json({ provider: "youtube", vod_id: "1", title: "last page", published_at: "2026-08-01T00:00:00Z" });
    }
    if (path === "/data/vods/0.json") {
      return Response.json({ provider: "youtube", vod_id: "0", title: "last page", published_at: "2026-07-31T00:00:00Z" });
    }
    if (path === "/data/vods/-1.json") {
      return Response.json({ provider: "youtube", vod_id: "-1", title: "last page", published_at: "2026-07-30T00:00:00Z" });
    }
    return new Response("not found", { status: 404 });
  };

  const result = await loadVodPage(99, fetcher as typeof fetch);

  assert.equal(result.requestedPage, 99);
  assert.equal(result.page, 2);
  assert.deepEqual(result.vods.map((vod) => vod.vod_id), ["-1"]);
  assert.equal(requestedPaths.includes("/data/vods/4.json"), false);
});

test("keeps the page usable when one VOD detail payload fails", async () => {
  const fetcher = async (input: string | URL | Request): Promise<Response> => {
    const path = String(input);
    if (path === "/data/vod_index.json") {
      return Response.json({
        videos: [
          { provider: "youtube", vod_id: "2", detail_path: "data/vods/2.json", published_at: "2026-08-02T00:00:00Z" },
          { provider: "youtube", vod_id: "1", detail_path: "data/vods/1.json", published_at: "2026-08-01T00:00:00Z" },
        ],
      });
    }
    if (path === "/site-config.json") return Response.json({ site: { name: "Example" } });
    if (path === "/data/vods/2.json") return new Response("not found", { status: 404 });
    if (path === "/data/vods/1.json") {
      return Response.json({ provider: "youtube", vod_id: "1", title: "healthy VOD", published_at: "2026-08-01T00:00:00Z" });
    }
    return new Response("not found", { status: 404 });
  };

  const result = await loadVodPage(1, fetcher as typeof fetch);

  assert.deepEqual(result.vods.map((vod) => vod.vod_id), ["1"]);
  assert.equal(result.totalCount, 2);
});

test("keeps only YouTube entries in the public page", async () => {
  const fetcher = async (input: string | URL | Request): Promise<Response> => {
    const path = String(input);
    if (path === "/data/vod_index.json") {
      return Response.json({
        videos: [
          { provider: "twitch", vod_id: "twitch-1", detail_path: "data/vods/twitch-1.json", published_at: "2026-08-03T00:00:00Z" },
          { provider: "youtube", vod_id: "youtube-1", detail_path: "data/vods/youtube-1.json", published_at: "2026-08-02T00:00:00Z" },
        ],
      });
    }
    if (path === "/site-config.json") return Response.json({});
    if (path === "/data/vods/twitch-1.json") {
      return Response.json({ provider: "twitch", vod_id: "twitch-1", title: "Twitch VOD", published_at: "2026-08-03T00:00:00Z" });
    }
    if (path === "/data/vods/youtube-1.json") {
      return Response.json({ provider: "youtube", vod_id: "youtube-1", title: "YouTube VOD", published_at: "2026-08-02T00:00:00Z" });
    }
    return new Response("not found", { status: 404 });
  };

  const result = await loadVodPage(1, fetcher as typeof fetch);

  assert.deepEqual(result.vods.map((vod) => vod.vod_id), ["youtube-1"]);
  assert.equal(result.totalCount, 1);
});

test("keeps display formatting and reason localization", () => {
  assert.equal(formatClock(3661.9), "01:01:01");
  assert.equal(localizeReason("Chat activity spike around 00:00:40 (z-score=4.2)."), "コメントが集中した場面");
  assert.equal(formatChatVolume({ vod_id: "1", title: "", published_at: "" }), "―");
  assert.equal(
    formatChatVolume({ vod_id: "1", title: "", published_at: "", chat_total: 1234, comments_per_hour: 56.7 }),
    "1,234件 / 時間あたり約57件",
  );
});

test("resolves previous current and next YouTube caption cues by playback position", () => {
  const cues = [
    { start_sec: 0, end_sec: 4.9, text: "前の字幕" },
    { start_sec: 5, end_sec: 9.9, text: "今の字幕" },
    { start_sec: 10, end_sec: 14.9, text: "次の字幕" },
  ];
  const active = resolveCaptionWindow(cues, 7);
  assert.equal(active.previous?.text, "前の字幕");
  assert.equal(active.current?.text, "今の字幕");
  assert.equal(active.next?.text, "次の字幕");

  const gap = resolveCaptionWindow(cues, 9.95);
  assert.equal(gap.previous?.text, "今の字幕");
  assert.equal(gap.current, null);
  assert.equal(gap.next?.text, "次の字幕");
});

test("creates responsive activity geometry without reading browser globals", () => {
  const buckets = Array.from({ length: 1000 }, (_, index) => index % 17);
  assert.equal(smoothBuckets([1, 3, 5], 1)[1], 3);
  assert.equal(downsampleBuckets(buckets, 120).length <= 120, true);

  const desktop = createActivityGeometry(buckets, false);
  const compact = createActivityGeometry(buckets, true);
  assert.ok(desktop);
  assert.ok(compact);
  const desktopPoints = (desktop.areaPath.match(/ L /g) || []).length - 1;
  const compactPoints = (compact.areaPath.match(/ L /g) || []).length - 1;
  assert.equal(desktopPoints <= 320, true);
  assert.equal(compactPoints <= 120, true);
});

test("calculates selected and unavailable activity ranges", () => {
  const overlay = createActivityOverlay({
    durationSec: 100,
    positionSec: 25,
    segmentStartSec: 20,
    segmentEndSec: 30,
    lastCommentSec: 80,
  });
  assert.equal(overlay.positionRatio, 0.25);
  assert.equal(overlay.segmentRangeX, ACTIVITY_CHART_WIDTH * 0.2);
  assert.equal(overlay.segmentRangeWidth, ACTIVITY_CHART_WIDTH * 0.1);
  assert.equal(overlay.unavailableX, ACTIVITY_CHART_WIDTH * 0.8);
  assert.equal(overlay.unavailableWidth, ACTIVITY_CHART_WIDTH * 0.2);
});
