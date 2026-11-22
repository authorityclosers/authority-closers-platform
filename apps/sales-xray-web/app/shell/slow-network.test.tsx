import { expect, it } from "vitest";

import { slowNow } from "./slow-network";
import {
  LIVE_ATTRIBUTE,
  SLOW_AFTER_MS,
  SLOW_ATTRIBUTE,
  slowNetworkScript,
} from "./slow-network-script";

// v1.96 device polish, lane P: "Slow network. Still loading…" after 5 s.
it("shows after 5 s of loading, online, until the stuck card takes over", () => {
  expect(SLOW_AFTER_MS).toBe(5000);
  expect(slowNow(null, 10_000, true, false)).toBe(false);
  expect(slowNow(0, 4_999, true, false)).toBe(false);
  expect(slowNow(0, 5_000, true, false)).toBe(true);
  expect(slowNow(0, 9_000, false, false)).toBe(false);
  expect(slowNow(0, 15_000, true, true)).toBe(false);
});

it("puts the pill up before the app arrives, unless the app is already running", () => {
  const script = slowNetworkScript();
  expect(script).toContain(`setTimeout(`);
  expect(script).toContain(`${SLOW_AFTER_MS}`);
  expect(script).toContain(LIVE_ATTRIBUTE);
  expect(script).toContain(SLOW_ATTRIBUTE);
  expect(() => new Function(script)).not.toThrow();
});
