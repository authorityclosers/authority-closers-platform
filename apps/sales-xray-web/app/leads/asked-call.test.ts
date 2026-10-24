// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";

import { askAboutCall } from "./lead-sheet";

afterEach(() => window.localStorage.clear());

// Redmi sweep, 24 Oct 2026: opening a lead asked "How did the call go?" about a
// call from days ago. The phone app's last call is asked about once, while fresh.
it("asks about a fresh call once, and never about an old one", () => {
  const now = Date.parse("2026-10-24T10:00:00Z");
  const call = {
    leadId: "lead-1",
    startedMs: now - 120_000,
    endedMs: now - 60_000,
  };
  expect(askAboutCall(call, now)).toBe(true);
  expect(askAboutCall(call, now + 5_000)).toBe(false);
  const old = {
    leadId: "lead-2",
    startedMs: now - 3 * 86_400_000,
    endedMs: now - 3 * 86_400_000,
  };
  expect(askAboutCall(old, now)).toBe(false);
  expect(askAboutCall({ ...call, endedMs: null }, now)).toBe(false);
});
