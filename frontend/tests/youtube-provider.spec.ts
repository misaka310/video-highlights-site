import { expect, test } from "@playwright/test";
import { getFakeYoutubeLog, installFakeYoutube } from "./fake-youtube";


const firstVod = {
  provider: "youtube",
  vod_id: "WGTrmrSvZH0",
  vod_url: "https://www.youtube.com/watch?v=WGTrmrSvZH0",
  title: "YouTube archive",
  published_at: "2026-07-25T00:00:00Z",
  duration_sec: 100,
  chat_total: 1365,
  comments_per_hour: 491.3,
  activity_map: { bucket_sec: 10, duration_sec: 100, last_comment_sec: 98, buckets: [1, 5, 2, 8, 3, 2, 4, 1, 1, 3] },
  items: [
    { id: "WGTrmrSvZH0_20_30", rank: 1, start_sec: 20, end_sec: 30, headline: "first" },
    { id: "WGTrmrSvZH0_60_70", rank: 2, start_sec: 60, end_sec: 70, headline: "second" },
    { id: "WGTrmrSvZH0_80_90", rank: 3, start_sec: 80, end_sec: 90, headline: "third" },
  ],
};

const secondVod = {
  ...firstVod,
  vod_id: "abcdefghijk",
  vod_url: "https://www.youtube.com/watch?v=abcdefghijk",
  title: "Second YouTube archive",
  published_at: "2026-07-24T00:00:00Z",
  items: [{ id: "abcdefghijk_10_20", rank: 1, start_sec: 10, end_sec: 20, headline: "other" }],
};


test.beforeEach(async ({ page }) => {
  await installFakeYoutube(page);
  await page.route("**/data/vod_index.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        updated_at: "2026-08-01T00:00:00Z",
        next_update_at: "2026-08-02T00:00:00Z",
        videos: [
          { provider: "youtube", vod_id: firstVod.vod_id, vod_url: firstVod.vod_url, detail_path: `/data/vods/${firstVod.vod_id}.json`, published_at: firstVod.published_at },
          { provider: "youtube", vod_id: secondVod.vod_id, vod_url: secondVod.vod_url, detail_path: `/data/vods/${secondVod.vod_id}.json`, published_at: secondVod.published_at },
        ],
      }),
    });
  });
  await page.route(`**/data/vods/${firstVod.vod_id}.json`, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(firstVod) });
  });
  await page.route(`**/data/vods/${secondVod.vod_id}.json`, async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(secondVod) });
  });
  await page.route(`**/data/captions/${firstVod.vod_id}.json`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        video_id: firstVod.vod_id,
        source: "youtube_automatic_captions",
        language: "ja",
        cues: [
          { start_sec: 15, end_sec: 25, text: "前の字幕" },
          { start_sec: 26, end_sec: 55, text: "中間の字幕" },
          { start_sec: 56, end_sec: 75, text: "後半の字幕" },
        ],
      }),
    });
  });
  await page.route(`**/data/captions/${secondVod.vod_id}.json`, async (route) => {
    await route.fulfill({ status: 404, body: "not found" });
  });
});


test("runs real user playback controls through the YouTube adapter", async ({ page }, testInfo) => {
  await page.goto("/");
  const frame = page.locator(".player-frame");
  await expect(frame).toHaveAttribute("data-player-provider", "youtube");
  await expect(frame).toHaveAttribute("data-player-mode", "interactive");
  await expect(page.getByRole("tab").first()).toContainText("7/25");
  await expect(page.getByRole("tab").first()).not.toContainText("YouTube");
  await expect(page.locator("body > .player-embed--portal [data-fake-youtube-player='true']")).toHaveCount(1);

  const initial = await getFakeYoutubeLog(page);
  expect(initial.mounts).toHaveLength(1);
  expect(initial.mounts[0]).toMatchObject({ videoId: firstVod.vod_id, autoplay: 0, start: 20 });
  expect(initial.plays).toBe(0);
  expect(initial.muted.at(-1)).toBe(true);
  await expect(frame).toHaveAttribute("data-player-status", "ready");
  await expect(page.getByRole("region", { name: "文字起こし" })).toBeVisible();
  await expect(page.locator(".caption-line--current .caption-text")).toHaveText("前の字幕");
  await expect.poll(async () => page.locator(".caption-panel").evaluate((element) => {
    const style = window.getComputedStyle(element);
    return `${style.display}|${style.justifyContent}`;
  })).toBe("flex|center");
  if (testInfo.project.name === "desktop") {
    const verticalOverflow = await page.evaluate(
      () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
    );
    expect(verticalOverflow).toBeLessThanOrEqual(1);
  }

  await page.locator(".highlight-item").first().click();
  await expect(frame).toHaveAttribute("data-current-start-sec", "20");
  expect((await getFakeYoutubeLog(page)).seeks).toContain(20);

  await page.locator(".highlight-item").nth(1).click();
  await expect(frame).toHaveAttribute("data-expected-autoplay", "true");
  await expect(frame).toHaveAttribute("data-expected-muted", "false");
  await expect(frame).toHaveAttribute("data-player-status", "playing");
  await expect(frame).toHaveAttribute("data-current-start-sec", "60");
  await expect(page.locator(".caption-line--current .caption-text")).toHaveText("後半の字幕");
  const afterHighlight = await getFakeYoutubeLog(page);
  expect(afterHighlight.mounts).toHaveLength(1);
  expect(afterHighlight.seeks).toContain(60);
  expect(afterHighlight.muted.at(-1)).toBe(false);
  expect(afterHighlight.plays).toBeGreaterThan(0);

  await page.locator(".highlight-item").nth(2).click();
  await expect(frame).toHaveAttribute("data-current-start-sec", "80");
  expect((await getFakeYoutubeLog(page)).seeks).toContain(80);

  const chartBox = await page.locator(".activity-chart").boundingBox();
  expect(chartBox).not.toBeNull();
  await page.locator(".activity-chart").click({
    position: { x: (chartBox?.width || 0) / 2, y: (chartBox?.height || 0) / 2 },
  });
  await expect(frame).toHaveAttribute("data-current-start-sec", "50");
  await page.getByRole("button", { name: "10秒戻る" }).click();
  await expect(frame).toHaveAttribute("data-current-start-sec", "40");
  expect((await getFakeYoutubeLog(page)).seeks).toEqual(expect.arrayContaining([50, 40]));

  const playsBeforeDateSwitch = (await getFakeYoutubeLog(page)).plays;
  await page.getByRole("tab").nth(1).click();
  await expect(frame).toHaveAttribute("data-current-vod-id", secondVod.vod_id);
  await expect.poll(async () => (await getFakeYoutubeLog(page)).mounts.length).toBe(2);
  await expect(page.getByRole("region", { name: "文字起こし" })).toHaveCount(0);
  await expect(frame).toHaveAttribute("data-expected-autoplay", "false");
  await expect(frame).toHaveAttribute("data-expected-muted", "true");
  await expect(frame).toHaveAttribute("data-player-status", "ready");
  expect((await getFakeYoutubeLog(page)).mounts.at(-1)).toMatchObject({ videoId: secondVod.vod_id, autoplay: 0 });
  expect((await getFakeYoutubeLog(page)).plays).toBe(playsBeforeDateSwitch);
  expect((await getFakeYoutubeLog(page)).destroys).toBeGreaterThan(0);

  await page.locator(".highlight-item").first().click();
  await expect(frame).toHaveAttribute("data-current-start-sec", "10");
  expect((await getFakeYoutubeLog(page)).mounts).toHaveLength(2);
  expect((await getFakeYoutubeLog(page)).seeks).toContain(10);
});
