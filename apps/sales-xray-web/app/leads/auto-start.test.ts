import { afterEach, expect, it } from "vitest";

import type { AutoAnalysis } from "../settings/auto-analysis-client";
import {
  afterCallStart,
  ASKED_ON_KEY,
  markNudged,
  NOT_NOW_KEY,
  NOT_NOW_MS,
  notNow,
  nudgeDue,
} from "./auto-start";

const view = (
  state: AutoAnalysis["state"],
  can_start = false,
): AutoAnalysis => ({
  schema: "sales-xray-auto-analysis/1",
  state,
  can_start,
});

afterEach(() => localStorage.clear());

// Owner, 26 Oct 2026: a seller's calls analysed as they arrive, once they say so.
it("starts by itself only when the server says it may", () => {
  expect(afterCallStart(view("on", true))).toBe("start");
  // On, but the AI level is Off: the tap.
  expect(afterCallStart(view("on", false))).toBe("tap");
  expect(afterCallStart(view("off"))).toBe("tap");
  expect(afterCallStart(view("unavailable"))).toBe("tap");
  expect(afterCallStart(null)).toBe("tap");
});

it("asks until Not now, then waits a week on this device", () => {
  const now = Date.UTC(2026, 9, 26, 10);
  expect(afterCallStart(view("ask"), now)).toBe("ask");
  notNow(now);
  // Nothing about consent is kept: only when the sheet may ask again.
  expect(Object.keys(localStorage)).toEqual([NOT_NOW_KEY]);
  expect(afterCallStart(view("ask"), now + NOT_NOW_MS - 1)).toBe("tap");
  expect(afterCallStart(view("ask"), now + NOT_NOW_MS + 1)).toBe("ask");
  // A consent turned on elsewhere still starts.
  expect(afterCallStart(view("on", true), now + 1)).toBe("start");
});

// Owner, 3 Nov 2026: optional, easy to say yes to, and reminded gently.
it("asks at most once a day, on the Calls line or after a call", () => {
  const morning = Date.UTC(2026, 10, 3, 4); // 09:30 in India
  expect(nudgeDue(view("ask"), morning)).toBe(true);
  markNudged(morning);
  expect(nudgeDue(view("ask"), morning + 3 * 60 * 60 * 1000)).toBe(false);
  expect(afterCallStart(view("ask"), morning + 60_000)).toBe("tap");
  // The next India day it may ask again.
  expect(nudgeDue(view("ask"), morning + 24 * 60 * 60 * 1000)).toBe(true);
  // Only the day is kept, never anything about consent.
  expect(Object.keys(localStorage)).toEqual([ASKED_ON_KEY]);
});

it("never asks someone who turned it off, or in the week after Not now", () => {
  const now = Date.UTC(2026, 10, 3, 4);
  expect(nudgeDue(view("off"), now)).toBe(false);
  expect(nudgeDue(view("on", true), now)).toBe(false);
  expect(nudgeDue(view("unavailable"), now)).toBe(false);
  expect(nudgeDue(null, now)).toBe(false);
  notNow(now);
  expect(nudgeDue(view("ask"), now + NOT_NOW_MS - 1)).toBe(false);
  expect(nudgeDue(view("ask"), now + NOT_NOW_MS + 1)).toBe(true);
});
