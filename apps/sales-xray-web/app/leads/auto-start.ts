/**
 * After a call, whether its recording starts by itself (owner, 26 Oct 2026:
 * "Analyse my calls automatically", the seller's standing consent; the
 * server's view is read with settings/auto-analysis-client.ts):
 *
 * - "start": the consent is on for the terms in force: upload with no tap;
 * - "ask": never chosen, or the words or the terms changed since: offer the
 *   sheet, unless the person said Not now on this device within the week, or
 *   it was offered today (nudgeDue);
 * - "tap": everything else (off, a personal workspace, not read): today's
 *   one tap.
 *
 * Not now records nothing about consent: it only keeps the sheet away.
 *
 * The same gentle ask shows on the Calls line, with what is being missed in
 * numbers (owner, 3 Nov 2026): one ask a day across both, and none in the week
 * after Not now. It never covers anything or blocks.
 */
import type { AutoAnalysis } from "../settings/auto-analysis-client";

export type AfterCallStart = "start" | "ask" | "tap";

export const NOT_NOW_KEY = "sx.autoAnalysis.notNowUntil";
export const NOT_NOW_MS = 7 * 24 * 60 * 60 * 1000;
/** The India day the gentle ask last showed on this device. */
export const ASKED_ON_KEY = "sx.autoAnalysis.askedOn";

/** Where the person turns it off again. */
export const AUTO_ANALYSIS_SETTINGS_HREF = "/settings?section=privacy";

export function afterCallStart(
  view: AutoAnalysis | null,
  now = Date.now(),
): AfterCallStart {
  if (!view) return "tap";
  if (view.can_start) return "start";
  if (nudgeDue(view, now)) return "ask";
  return "tap";
}

/**
 * The gentle ask may show: never chosen (or new words), at most once a day on
 * this device, and not in the week after Not now. Off (the seller turned it
 * off) is their choice: it never asks.
 */
export function nudgeDue(view: AutoAnalysis | null, now = Date.now()): boolean {
  return (
    !!view &&
    !view.can_start &&
    view.state === "ask" &&
    !notNowUntilLater(now) &&
    !askedToday(now)
  );
}

/** The ask showed: no other today. */
export function markNudged(now = Date.now()): void {
  try {
    localStorage.setItem(ASKED_ON_KEY, indiaDay(now));
  } catch {
    // Private windows: it may ask again today, which is harmless.
  }
}

function indiaDay(now: number): string {
  return new Date(now).toLocaleDateString("en-CA", {
    timeZone: "Asia/Kolkata",
  });
}

function askedToday(now: number): boolean {
  try {
    return localStorage.getItem(ASKED_ON_KEY) === indiaDay(now);
  } catch {
    return false;
  }
}

/** Not now: the sheet waits a week on this device. */
export function notNow(now = Date.now()): void {
  try {
    localStorage.setItem(NOT_NOW_KEY, String(now + NOT_NOW_MS));
  } catch {
    // Private windows: the sheet may ask again, which is harmless.
  }
}

function notNowUntilLater(now: number): boolean {
  try {
    const until = Number(localStorage.getItem(NOT_NOW_KEY));
    return Number.isFinite(until) && until > now;
  } catch {
    return false;
  }
}
