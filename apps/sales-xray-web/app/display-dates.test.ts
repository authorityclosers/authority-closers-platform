import { expect, it } from "vitest";

import { callDate } from "./call-status";
import { unnamedCallName } from "./call-label";
import {
  acceptedLocale,
  dayKey,
  daysBetween,
  INDIA_TIME,
  serverDisplayDates,
} from "./display-dates";

// 20:00 UTC on 10 Oct is already 11 Oct in India (01:30 IST).
const lateEvening = Date.UTC(2026, 9, 10, 20, 0);

it("names the day an instant falls on in a time zone", () => {
  expect(dayKey(lateEvening, "UTC")).toBe("2026-10-10");
  expect(dayKey(lateEvening, INDIA_TIME)).toBe("2026-10-11");
  expect(dayKey("2026-01-05T00:00:00Z", "UTC")).toBe("2026-01-05");
  expect(dayKey("not a date", INDIA_TIME)).toBeNull();
  expect(daysBetween("2026-10-10", "2026-10-11")).toBe(1);
  expect(daysBetween("2025-12-31", "2026-01-01")).toBe(1);
  expect(daysBetween("2026-10-11", "2026-10-04")).toBe(-7);
});

it("writes dates in the first language the browser asked for, if usable", () => {
  expect(acceptedLocale("en-IN,en;q=0.9,hi;q=0.8")).toBe("en-IN");
  expect(acceptedLocale("hi-IN")).toBe("hi-IN");
  expect(acceptedLocale("en-us;q=0.8")).toBe("en-US");
  for (const bad of [null, undefined, "", "*", "!!", "x".repeat(300)])
    expect(acceptedLocale(bad)).toBeNull();
  expect(serverDisplayDates("en-GB", lateEvening)).toEqual({
    locale: "en-GB",
    timeZone: INDIA_TIME,
    today: "2026-10-11",
  });
  // No usable language: Indian English.
  expect(serverDisplayDates(null, lateEvening).locale).toBe("en-IN");
});

it("dates calls in the display's language and zone", () => {
  const india = { locale: "en-IN", timeZone: INDIA_TIME, today: "2026-10-11" };
  const london = { locale: "en-GB", timeZone: "UTC", today: "2026-10-10" };
  const at = new Date(lateEvening).toISOString();
  expect(callDate(at, undefined, india)).toBe("Today");
  expect(callDate(at, undefined, london)).toBe("Today");
  expect(callDate("2026-10-09T20:00:00Z", undefined, india)).toBe("Yesterday");
  expect(callDate("2026-10-01T08:00:00Z", undefined, india)).toBe("1 Oct");
  expect(callDate("2025-10-01T08:00:00Z", undefined, india)).toBe("1 Oct 2025");
  expect(callDate("nonsense", undefined, india)).toBe("Date unknown");
  expect(unnamedCallName(at, india)).toBe("Sales call · 11 Oct 2026");
  expect(unnamedCallName(at, london)).toBe("Sales call · 10 Oct 2026");
});
