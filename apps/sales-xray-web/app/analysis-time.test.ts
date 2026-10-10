import { expect, it } from "vitest";

import { formatAnalysisTime } from "./analysis-time";

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
