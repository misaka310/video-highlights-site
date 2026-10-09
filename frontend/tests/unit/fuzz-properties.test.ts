import assert from "node:assert/strict";
import test from "node:test";
import fc from "fast-check";
import { normalizeDataPath, pageUrl, parsePageSearch } from "../../src/lib/vod-data.js";

test("property: normalized data paths are canonical and idempotent", () => {
  fc.assert(
    fc.property(fc.string(), (raw) => {
      const normalized = normalizeDataPath(raw);
      assert.equal(normalized.startsWith("/data/"), true);
      assert.equal(normalizeDataPath(normalized), normalized);
    }),
    { numRuns: 1000 },
  );
});

test("property: generated page URLs always round-trip to a positive page", () => {
  fc.assert(
    fc.property(fc.integer({ min: -1_000_000, max: 1_000_000 }), (requestedPage) => {
      const generated = pageUrl("https://example.test/?mode=preview", requestedPage);
      const parsed = new URL(generated);
      assert.equal(parsePageSearch(parsed.search), Math.max(1, requestedPage));
    }),
    { numRuns: 1000 },
  );
});
