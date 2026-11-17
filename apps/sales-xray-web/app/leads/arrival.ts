"use client";

/**
 * When a lead came in (owner, 16 Nov 2026, after a client's admin asked "when
 * did this lead actually generate?"): the time its source says the person sent
 * it (a Meta form's time), else when it reached Sales X-Ray. A list row says it
 * short ("2 h", "Yesterday", "3 d", "12 Oct"); the lead's Timeline says it in
 * full with how long ago. A lead that came in since the person last opened
 * Leads is marked New.
 */

import { useEffect, useSyncExternalStore } from "react";

import { ago } from "./leads-client";

type Times = { received_at?: string | null; created_at: string };

/** The arrival: the person's own time when the source gave one. */
export const arrivedAt = (row: Times): string =>
  row.received_at ?? row.created_at;

const startOfDay = (at: Date) =>
  new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();

/** Whole calendar days from `at` to `now` on this phone's clock. */
function calendarDays(at: Date, now: Date): number {
  return Math.round((startOfDay(now) - startOfDay(at)) / 86_400_000);
}

/** "now", "5 min", "2 h" (today), "Yesterday", "3 d" (this week), "12 Oct",
 *  "12 Oct 2025" (another year). */
export function arrivedShort(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const minutes = Math.floor((now.getTime() - at.getTime()) / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes} min`;
  const days = calendarDays(at, now);
  if (days <= 0) return `${Math.floor(minutes / 60)} h`;
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} d`;
  return at.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    ...(at.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** "16 Nov, 10:42 am" (with the year when it isn't this one): when Meta made
 *  a lead, at the top of its page (Shivam's review, 17 Nov 2026). */
export function metaWhen(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const day = at.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    ...(at.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  const time = at
    .toLocaleTimeString("en-IN", {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    })
    .replace(/\s(am|pm)$/i, " $1");
  return `${day}, ${time}`;
}

/** "16 Nov 2026, 3:16 pm": a moment in full, one format whatever the locale. */
export function fullTime(iso: string): string {
  return new Date(iso)
    .toLocaleString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    })
    .replace(/\s(am|pm)$/i, " $1");
}

/** The Timeline's line: "16 Nov 2026, 3:16 pm · 2 h ago". */
export function timelineWords(iso: string, now: Date = new Date()): string {
  return `${fullTime(iso)} · ${ago(iso, now)}`;
}

/** Arrived after the person last opened Leads (never on a first visit). */
export function isNewSince(row: Times, seenAt: number | null): boolean {
  return seenAt !== null && Date.parse(arrivedAt(row)) > seenAt;
}

export const SEEN_KEY = "sales-xray:leads-seen-at";

// When Leads was last left on this phone, read once per visit.
let lastSeen: number | null | undefined;
const readSeen = (): number | null => {
  if (lastSeen === undefined) {
    try {
      const saved = Number(window.localStorage.getItem(SEEN_KEY));
      lastSeen = Number.isFinite(saved) && saved > 0 ? saved : null;
    } catch {
      // Storage off (a private window): no New marks.
      lastSeen = null;
    }
  }
  return lastSeen;
};
const still = () => () => undefined;

/** When this person last left Leads on this phone; null on a first visit (no
 *  New marks) and on the server. */
export function useSeenAt(): number | null {
  return useSyncExternalStore(still, readSeen, () => null);
}

/** Leads is open: when it closes or the app goes to the background, this
 *  visit is the last, and the next visit reads it again. */
// A close waiting one tick: React's development double mount (and any quick
// remount) closes Leads and opens it again at once, which is not leaving it.
let leaving: ReturnType<typeof setTimeout> | undefined;

export function useMarkSeen() {
  useEffect(() => {
    clearTimeout(leaving);
    leaving = undefined;
    const mark = () => {
      try {
        window.localStorage.setItem(SEEN_KEY, String(Date.now()));
      } catch {
        // Storage off: nothing to keep.
      }
    };
    const hidden = () => {
      if (document.visibilityState === "hidden") mark();
    };
    document.addEventListener("visibilitychange", hidden);
    return () => {
      document.removeEventListener("visibilitychange", hidden);
      leaving = setTimeout(() => {
        leaving = undefined;
        mark();
        lastSeen = undefined;
      }, 0);
    };
  }, []);
}

/** Tests: read the last visit again. */
export function forgetSeen() {
  lastSeen = undefined;
}
