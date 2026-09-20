import assert from "node:assert/strict";
import test from "node:test";
import { decideMountContinuation, decidePlayback } from "../../src/player/playback-decision.js";
import { createPlaybackRequest, createVodSwitchPlaybackOptions, normalizeVodId } from "../../src/player/playback-request.js";
import { buildEmbedUrl, formatTwitchTime, getTwitchParents } from "../../src/player/twitch-url.js";
import { getVodProvider } from "../../src/lib/vod-data.js";

function request(id = 1, vodId = "123") {
  const value = createPlaybackRequest(id, vodId, 42.9);
  assert.ok(value);
  return value;
}

test("normalizes playback requests with the existing defaults", () => {
  assert.equal(normalizeVodId("v123"), "123");
  assert.equal(createPlaybackRequest(4, "", 10), null);
  assert.deepEqual(createPlaybackRequest(4, "v123", -5), {
    requestId: 4,
    vodId: "123",
    startSec: 0,
    autoplay: true,
    muted: true,
    triggeredByUser: false,
  });
  assert.deepEqual(createPlaybackRequest(5, "123", 9.8, {
    autoplay: false,
    muted: false,
    triggeredByUser: true,
  }), {
    requestId: 5,
    vodId: "123",
    startSec: 9,
    autoplay: false,
    muted: false,
    triggeredByUser: true,
  });
});

test("keeps provider identity in explicit YouTube playback requests", () => {
  assert.equal(getVodProvider({ vod_id: "WGTrmrSvZH0", vod_url: "https://www.youtube.com/watch?v=WGTrmrSvZH0" }), "youtube");
  assert.equal(getVodProvider({ vod_id: "123", vod_url: "https://www.twitch.tv/videos/123" }), "twitch");
  assert.deepEqual(createPlaybackRequest(6, "WGTrmrSvZH0", 12, { provider: "youtube" }), {
    requestId: 6,
    vodId: "WGTrmrSvZH0",
    startSec: 12,
    autoplay: true,
    muted: true,
    triggeredByUser: false,
    provider: "youtube",
  });
});

test("keeps date changes paused until the user selects a playback target", () => {
  assert.deepEqual(createVodSwitchPlaybackOptions("youtube"), {
    autoplay: false,
    muted: true,
    triggeredByUser: false,
    provider: "youtube",
  });
});

test("does not classify an untrusted host containing a YouTube path as YouTube", () => {
  assert.equal(
    getVodProvider({
      vod_id: "spoofed",
      vod_url: "https://attacker.example/youtube.com/watch?v=WGTrmrSvZH0",
    }),
    "twitch",
  );
});

test("builds Twitch URLs and parent lists without browser globals", () => {
  assert.equal(formatTwitchTime(3661.9), "1h1m1s");
  assert.deepEqual(getTwitchParents("example.test"), ["example.test", "localhost", "127.0.0.1"]);
  assert.deepEqual(getTwitchParents("localhost"), ["localhost", "127.0.0.1"]);

  const url = new URL(buildEmbedUrl(request(7, "v456"), "example.test"));
  assert.equal(url.searchParams.get("video"), "456");
  assert.equal(url.searchParams.get("autoplay"), "true");
  assert.equal(url.searchParams.get("muted"), "true");
  assert.equal(url.searchParams.get("playsinline"), "true");
  assert.equal(url.searchParams.get("seq"), "7");
  assert.equal(url.searchParams.get("time"), "0h0m42s");
  assert.deepEqual(url.searchParams.getAll("parent"), ["example.test", "localhost", "127.0.0.1"]);
});

test("seeks same VOD and keeps a remount fallback if seeking fails", () => {
  assert.deepEqual(decidePlayback(request(), {
    playerReady: true,
    playerVodId: "123",
    mountInFlight: false,
    mountVodId: "",
    hasInteractivePlayer: true,
  }), {
    seekInteractive: true,
    mountFallback: true,
    waitForMount: false,
    destroyInteractive: true,
    mountInteractive: true,
  });
});

test("does not replace fallback while the same VOD is mounting", () => {
  assert.deepEqual(decidePlayback(request(), {
    playerReady: false,
    playerVodId: "",
    mountInFlight: true,
    mountVodId: "123",
    hasInteractivePlayer: false,
  }), {
    seekInteractive: false,
    mountFallback: false,
    waitForMount: true,
    destroyInteractive: false,
    mountInteractive: false,
  });
});

test("updates fallback but waits when another VOD mount is in flight", () => {
  const decision = decidePlayback(request(2, "999"), {
    playerReady: false,
    playerVodId: "",
    mountInFlight: true,
    mountVodId: "123",
    hasInteractivePlayer: false,
  });
  assert.equal(decision.mountFallback, true);
  assert.equal(decision.waitForMount, true);
  assert.equal(decision.mountInteractive, false);
});

test("mounts and destroys an obsolete interactive player when needed", () => {
  const decision = decidePlayback(request(3, "999"), {
    playerReady: true,
    playerVodId: "123",
    mountInFlight: false,
    mountVodId: "",
    hasInteractivePlayer: true,
  });
  assert.equal(decision.seekInteractive, false);
  assert.equal(decision.mountFallback, true);
  assert.equal(decision.destroyInteractive, true);
  assert.equal(decision.mountInteractive, true);
});

test("request sequence makes the latest mount request win", () => {
  const first = request(1, "123");
  const latest = request(2, "123");
  assert.equal(decideMountContinuation(first, null), "stop");
  assert.equal(decideMountContinuation(first, first), "continue");
  assert.equal(decideMountContinuation(first, latest), "restart");
});
