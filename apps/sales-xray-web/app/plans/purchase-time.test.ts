import { expect, it } from "vitest";
import { minutes } from "../billing/money";
import { formatPurchaseMinutes } from "./purchase-time";

it.each([
  [0, "0 min"],
  [59, "59 min"],
  [60, "60 min"],
  [61, "61 min (1 h 1 min)"],
  [120, "120 min (2 h)"],
  [800, "800 min (13 h 20 min)"],
  [862, "862 min (14 h 22 min)"],
  [10_000, "10,000 min (166 h 40 min)"],
])("shows %i whole minutes as %s", (value, expected) => {
  expect(formatPurchaseMinutes(value)).toBe(expected);
});

it.each([
  [-1, "0 min"],
  [3_599, "59 min"],
  [3_600, "60 min"],
  [3_659, "60 min"],
  [3_660, "61 min (1 h 1 min)"],
  [51_779, "862 min (14 h 22 min)"],
])("keeps the existing conversion of %i seconds", (seconds, expected) => {
  expect(formatPurchaseMinutes(minutes(seconds))).toBe(expected);
});
