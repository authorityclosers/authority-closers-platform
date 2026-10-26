import { expect, it } from "vitest";

import { runWords } from "./meta-setup";

// Owner's dev reports #2 and #3 (26 Oct 2026): older leads come in from the
// Connections sheet, never held up by the test lead, and say what was found.
it("says what a run of older leads found, not only what was new", () => {
  expect(runWords(null)).toBeNull();
  expect(runWords({ state: "running", seen: 40, created: 2, here: 38 })).toBe(
    "Bringing in older leads… 40 leads read: 2 new, 38 already in your leads so far",
  );
  expect(runWords({ state: "done", seen: 102, created: 2, here: 100 })).toBe(
    "Older leads, last 90 days: 102 leads read: 2 new, 100 already in your leads",
  );
  expect(runWords({ state: "done", seen: 0, created: 0, here: 0 })).toBe(
    "Older leads: Meta has none from the last 90 days",
  );
  expect(runWords({ state: "blocked", seen: 0, created: 0, here: 0 })).toBe(
    "Older leads stopped: see the Page's problem",
  );
});
