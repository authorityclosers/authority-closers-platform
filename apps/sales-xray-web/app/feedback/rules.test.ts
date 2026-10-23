import { expect, it } from "vitest";

import { newlyFixed } from "../bug-report/my-reports";
import { shakeDetector } from "../bug-report/shake";
import type { FeedbackState } from "./feedback-client";
import { NO_ASKS, mayAsk, shown } from "./rules";

const DAY = 86_400_000;
const NOW = Date.parse("2026-10-23T12:00:00Z");
const SERVER: FeedbackState = {
  optedOut: [],
  last: {},
  askedToday: 0,
  askedThisWeek: 0,
  subjects: [],
};

it("asks once a day at most, three times a week, and rests each moment", () => {
  expect(mayAsk("report_read", "call:1", NOW, NO_ASKS, SERVER)).toEqual({
    ask: true,
  });
  const once = shown(NO_ASKS, "report_read", "call:1", NOW);
  expect(mayAsk("call_outcome", undefined, NOW + 1000, once, SERVER)).toEqual({
    ask: false,
    why: "asked_today",
  });
  expect(
    mayAsk("call_outcome", undefined, NOW + DAY + 1, once, SERVER),
  ).toEqual({
    ask: true,
  });
  // The same moment rests for its own period (14 days for a Report).
  expect(mayAsk("report_read", "call:2", NOW + 2 * DAY, once, SERVER).ask).toBe(
    false,
  );
  expect(
    mayAsk("report_read", "call:2", NOW + 15 * DAY, once, SERVER).ask,
  ).toBe(true);
  // Three this week is the most, whichever moments they were.
  let week = shown(once, "call_outcome", undefined, NOW + 1.1 * DAY);
  week = shown(week, "chats_used", undefined, NOW + 2.2 * DAY);
  expect(
    mayAsk("app_update", "update:k", NOW + 3.3 * DAY, week, SERVER),
  ).toEqual({
    ask: false,
    why: "asked_this_week",
  });
});

it("never asks about one thing twice, and never after don't ask again", () => {
  const asked = shown(NO_ASKS, "app_update", "update:k1", NOW - 30 * DAY);
  expect(mayAsk("app_update", "update:k1", NOW, asked, SERVER).ask).toBe(false);
  expect(mayAsk("app_update", "update:k2", NOW, asked, SERVER).ask).toBe(true);
  expect(
    mayAsk("chats_used", undefined, NOW, NO_ASKS, {
      ...SERVER,
      optedOut: ["chats_used"],
    }),
  ).toEqual({ ask: false, why: "opted_out" });
  // The person's other devices count too.
  expect(
    mayAsk("general", undefined, NOW, NO_ASKS, { ...SERVER, askedToday: 1 })
      .ask,
  ).toBe(false);
  expect(
    mayAsk("plan_purchase", "order:1", NOW, NO_ASKS, {
      ...SERVER,
      subjects: ["order:1"],
    }).ask,
  ).toBe(false);
  expect(
    mayAsk("call_outcome", undefined, NOW, NO_ASKS, {
      ...SERVER,
      last: { call_outcome: new Date(NOW - 2 * DAY).toISOString() },
    }).ask,
  ).toBe(false);
});

it("counts three hard shakes within a second, not walking or one bump", () => {
  let now = 0;
  const shaken = shakeDetector(() => now);
  const hard = () => shaken(0, 0, 9.81 + 20);
  const gentle = () => shaken(0, 0, 9.81 + 4);
  expect([gentle(), gentle(), gentle(), gentle()]).toEqual([
    false,
    false,
    false,
    false,
  ]);
  expect(hard()).toBe(false);
  now = 300;
  expect(hard()).toBe(false);
  now = 600;
  expect(hard()).toBe(true);
  // Not again straight away.
  now = 900;
  expect([hard(), hard(), hard()]).toEqual([false, false, false]);
  // Peaks too far apart never add up.
  now = 7000;
  expect(hard()).toBe(false);
  now = 8200;
  expect(hard()).toBe(false);
  now = 9400;
  expect(hard()).toBe(false);
});

it("finds reports fixed since the last look, and only those", () => {
  const reports = [
    { bugId: "a", createdAt: "", words: "a", status: "fixed", statusAt: "" },
    { bugId: "b", createdAt: "", words: "b", status: "verified", statusAt: "" },
    { bugId: "c", createdAt: "", words: "c", status: "triaged", statusAt: "" },
    { bugId: "d", createdAt: "", words: "d", status: "fixed", statusAt: "" },
  ];
  expect(newlyFixed(reports, null)).toEqual([]);
  expect(
    newlyFixed(reports, { a: "new", b: "fixed", c: "new" }).map((r) => r.bugId),
  ).toEqual(["a"]);
});
