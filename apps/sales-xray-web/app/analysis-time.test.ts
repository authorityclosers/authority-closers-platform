import { expect, it } from "vitest";

import { analysisTimeLeft, formatAnalysisTime } from "./analysis-time";

// The time left over Choose a file (orchestrator, 13 Nov 2026): time, never a
// price; nothing when used up, unlimited or not known yet.
it("says how much analysis is left, or what a new tester has to try", () => {
  const left = (
    available: number,
    total = 10_800,
    committed = total - available,
  ) => ({
    allowance_seconds: total,
    committed_seconds: committed,
    available_seconds: available,
  });
  expect(analysisTimeLeft(left(10_800, 10_800, 0), "personal")).toBe(
    "3 hours to try",
  );
  expect(analysisTimeLeft(left(3_600, 3_600, 0), "personal")).toBe(
    "1 hour to try",
  );
  expect(analysisTimeLeft(left(9_660), "personal")).toBe(
    "2 h 41 min of analysis left",
  );
  // An organisation's member sees time left, even before their first call.
  expect(analysisTimeLeft(left(10_800, 10_800, 0), "member")).toBe(
    "3 h of analysis left",
  );
  expect(analysisTimeLeft(left(0), "member")).toBeNull();
  expect(
    analysisTimeLeft({ ...left(600), unlimited: true }, "payer"),
  ).toBeNull();
  expect(analysisTimeLeft(null, "personal")).toBeNull();
});

it.each([
  [0, "0 min"],
  [45, "0 min"],
  [2520, "42 min"],
  [3600, "60 min"],
  [3660, "1 h 1 min"],
  [7200, "2 h"],
  [28_740, "7 h 59 min"],
  [600000, "166 h 40 min"],
])("formats %s seconds without overstating the balance", (seconds, text) => {
  expect(formatAnalysisTime(seconds)).toBe(text);
});
