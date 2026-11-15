"use client";

/**
 * Home's chosen day (owner, 15 Nov 2026: "people can go on a specific date and
 * see that date's detail and easily go back to the today"): ?day=YYYY-MM-DD in
 * the address, India time; none, today, or a day out of range is today. The server
 * and the first paint draw today, so the two never disagree.
 */

import { useSyncExternalStore } from "react";

/** How far back Home's date can look; the server holds the same bound. */
export const DAYS_BACK = 90;

const DAY_EVENT = "sx:home-day";
/** Marks the history step that left today, so going back to today undoes it. */
const LEFT_TODAY = "sxLeftToday";
const DAY_SHAPE = /^\d{4}-\d{2}-\d{2}$/;
const IST_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });
const SHORT = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});

/** Today in India ("2026-11-15"). */
export const indiaToday = (): string => IST_DAY.format(new Date());

/** A day's noon in India, so no time zone moves it to another date. */
export const noonOf = (day: string): Date => new Date(`${day}T12:00:00+05:30`);

/** The day `by` days after `day` (before, when negative). */
export function shiftDay(day: string, by: number): string {
  const at = noonOf(day);
  at.setUTCDate(at.getUTCDate() + by);
  return IST_DAY.format(at);
}

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** A day as people say it (motion-research-2.md): "Yesterday", "3 days ago"
 *  up to 6 days back, then "Thu, 6 Nov", with the year when it isn't this one. */
export function dayName(day: string): string {
  const today = indiaToday();
  const back = Math.round(
    (noonOf(today).getTime() - noonOf(day).getTime()) / 86_400_000,
  );
  if (back >= 1 && back <= 6) {
    const words = RELATIVE.format(-back, "day");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  const part = Object.fromEntries(
    SHORT.formatToParts(noonOf(day)).map((piece) => [piece.type, piece.value]),
  );
  const year =
    day.slice(0, 4) === today.slice(0, 4) ? "" : ` ${day.slice(0, 4)}`;
  return `${part.weekday}, ${part.day} ${part.month}${year}`;
}

function readDay(): string | null {
  const day = new URLSearchParams(window.location.search).get("day");
  if (!day || !DAY_SHAPE.test(day)) return null;
  const today = indiaToday();
  if (day >= today || day < shiftDay(today, -DAYS_BACK)) return null;
  return day;
}

const onDay = (change: () => void) => {
  window.addEventListener("popstate", change);
  window.addEventListener(DAY_EVENT, change);
  return () => {
    window.removeEventListener("popstate", change);
    window.removeEventListener(DAY_EVENT, change);
  };
};

/** The chosen past day, or null for today; and the way to change it. */
export function useHomeDay(): [string | null, (next: string | null) => void] {
  const day = useSyncExternalStore(onDay, readDay, () => null);
  const choose = (next: string | null) => {
    const target = next && next < indiaToday() ? next : null;
    const state = window.history.state as Record<string, unknown> | null;
    // Leaving today adds a step, so Android's Back returns to today; another past
    // day replaces it; back to today takes that step back (motion-research-2.md).
    if (!target && readDay() && state?.[LEFT_TODAY]) {
      window.history.back();
      return;
    }
    const params = new URLSearchParams(window.location.search);
    if (target) params.set("day", target);
    else params.delete("day");
    const query = params.toString();
    const url = `${window.location.pathname}${query ? `?${query}` : ""}`;
    if (target && !readDay())
      window.history.pushState({ ...state, [LEFT_TODAY]: true }, "", url);
    else window.history.replaceState(state, "", url);
    window.dispatchEvent(new Event(DAY_EVENT));
  };
  return [day, choose];
}
