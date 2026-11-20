/**
 * The words of Home's work queue (round 2, board 2, option C, 20 Nov 2026):
 * where each To Call row stands, how long a new lead has waited, and a
 * follow-up's note only when it says more than the row's name.
 */

import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { ago, type LeadRow } from "../leads/leads-client";
import { breakLength } from "./home-today";

export const CLOCK = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});
export const DAY = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});
const IST_DATE = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });

/** "9:12 AM" today, "Tue, 18 Nov, 9:12 AM" another day. */
export function clockDay(at: string, now: Date = new Date()): string {
  const date = new Date(at);
  return IST_DATE.format(date) === IST_DATE.format(now)
    ? CLOCK.format(date)
    : `${DAY.format(date)}, ${CLOCK.format(date)}`;
}

/** How long, in Home's words: "28 min", "1 h 5 min", "3 days". */
export function waited(minutes: number): string {
  const whole = Math.max(0, Math.floor(minutes));
  if (whole >= 2 * 1440) return `${Math.floor(whole / 1440)} days`;
  return breakLength(whole);
}

/** When the lead arrived: its source's own time when it sent one. */
export const arrivedAt = (lead: LeadRow) => lead.received_at ?? lead.created_at;

/** Never called and nothing planned: a new lead waiting for its first call. */
export const fresh = (lead: LeadRow) =>
  lead.stage === "new" && lead.next_action_at === null && lead.calls === 0;

export type QueueKind = "missed" | "new" | "late" | "later" | "due";

export const KIND_WORDS: Record<QueueKind, string> = {
  missed: "Missed calls",
  new: "New leads",
  late: "Late",
  later: "Later today",
  due: "To call",
};

/** Where a To Call row stands now: rang and missed, new and waiting, late, or later today. */
export function queueKind(lead: LeadRow, now: Date = new Date()): QueueKind {
  if (lead.missed_at) return "missed";
  if (fresh(lead)) return "new";
  if (lead.next_action_at)
    return Date.parse(lead.next_action_at) < now.getTime() ? "late" : "later";
  return "due";
}

/** Minutes a new lead has waited since it came in. */
export function waitingMinutes(lead: LeadRow, now: Date = new Date()): number {
  return (now.getTime() - Date.parse(arrivedAt(lead))) / 60_000;
}

/** Half an hour without a first call: the waiting time turns warm. */
export const LONG_WAIT_MINUTES = 30;

/** A row's one line: how long it waited, when it was due, or what is planned. */
export function queueLine(lead: LeadRow, now: Date = new Date()): string {
  const kind = queueKind(lead, now);
  if (kind === "missed" && lead.missed_at) {
    const more =
      (lead.missed_calls ?? 0) > 1 ? ` · ${lead.missed_calls} calls` : "";
    return `Missed call ${ago(lead.missed_at, now)}${more}`;
  }
  if (kind === "new") return `Waiting ${waited(waitingMinutes(lead, now))}`;
  if (kind === "late" && lead.next_action_at)
    return `Was due ${clockDay(lead.next_action_at, now)}`;
  if (kind === "later" && lead.next_action_at)
    return CLOCK.format(new Date(lead.next_action_at));
  return lead.why;
}

/**
 * What the lead's follow-up says, unless it only repeats the row's name (the
 * owner's board, 20 Nov 2026: Today's list read "Call back Shubham Rao … Call
 * back Shubham Rao").
 */
export function noteBeside(
  note: string | null | undefined,
  name: string,
): string | null {
  const words = note?.trim();
  if (!words) return null;
  const said = displayName(name).toLowerCase();
  return said && words.toLowerCase().includes(said) ? null : words;
}

/** "Priya Deshmukh" → "PD". */
export const initials = (name: string) =>
  displayName(name)
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();

/** The clock, once a minute, so waiting times keep up while Home is open. */
export function useMinute(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}
