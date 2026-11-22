import { expect, it } from "vitest";

import { trialHeadline, trialHours, trialLeft } from "./trial-copy";

// Owner, 22 Nov 2026: "1 month + 3 hours", whichever comes first.
const NOW = Date.parse("2026-11-28T06:30:00Z");
const month = { seconds: 10_800, endsAt: "2026-12-25T07:00:00Z" };

it("names the free month and its three hours", () => {
  expect(trialHeadline(month)).toBe(
    "Free for 1 month · 3 hours of call analysis",
  );
  // Trial v1 has no end: no month is promised.
  expect(trialHeadline({ seconds: 10_800, endsAt: null })).toBe(
    "Free trial · 3 hours of call analysis",
  );
  expect(trialHours(3600)).toBe("1 hour");
  expect(trialHours(6000)).toBe("1 h 40 min");
});

it("says the days and time left", () => {
  expect(trialLeft(month, 7800, NOW)).toBe("27 days · 2 h 10 min left");
  expect(trialLeft(month, 600, NOW)).toBe("27 days · 10 min left");
  const tomorrow = Date.parse("2026-12-24T06:00:00Z");
  expect(trialLeft(month, 7800, tomorrow)).toBe("1 day · 2 h 10 min left");
  const lastHours = Date.parse("2026-12-25T01:00:00Z");
  expect(trialLeft(month, 7800, lastHours)).toBe("Last day · 2 h 10 min left");
  expect(trialLeft({ seconds: 10_800, endsAt: null }, 7800, NOW)).toBe(
    "2 h 10 min left",
  );
});

it("says which end came first", () => {
  expect(trialLeft(month, 7800, Date.parse(month.endsAt))).toBe(
    "Your free month has ended",
  );
  expect(trialLeft(month, 0, NOW)).toBe("You've used your 3 free hours");
  expect(trialLeft({ seconds: 10_800, endsAt: null }, 0, NOW)).toBe(
    "You've used your 3 free hours",
  );
});

it("never says 15 days", () => {
  const all = [
    trialHeadline(month),
    trialLeft(month, 7800, NOW),
    trialLeft(month, 0, NOW),
    trialLeft(month, 1, Date.parse(month.endsAt)),
  ].join(" ");
  expect(all).not.toMatch(/15\s*days?/i);
});
