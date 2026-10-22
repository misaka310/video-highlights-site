import assert from "node:assert/strict";
import test from "node:test";
import { isHlsSource } from "../../src/lib/video-source.js";

test("detects HLS master playlists and media playlists", () => {
  assert.equal(isHlsSource("https://media.example.com/v/master.m3u8"), true);
  assert.equal(isHlsSource("/media/v/master.m3u8"), true);
  assert.equal(isHlsSource("https://media.example.com/v/master.M3U8"), true);
  assert.equal(isHlsSource("https://media.example.com/v/master.m3u8?token=abc"), true);
  assert.equal(isHlsSource("https://media.example.com/v/master.m3u8#t=10"), true);
});

test("rejects progressive files and empty values", () => {
  assert.equal(isHlsSource("https://media.example.com/v/intro.mp4"), false);
  assert.equal(isHlsSource("/media/intro.mp4"), false);
  assert.equal(isHlsSource(""), false);
  assert.equal(isHlsSource("   "), false);
});
