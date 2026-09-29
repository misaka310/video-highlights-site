export type CaptionCue = {
  start_sec: number;
  end_sec: number;
  text: string;
};

export type CaptionData = {
  video_id: string;
  source: "youtube_manual_captions" | "youtube_automatic_captions";
  language: string;
  language_source?: string;
  fetched_at?: string;
  cues: CaptionCue[];
};

export type CaptionWindow = {
  previous: CaptionCue | null;
  current: CaptionCue | null;
  next: CaptionCue | null;
};

export type AnosaStatement = {
  start_sec: number;
  end_sec: number;
  text: string;
};

const ANOSA_RE = /あのさ(?:ぁ|あ)?/;
const ANONE_RE = /あのね(?:ぇ|え)?/;
const ANONE_MAX_CHARACTERS = 110;
const SENTENCE_END_RE = /[。！？!?](?:[」』】）》〉〕］】]*)$/;
const NOISE_ONLY_RE = /^\[[^\]]+\]$/;
const JAPANESE_SPACE_RE = /(?<=[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Han}ー])\s+(?=[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Han}ー])/gu;

function normalizeCaptionText(raw: string): string {
  return String(raw || "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(JAPANESE_SPACE_RE, "")
    .trim();
}

function appendCaptionText(base: string, incoming: string): string {
  const left = normalizeCaptionText(base);
  const right = normalizeCaptionText(incoming);
  if (!left) return right;
  if (!right || NOISE_ONLY_RE.test(right)) return left;
  if (left.endsWith(right)) return left;

  const maxOverlap = Math.min(left.length, right.length);
  for (let overlap = maxOverlap; overlap >= 2; overlap -= 1) {
    if (left.endsWith(right.slice(0, overlap))) {
      return normalizeCaptionText(left + right.slice(overlap));
    }
  }
  return normalizeCaptionText(`${left}${right}`);
}

function capCaptionText(text: string, maxCharacters?: number): { text: string; truncated: boolean } {
  if (maxCharacters === undefined) return { text, truncated: false };
  const characters = Array.from(text);
  if (characters.length <= maxCharacters) return { text, truncated: false };
  return {
    text: `${characters.slice(0, maxCharacters - 1).join("")}…`,
    truncated: true,
  };
}

function extractPhraseStatements(cues: CaptionCue[], phrase: "あのさ" | "あのね"): AnosaStatement[] {
  if (!Array.isArray(cues) || cues.length === 0) return [];

  const maxCharacters = phrase === "あのね" ? ANONE_MAX_CHARACTERS : undefined;
  const results: AnosaStatement[] = [];
  for (let index = 0; index < cues.length; index += 1) {
    const source = cues[index];
    const sourceText = normalizeCaptionText(source?.text || "");
    const match = (phrase === "あのさ" ? ANOSA_RE : ANONE_RE).exec(sourceText);
    let text = "";
    let endSec = Number(source?.end_sec ?? source?.start_sec ?? 0);
    let cursor = index + 1;
    let truncated = false;

    if (match && match.index >= 0) {
      text = sourceText.slice(match.index);
    } else if (phrase === "あのね" && sourceText.endsWith("あの") && cursor < cues.length) {
      const next = cues[cursor];
      const nextText = normalizeCaptionText(next?.text || "");
      const nextStartSec = Number(next?.start_sec ?? endSec);
      if (!nextText.startsWith("ね") || nextStartSec - endSec > 5) continue;

      text = appendCaptionText("あの", nextText);
      endSec = Math.max(endSec, Number(next?.end_sec ?? next?.start_sec ?? endSec));
      cursor += 1;
    } else {
      continue;
    }

    const initialText = capCaptionText(text, maxCharacters);
    text = initialText.text;
    truncated = initialText.truncated;

    while (!truncated && !SENTENCE_END_RE.test(text) && cursor < cues.length && cursor <= index + 8 && text.length < 220) {
      const next = cues[cursor];
      const nextStartSec = Number(next?.start_sec ?? endSec);
      if (nextStartSec - endSec > 5) break;
      const nextText = normalizeCaptionText(next?.text || "");
      const combinedText = appendCaptionText(text, nextText);
      const cappedText = capCaptionText(combinedText, maxCharacters);
      text = cappedText.text;
      truncated = cappedText.truncated;
      endSec = Math.max(endSec, Number(next?.end_sec ?? next?.start_sec ?? endSec));
      cursor += 1;
    }

    text = normalizeCaptionText(text);
    const complete = SENTENCE_END_RE.test(text);
    if (!text.startsWith(phrase) || (!complete && phrase !== "あのね")) continue;

    const startSec = Math.max(0, Number(source?.start_sec) || 0);
    const statement: AnosaStatement = {
      start_sec: startSec,
      end_sec: Math.max(startSec, endSec),
      text,
    };

    const previous = results[results.length - 1];
    if (
      previous &&
      Math.abs(previous.start_sec - statement.start_sec) <= 3 &&
      (previous.text === statement.text ||
        previous.text.startsWith(statement.text) ||
        statement.text.startsWith(previous.text))
    ) {
      if (statement.text.length > previous.text.length) {
        results[results.length - 1] = statement;
      }
      continue;
    }
    results.push(statement);
  }

  return results;
}

export function extractAnosaStatements(cues: CaptionCue[]): AnosaStatement[] {
  return extractPhraseStatements(cues, "あのさ");
}

export function extractAnoneStatements(cues: CaptionCue[]): AnosaStatement[] {
  return extractPhraseStatements(cues, "あのね");
}

export function resolveCaptionWindow(cues: CaptionCue[], positionSec: number): CaptionWindow {
  if (!Array.isArray(cues) || cues.length === 0) {
    return { previous: null, current: null, next: null };
  }

  const position = Math.max(0, Number(positionSec) || 0);
  let low = 0;
  let high = cues.length - 1;
  let candidate = -1;

  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (Number(cues[middle]?.start_sec) <= position) {
      candidate = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }

  if (candidate < 0) {
    return { previous: null, current: null, next: cues[0] || null };
  }

  const cue = cues[candidate];
  const inCue = position <= Number(cue?.end_sec ?? cue?.start_sec ?? 0);
  const currentIndex = inCue ? candidate : -1;
  if (currentIndex >= 0) {
    return {
      previous: cues[currentIndex - 1] || null,
      current: cues[currentIndex] || null,
      next: cues[currentIndex + 1] || null,
    };
  }

  return {
    previous: cues[candidate] || null,
    current: null,
    next: cues[candidate + 1] || null,
  };
}
