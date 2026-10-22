import assert from "node:assert/strict";
import test from "node:test";
import { currentChapterIndex, findProducedVideo, isVideoAvailable, normalizeProducedVideos } from "../../src/lib/produced-videos.js";

const payload = {
  videos: [
    {
      video_id: "intro",
      title: "紹介動画",
      description: "説明",
      duration_sec: 300.5,
      published_at: "2026-10-21",
      poster_url: "produced-video-posters/intro.jpg",
      video_url: "/media/intro.mp4",
      chapters: [
        { start_sec: 100, label: "人柄" },
        { start_sec: 0, label: "オープニング" },
        { start_sec: 100, label: "重複" },
        { start_sec: -5, label: "不正" },
        { start_sec: 42.9, label: "" },
      ],
    },
  ],
};

test("normalizes produced video entries and sorts chapters by start time", () => {
  const [video] = normalizeProducedVideos(payload);
  assert.ok(video);
  assert.equal(video.video_id, "intro");
  assert.equal(video.poster_url, "/data/produced-video-posters/intro.jpg");
  assert.deepEqual(
    video.chapters.map((chapter) => [chapter.start_sec, chapter.label]),
    [
      [0, "オープニング"],
      [100, "人柄"],
    ],
  );
});

test("drops produced video entries without an id, title, or source", () => {
  assert.deepEqual(normalizeProducedVideos({ videos: [{ video_id: "x", title: "y" }] }), []);
  assert.deepEqual(normalizeProducedVideos({}), []);
  assert.deepEqual(normalizeProducedVideos(null), []);
});

test("keeps absolute video urls and normalizes relative ones", () => {
  const [remote] = normalizeProducedVideos({
    videos: [{ video_id: "r", title: "r", video_url: "https://www.youtube.com/embed/abc" }],
  });
  const [relative] = normalizeProducedVideos({ videos: [{ video_id: "l", title: "l", video_url: "media/a.mp4" }] });
  assert.equal(remote.video_url, "https://www.youtube.com/embed/abc");
  assert.equal(relative.video_url, "/media/a.mp4");
});

test("resolves the current chapter from the playback position", () => {
  const [video] = normalizeProducedVideos(payload);
  assert.ok(video);
  assert.equal(currentChapterIndex(video.chapters, 0), 0);
  assert.equal(currentChapterIndex(video.chapters, 99), 0);
  assert.equal(currentChapterIndex(video.chapters, 100), 1);
  assert.equal(currentChapterIndex(video.chapters, 400), 1);
  assert.equal(currentChapterIndex([], 10), -1);
});

test("finds a produced video by id and ignores unknown ids", () => {
  const videos = normalizeProducedVideos(payload);
  assert.equal(findProducedVideo(videos, "intro")?.title, "紹介動画");
  assert.equal(findProducedVideo(videos, "missing"), null);
  assert.equal(findProducedVideo(videos, ""), null);
});

test("only probes same-origin sources for availability", async () => {
  const [video] = normalizeProducedVideos(payload);
  assert.ok(video);
  let called = 0;
  const failingFetch = (async () => {
    called += 1;
    return { ok: false } as Response;
  }) as unknown as typeof fetch;
  assert.equal(await isVideoAvailable(video, failingFetch), false);
  assert.equal(called, 1);

  const remote = { ...video, video_url: "https://www.youtube.com/embed/abc" };
  assert.equal(await isVideoAvailable(remote, failingFetch), true);
  assert.equal(called, 1);
});
