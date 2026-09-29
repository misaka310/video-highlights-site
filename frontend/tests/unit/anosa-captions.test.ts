import assert from "node:assert/strict";
import test from "node:test";

import { extractAnoneStatements, extractAnosaStatements, type CaptionCue } from "../../src/lib/captions.js";

function cue(start: number, text: string, end = start + 2): CaptionCue {
  return { start_sec: start, end_sec: end, text };
}

test("anosa statement starts exactly at あのさ and discards preceding fragment", () => {
  const result = extractAnosaStatements([
    cue(10, "前置きは不要。あのさ、これ大事な話なんだけど。"),
  ]);

  assert.deepEqual(result, [
    { start_sec: 10, end_sec: 12, text: "あのさ、これ大事な話なんだけど。" },
  ]);
});

test("anosa statement joins following cues until a sentence ending", () => {
  const result = extractAnosaStatements([
    cue(20, "あのさ、エルデンリング飯って"),
    cue(22, "こういう感じで作るのが"),
    cue(24, "一番いいと思うんだよね。"),
  ]);

  assert.equal(result.length, 1);
  assert.equal(result[0]?.text, "あのさ、エルデンリング飯ってこういう感じで作るのが一番いいと思うんだよね。");
  assert.equal(result[0]?.end_sec, 26);
});

test("incomplete fragmented anosa cue is not emitted", () => {
  const result = extractAnosaStatements([
    cue(30, "あのさ、これだけだと"),
    cue(32, "まだ意味が"),
  ]);

  assert.deepEqual(result, []);
});

test("incomplete anosa cue does not jump across a long gap into another utterance", () => {
  const result = extractAnosaStatements([
    cue(30, "あのさ、これは途中で"),
    cue(32, "意味が切れて"),
    cue(50, "別の話。あのさ、これは完結する。"),
  ]);

  assert.deepEqual(result, [
    { start_sec: 50, end_sec: 52, text: "あのさ、これは完結する。" },
  ]);
});

test("overlapping automatic caption text is merged without duplicated words", () => {
  const result = extractAnosaStatements([
    cue(40, "あのさ、これは絶対"),
    cue(42, "絶対やった方がいい。"),
  ]);

  assert.equal(result[0]?.text, "あのさ、これは絶対やった方がいい。");
});

test("unnatural spaces inside Japanese text are removed", () => {
  const result = extractAnosaStatements([
    cue(50, "あのさ、これ は ちゃんと 読める。"),
  ]);

  assert.equal(result[0]?.text, "あのさ、これはちゃんと読める。");
});

test("noise-only cues do not break sentence reconstruction", () => {
  const result = extractAnosaStatements([
    cue(60, "あのさ、続きが"),
    cue(62, "[音楽]"),
    cue(64, "ここまで来れば意味が通る。"),
  ]);

  assert.equal(result[0]?.text, "あのさ、続きがここまで来れば意味が通る。");
});

test("extracts complete あのね statements without changing the existing あのさ list", () => {
  const captions = [cue(70, "前置き。あのね、これは見つけやすい。")];
  const result = extractAnoneStatements(captions);

  assert.deepEqual(result, [
    { start_sec: 70, end_sec: 72, text: "あのね、これは見つけやすい。" },
  ]);
  assert.deepEqual(extractAnosaStatements(captions), []);
});

test("includes あのね split across adjacent subtitle cues", () => {
  const result = extractAnoneStatements([
    cue(80, "これちなみにね、あの", 82),
    cue(82, "ね、多分この後は大丈夫。", 84),
  ]);

  assert.deepEqual(result, [
    { start_sec: 80, end_sec: 84, text: "あのね、多分この後は大丈夫。" },
  ]);
});

test("does not join an あのね subtitle split across a gap over five seconds", () => {
  const result = extractAnoneStatements([
    cue(90, "これちなみにね、あの", 91),
    cue(97, "ね、多分この後は大丈夫。", 99),
  ]);

  assert.deepEqual(result, []);
});

test("keeps incomplete あのね caption candidates visible", () => {
  const result = extractAnoneStatements([
    cue(100, "前置き。あのね、その話なんだけど"),
  ]);

  assert.deepEqual(result, [
    { start_sec: 100, end_sec: 102, text: "あのね、その話なんだけど" },
  ]);
});

test("hard caps a long あのね cue at 110 characters including the ellipsis", () => {
  const result = extractAnoneStatements([
    cue(110, `あのね、${"長い文章".repeat(60)}`),
  ]);

  assert.equal(Array.from(result[0]?.text || "").length, 110);
  assert.ok(result[0]?.text.endsWith("…"));
});

test("hard caps あのね text when the next caption cue exceeds the remaining length", () => {
  const result = extractAnoneStatements([
    cue(120, "あのね、短い前置き"),
    cue(122, "これから先も長く続く文章".repeat(30)),
  ]);

  assert.equal(Array.from(result[0]?.text || "").length, 110);
  assert.ok(result[0]?.text.endsWith("…"));
});
