import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { getFakeYoutubeLog, installFakeYoutube } from "./fake-youtube";

const artifactsDirectory = resolve(process.cwd(), "artifacts");

test.beforeAll(() => {
  mkdirSync(artifactsDirectory, { recursive: true });
});

test.beforeEach(async ({ page }) => {
  await installFakeYoutube(page);
});

test("renders production layout and preserves same-VOD playback behavior", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto("/");
  const faviconResponse = await page.request.get("/favicon.svg");
  expect(faviconResponse.ok()).toBe(true);
  expect(faviconResponse.headers()["content-type"]).toContain("image/svg+xml");
  await expect(page.getByRole("heading", { name: "dotitao moments" })).toBeVisible();
  await expect(page.getByText("非公式ファンサイト", { exact: false })).toBeVisible();
  await expect(page.getByText("盛り上がりマップ", { exact: true })).toBeVisible();
  await expect(page.getByText("この配信について", { exact: true })).toBeVisible();
  await expect(page.getByText("長さ", { exact: true })).toBeVisible();
  await expect(page.getByText("配信の長さ", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Kumo preview", { exact: true })).toHaveCount(0);
  await expect(page.locator(".player-heading")).toHaveCount(0);
  await expect(page.locator(".playback-surface > .player-frame + .activity-card")).toHaveCount(1);

  const frame = page.locator(".player-frame");
  await expect(frame).toHaveAttribute("data-player-mode", "interactive");
  await expect(page.locator("body > .player-embed--portal")).toHaveCount(1);
  await expect(page.locator("body > .player-embed--portal iframe")).toHaveCount(0);
  await expect(page.locator("body > .player-embed--portal [data-fake-youtube-player='true']")).toHaveCount(1);
  await expect(frame).toHaveAttribute("data-expected-autoplay", "false");
  await expect(frame).toHaveAttribute("data-expected-muted", "true");

  await expect(page.locator(".highlight-item")).toHaveCount(3);
  await expect(page.locator(".highlight-item img")).toHaveCount(3);
  const indexResponse = await page.request.get("/data/vod_index.json");
  expect(indexResponse.ok()).toBe(true);
  const indexPayload = (await indexResponse.json()) as {
    videos: Array<{ detail_path?: string; published_at?: string }>;
  };
  const firstVod = indexPayload.videos[0];
  expect(firstVod?.detail_path).toBeTruthy();
  const detailResponse = await page.request.get(firstVod.detail_path!);
  expect(detailResponse.ok()).toBe(true);
  const firstDetail = (await detailResponse.json()) as {
    items: Array<{ screenshot_url?: string }>;
  };
  const expectedScreenshot = firstDetail.items[0]?.screenshot_url;
  expect(expectedScreenshot).toBeTruthy();
  await expect(page.locator(".highlight-item img").first()).toHaveAttribute(
    "src",
    expectedScreenshot!,
  );
  await expect(page.getByText(`Showing 1-3 of ${indexPayload.videos.length}`, { exact: true })).toBeVisible();
  const publishedDate = firstVod.published_at?.match(/-(\d{2})-(\d{2})/);
  expect(publishedDate).not.toBeNull();
  await expect(page.getByRole("tab").first()).toContainText(`${Number(publishedDate![1])}/${Number(publishedDate![2])}`);
  await expect(page.getByRole("tab").first()).not.toContainText("YouTube");
  await expect(page.getByRole("tab").first()).not.toContainText("Twitch");
  await expect(page.locator(".highlight-item").first()).toHaveClass(/is-selected/);
  const firstTags = page.locator(".highlight-item").first().locator(".highlight-tag");
  expect(await firstTags.count()).toBeLessThanOrEqual(2);
  if (await firstTags.count()) {
    await expect(firstTags.first()).toHaveCSS("background-color", "rgb(33, 29, 45)");
    await expect(firstTags.first()).toHaveCSS("color", "rgb(216, 204, 233)");
  }

  const activityChart = page.locator(".activity-chart");
  const activityPath = (await page.locator(".activity-area").getAttribute("d")) || "";
  const drawPointCount = (activityPath.match(/ L /g) || []).length - 1;
  expect(drawPointCount).toBeLessThanOrEqual(testInfo.project.name === "mobile" ? 120 : 320);
  await expect(activityChart).toHaveCSS("height", testInfo.project.name === "mobile" ? "60px" : "88px");
  await expect(page.locator(".activity-peak, .activity-grid-line, .activity-current-time")).toHaveCount(0);

  const initialLog = await getFakeYoutubeLog(page);
  expect(initialLog.mounts).toHaveLength(1);
  expect(initialLog.mounts[0]).toMatchObject({ autoplay: 0 });
  expect(initialLog.muted.at(-1)).toBe(true);

  const second = page.locator(".highlight-item").nth(1);
  await second.click();
  await expect(second).toHaveClass(/is-selected/);
  await expect(frame).toHaveAttribute("data-expected-autoplay", "true");
  await expect(frame).toHaveAttribute("data-expected-muted", "false");

  const selected = Number(await frame.getAttribute("data-current-start-sec"));
  expect(selected).toBeGreaterThan(0);
  const sameVodLog = await getFakeYoutubeLog(page);
  expect(sameVodLog.mounts).toHaveLength(1);
  expect(sameVodLog.seeks).toContain(selected);
  expect(sameVodLog.muted.at(-1)).toBe(false);
  expect(sameVodLog.plays).toBeGreaterThan(0);

  await page.getByRole("button", { name: "10秒戻る" }).click();
  await expect(frame).toHaveAttribute("data-current-start-sec", String(Math.max(0, selected - 10)));
  expect((await getFakeYoutubeLog(page)).seeks).toContain(Math.max(0, selected - 10));

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.activeElement?.tagName)).not.toBe("BODY");

  const columns = await page.locator(".content-grid").evaluate((element) => getComputedStyle(element).gridTemplateColumns);
  if (testInfo.project.name === "desktop") {
    expect(columns.split(" ").length).toBeGreaterThanOrEqual(2);
    const playerBox = await frame.boundingBox();
    const railBox = await page.locator(".highlight-column").boundingBox();
    expect(playerBox?.width || 0).toBeGreaterThanOrEqual(950);
    expect(railBox?.width || 0).toBeGreaterThanOrEqual(380);
    expect(railBox?.width || Infinity).toBeLessThanOrEqual(420);
    const verticalOverflow = await page.evaluate(
      () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
    );
    expect(verticalOverflow).toBeLessThanOrEqual(1);
  } else {
    expect(columns.split(" ").length).toBe(1);
    const order = await page.locator(".content-grid > *").evaluateAll((elements) =>
      elements.map((element) => element.getBoundingClientRect().top),
    );
    expect(order[1]).toBeGreaterThan(order[0]);
  }

  await page.screenshot({
    path: resolve(artifactsDirectory, `production-${testInfo.project.name}.png`),
    fullPage: true,
  });

  expect(consoleErrors).toEqual([]);
});

test("latest click wins and a different VOD remounts paused", async ({ page }) => {
  await page.route("**/data/vod_index.json", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    const [first] = payload.videos.filter((video: { provider?: string }) => video.provider === "youtube");
    payload.videos = [
      first,
      {
        ...first,
        vod_id: "preview-second-youtube",
        detail_path: "/data/vods/preview-second-youtube.json",
        published_at: "2026-08-01T00:00:00Z",
      },
    ];
    await route.fulfill({ response, json: payload });
  });
  await page.route("**/data/vods/preview-second-youtube.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "youtube",
        vod_id: "preview-second-youtube",
        title: "別のYouTube配信",
        published_at: "2026-08-01T00:00:00Z",
        duration_sec: 120,
        activity_map: { duration_sec: 120, buckets: [1, 2] },
        items: [{ id: "preview-second-10", rank: 1, start_sec: 10, end_sec: 20, headline: "別の見どころ" }],
      }),
    });
  });
  await page.goto("/");
  const frame = page.locator(".player-frame");
  await expect(frame).toHaveAttribute("data-player-mode", "interactive");
  const initialVodId = await frame.getAttribute("data-current-vod-id");

  const highlights = page.locator(".highlight-item");
  await highlights.nth(1).click();
  await highlights.nth(2).click();
  const lastSelectedStart = Number(await highlights.nth(2).locator(".time-chip").textContent().then((text) => {
    const parts = String(text || "0").split(":").map(Number);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return 0;
  }));
  await expect(frame).toHaveAttribute("data-current-start-sec", String(lastSelectedStart));
  expect((await getFakeYoutubeLog(page)).mounts).toHaveLength(1);

  const tabs = page.getByRole("tab");
  test.skip((await tabs.count()) < 2, "requires at least two VODs");
  const playsBeforeDateSwitch = (await getFakeYoutubeLog(page)).plays;
  await tabs.nth(1).click();
  await expect.poll(async () => frame.getAttribute("data-current-vod-id")).not.toBe(initialVodId);
  await expect(frame).toHaveAttribute("data-expected-autoplay", "false");
  await expect(frame).toHaveAttribute("data-expected-muted", "true");
  await expect.poll(async () => (await getFakeYoutubeLog(page)).mounts.length).toBeGreaterThan(1);
  expect((await getFakeYoutubeLog(page)).mounts.at(-1)).toMatchObject({ autoplay: 0 });
  expect((await getFakeYoutubeLog(page)).plays).toBe(playsBeforeDateSwitch);
  await expect(page.locator("body > .player-embed--portal")).toHaveCount(1);
  await expect(page.locator("body > .player-embed--portal iframe")).toHaveCount(0);
  await expect(page.locator("body > .player-embed--portal [data-fake-youtube-player='true']")).toHaveCount(1);
  expect((await getFakeYoutubeLog(page)).destroys).toBeGreaterThan(0);
});

test("keeps legacy ordering and missing metadata fallbacks", async ({ page }) => {
  await page.route("**/data/vod_index.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        updated_at: "2026-08-02T00:00:00Z",
        next_update_at: "2026-08-03T00:00:00Z",
        videos: [
          { provider: "youtube", vod_id: "older", detail_path: "data/vods/older.json", published_at: "2026-07-01T00:00:00Z" },
          { provider: "youtube", vod_id: "newer", detail_path: "data/vods/newer.json", published_at: "2026-08-01T00:00:00Z" },
        ],
      }),
    });
  });
  await page.route("**/data/vods/newer.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "youtube",
        vod_id: "newer",
        title: "",
        published_at: "2026-08-01T00:00:00Z",
        chat_total: null,
        comments_per_hour: null,
        activity_map: { buckets: [1, 3, 2], last_comment_sec: 0 },
        items: [
          { id: "rank-3", rank: 3, start_sec: 60, end_sec: 90, headline: "3番目" },
          { id: "rank-1", rank: 1, start_sec: 20, end_sec: 30, headline: "1番目" },
          { id: "rank-2", rank: 2, start_sec: 40, end_sec: 50, reason: "Chat activity spike around 00:00:40 (z-score=4.2)." },
        ],
      }),
    });
  });
  await page.route("**/data/vods/older.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "youtube",
        vod_id: "older",
        title: "古い配信",
        published_at: "2026-07-01T00:00:00Z",
        duration_sec: 120,
        chat_total: 10,
        comments_per_hour: 5,
        activity_map: { duration_sec: 120, buckets: [1, 1] },
        items: [{ id: "old-1", rank: 1, start_sec: 10, end_sec: 20, headline: "古い見どころ" }],
      }),
    });
  });

  await page.goto("/");
  const frame = page.locator(".player-frame");
  await expect(frame).toHaveAttribute("data-current-vod-id", "newer");
  await expect(frame).toHaveAttribute("data-current-start-sec", "20");
  await expect(page.locator(".time-chip")).toHaveText(["00:00:20", "00:00:40", "00:01:00"]);
  await expect(page.locator(".highlight-copy > strong")).toHaveText(["1番目", "見出し未生成", "3番目"]);
  await expect(page.locator(".stream-summary dd").nth(0)).toHaveText("―");
  await expect(page.locator(".stream-summary dd").nth(2)).toHaveText("00:01:30");
  await expect(page.locator(".stream-summary dd").nth(3)).toHaveText("―");
  await expect(page.locator(".activity-unavailable")).toHaveAttribute("x", "0");
  await expect(page.locator(".activity-unavailable")).toHaveAttribute("width", "1000");
});

test("page controls preserve the existing page query", async ({ page }, testInfo) => {
  await page.route("**/data/vod_index.json", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.videos = [4, 3, 2, 1].map((number) => ({
      provider: "youtube",
      vod_id: `page-vod-${number}`,
      detail_path: `/data/vods/page-vod-${number}.json`,
      published_at: `2026-08-0${number}T00:00:00Z`,
    }));
    await route.fulfill({ response, json: payload });
  });
  await page.route("**/data/vods/page-vod-*.json", async (route) => {
    const vodId = new URL(route.request().url()).pathname.split("/").pop()?.replace(".json", "") || "page-vod-1";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "youtube",
        vod_id: vodId,
        title: `${vodId} の配信`,
        published_at: "2026-08-01T00:00:00Z",
        duration_sec: 120,
        activity_map: { duration_sec: 120, buckets: [1, 2] },
        items: [{ id: `${vodId}-10`, rank: 1, start_sec: 10, end_sec: 20, headline: "ページの見どころ" }],
      }),
    });
  });
  await page.goto("/");
  const nextButton = page.getByRole("button", { name: /next|次/i }).last();
  await expect(nextButton).toBeVisible();
  await nextButton.click();
  await expect(page).toHaveURL(/\?page=2$/);
  await expect(page.locator(".highlight-item").first()).toBeVisible();
  await expect(page.locator(".player-frame")).toHaveAttribute("data-expected-autoplay", "false");
  await expect(page.locator(".player-frame")).toHaveAttribute("data-expected-muted", "true");

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  await page.screenshot({
    path: resolve(artifactsDirectory, `page-2-${testInfo.project.name}.png`),
    fullPage: true,
  });
});

test("clamps an out-of-range page to the last available page", async ({ page }) => {
  await page.route("**/data/vod_index.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        videos: [
          { provider: "youtube", vod_id: "4", detail_path: "data/vods/4.json", published_at: "2026-08-04T00:00:00Z" },
          { provider: "youtube", vod_id: "3", detail_path: "data/vods/3.json", published_at: "2026-08-03T00:00:00Z" },
          { provider: "youtube", vod_id: "2", detail_path: "data/vods/2.json", published_at: "2026-08-02T00:00:00Z" },
          { provider: "youtube", vod_id: "1", detail_path: "data/vods/1.json", published_at: "2026-08-01T00:00:00Z" },
        ],
      }),
    });
  });
  await page.route("**/data/vods/1.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "youtube",
        vod_id: "1",
        title: "最終ページの配信",
        published_at: "2026-08-01T00:00:00Z",
        duration_sec: 120,
        activity_map: { duration_sec: 120, buckets: [1, 2] },
        items: [{ id: "1_10_20", rank: 1, start_sec: 10, end_sec: 20, headline: "最終ページの見どころ" }],
      }),
    });
  });

  await page.goto("/?page=999");

  await expect(page).toHaveURL(/\?page=2$/);
  await expect(page.getByText("最終ページの配信", { exact: true })).toBeVisible();
  await expect(page.getByText("読み込み中...", { exact: true })).toHaveCount(0);
});
