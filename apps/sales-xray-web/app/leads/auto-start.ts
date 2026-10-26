/**
 * After a call, whether its recording starts by itself (owner, 26 Oct 2026:
 * "Analyse my calls automatically", the seller's standing consent; the
 * server's view is read with settings/auto-analysis-client.ts):
 *
 * - "start": the consent is on for the terms in force: upload with no tap;
 * - "ask": never chosen, or the words or the terms changed since: offer the
 *   sheet, unless the person said Not now on this device within the week;
 * - "tap": everything else (off, a personal workspace, not read): today's
 *   one tap.
 *
 * Not now records nothing about consent: it only keeps the sheet away.
 */
import type { AutoAnalysis } from "../settings/auto-analysis-client";

export type AfterCallStart = "start" | "ask" | "tap";

export const NOT_NOW_KEY = "sx.autoAnalysis.notNowUntil";
export const NOT_NOW_MS = 7 * 24 * 60 * 60 * 1000;

/** Where the person turns it off again. */
export const AUTO_ANALYSIS_SETTINGS_HREF = "/settings?section=privacy";

export function afterCallStart(
  view: AutoAnalysis | null,
  now = Date.now(),
): AfterCallStart {
  if (!view) return "tap";
  if (view.can_start) return "start";
  if (view.state === "ask" && !notNowUntilLater(now)) return "ask";
  return "tap";
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
