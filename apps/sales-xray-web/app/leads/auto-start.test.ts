import { afterEach, expect, it } from "vitest";

import type { AutoAnalysis } from "../settings/auto-analysis-client";
import { afterCallStart, NOT_NOW_KEY, NOT_NOW_MS, notNow } from "./auto-start";

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
