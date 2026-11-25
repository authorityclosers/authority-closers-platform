/**
 * Find my old calls (owner, 20 Nov 2026: "it automatically scans old calls
 * and auto fetches and asks the user for analysis, or analyses itself
 * smartly… the call logs can be used to fetch the calls back again"). The
 * server knows each seller's lead calls with no recording (call history sync
 * and calls from the app: /capture-setup/missing/{day}); the phone app finds
 * each one's recording in its folder (findOldRecordings, sales-xray-apps #38:
 * the lead's number and the call's time, the strict RecordingMatch rules).
 * Pure rules here, so they are tested without a phone.
 *
 * Consent: never analysed without it. With "Analyse my calls automatically"
 * on, the found calls go up by themselves; otherwise the seller makes one
 * choice (Analyse all, Pick calls, Not now) with nothing ticked for them.
 * A call that only fits by time is never sent by itself.
 */

import type { MissingCall } from "../../capture-setup/capture-setup-client";
import { parseRecording, type NativeRecording } from "../../leads/native-phone";
import type { AutoAnalysis } from "../../settings/auto-analysis-client";

/** How far back the look goes, in India days (today included). */
export const LOOK_BACK_DAYS = 30;
/** The quiet look on Calls runs at most this often. */
export const QUIET_EVERY_MS = 6 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

/** How a recording fits its call: its file names the lead's number, a contact, or only the time fits. */
export type Fit = "number" | "contact" | "time";

export type OldCall = Readonly<{
  /** The call's row on the lead: the recording joins it, never a new call. */
  eventId: string;
  leadId: string;
  leadName: string;
  /** When the call began (ISO). */
  at: string;
  seconds: number;
  fit: Fit;
  recording: NativeRecording;
}>;

/** A recording in the window the phone could put on none of these calls. */
export type Unplaced = Readonly<{
  startedMs: number;
  seconds: number;
  recording: NativeRecording;
}>;

export type PhoneFound = Readonly<{
  access: "ok" | "none" | "hidden";
  scanned: number;
  items: ReadonlyArray<{
    eventId: string;
    fit: Fit;
    recording: NativeRecording;
  }>;
  unmatched: ReadonlyArray<Unplaced>;
}>;

export type OldCallsScan = Readonly<{
  access: PhoneFound["access"];
  /** Recordings the phone looked at in the window. */
  scanned: number;
  /** Lead calls in the window with no recording on Sales X-Ray. */
  missing: number;
  calls: ReadonlyArray<OldCall>;
  unplaced: ReadonlyArray<Unplaced>;
}>;

const FITS = new Set<Fit>(["number", "contact", "time"]);
const ACCESS = new Set(["ok", "none", "hidden"]);

const count = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : 0;

/** India's calendar day of a moment, "2026-11-20". */
export function indiaDay(at: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(at);
}

/** The window's India days, today first. */
export function lookBackDays(
  now: Date,
  days: number = LOOK_BACK_DAYS,
): string[] {
  const out: string[] = [];
  for (let back = 0; back < days; back++)
    out.push(indiaDay(new Date(now.getTime() - back * DAY_MS)));
  return [...new Set(out)];
}

/** The phone's findOldRecordings reply; null when it isn't one. */
export function parseFound(raw: unknown): PhoneFound | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (!Array.isArray(value.items)) return null;
  const items = value.items.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const row = item as Record<string, unknown>;
    const recording = parseRecording(row.recording);
    const fit = row.fit as Fit;
    if (typeof row.eventId !== "string" || !row.eventId || !recording)
      return [];
    return [
      { eventId: row.eventId, fit: FITS.has(fit) ? fit : "time", recording },
    ];
  });
  const unmatched = (Array.isArray(value.unmatched) ? value.unmatched : [])
    .flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const row = item as Record<string, unknown>;
      const recording = parseRecording(row.recording);
      if (!recording || !recording.supported) return [];
      if (recording.check?.verdict === "silent") return [];
      return [
        {
          startedMs: count(row.startedMs),
          seconds: count(row.seconds),
          recording,
        },
      ];
    })
    .sort((a, b) => b.startedMs - a.startedMs)
    .slice(0, 30);
  return {
    access: ACCESS.has(String(value.access))
      ? (value.access as PhoneFound["access"])
      : "ok",
    scanned: count(value.scanned),
    items,
    unmatched,
  };
}

/**
 * The server's calls with no recording and the phone's matches, as the
 * seller's found calls: only calls the server listed (so each lands on its
 * own row), each once, readable and not silent, newest first.
 */
export function joinFound(
  missing: ReadonlyArray<MissingCall>,
  found: PhoneFound,
): OldCall[] {
  const byEvent = new Map(missing.map((call) => [call.event_id, call]));
  const seen = new Set<string>();
  const calls: OldCall[] = [];
  for (const item of found.items) {
    const call = byEvent.get(item.eventId);
    if (!call || seen.has(item.eventId)) continue;
    if (!item.recording.supported) continue;
    if (item.recording.check?.verdict === "silent") continue;
    seen.add(item.eventId);
    calls.push({
      eventId: call.event_id,
      leadId: call.lead_id,
      leadName: call.lead_name ?? "",
      at: call.at,
      seconds: call.seconds,
      fit: item.fit,
      recording: item.recording,
    });
  }
  return calls.sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

/** The server's missing calls from several days' reads, each once, newest first. */
export function mergeMissing(
  days: ReadonlyArray<ReadonlyArray<MissingCall> | null>,
): MissingCall[] {
  const byEvent = new Map<string, MissingCall>();
  for (const day of days)
    for (const call of day ?? []) byEvent.set(call.event_id, call);
  return [...byEvent.values()].sort(
    (a, b) => Date.parse(b.at) - Date.parse(a.at),
  );
}

export type Buckets = Readonly<{ sure: number; likely: number; time: number }>;

export function buckets(calls: ReadonlyArray<OldCall>): Buckets {
  return {
    sure: calls.filter((call) => call.fit === "number").length,
    likely: calls.filter((call) => call.fit === "contact").length,
    time: calls.filter((call) => call.fit === "time").length,
  };
}

/** The match in a word: Sure (the lead's number), Likely (a contact), Time only. */
export function fitWord(fit: Fit): string {
  return fit === "number" ? "Sure" : fit === "contact" ? "Likely" : "Time only";
}

/**
 * Which way the found calls go: "auto" when the seller's standing consent
 * lets a found recording start by itself, else "ask" (off, never chosen,
 * changed words, or a personal workspace): one choice, nothing ticked.
 */
export type ConsentPath = "auto" | "ask";

export function consentPath(auto: AutoAnalysis | null): ConsentPath {
  return auto?.can_start === true ? "auto" : "ask";
}

/** The consent word sx.old_calls carries. */
export function consentWord(
  auto: AutoAnalysis | null,
): "on" | "off" | "ask" | "unavailable" {
  return auto?.state ?? "unavailable";
}

/**
 * The calls that may go up by themselves under standing consent: a sure or
 * likely match only. A time-only match waits for the seller's own tap.
 */
export function autoCalls(calls: ReadonlyArray<OldCall>): OldCall[] {
  return calls.filter((call) => call.fit !== "time");
}

/** "12 recorded calls with your leads". */
export function headline(found: number): string {
  return found === 1
    ? "1 recorded call with a lead"
    : `${found} recorded calls with your leads`;
}

export type RowState =
  | "waiting"
  | "reading"
  | "uploading"
  | "done"
  | "failed"
  | "stopped";

export const ROW_WORDS: Record<RowState, string> = {
  waiting: "Waiting",
  reading: "Getting it from your phone",
  uploading: "Uploading for analysis",
  done: "Analysis started",
  failed: "Didn't upload",
  stopped: "Stopped",
};

/** "7 of 12 done". */
export function progressLine(
  states: Readonly<Record<string, RowState>>,
  total: number,
): string {
  const done = Object.values(states).filter((state) => state === "done").length;
  return `${done} of ${total} done`;
}

/** Found calls the seller hasn't dealt with yet (analysed, or said Not this call). */
export function newCalls(
  calls: ReadonlyArray<OldCall>,
  handled: ReadonlySet<string>,
): OldCall[] {
  return calls.filter((call) => !handled.has(call.eventId));
}

/**
 * The card's words: the first look, new calls found since the last look, or
 * (quiet) nothing new, with a way to look again.
 */
export function cardWords(state: { scannedAt: number | null; fresh: number }): {
  title: string;
  note: string;
  button: string;
  quiet: boolean;
} {
  if (state.scannedAt === null)
    return {
      title: "Find my old calls",
      note: `Your phone may have recorded calls with your leads in the last ${LOOK_BACK_DAYS} days.`,
      button: "Look now",
      quiet: false,
    };
  if (!state.fresh)
    return {
      title: "Old calls",
      note: "Nothing new since your last look",
      button: "Look again",
      quiet: true,
    };
  return {
    title:
      state.fresh === 1
        ? "1 new recorded call found"
        : `${state.fresh} new recorded calls found`,
    note: "From your phone, with your leads",
    button: "Review",
    quiet: false,
  };
}

/** A quiet look is due on Calls: never looked, or the last look is old. */
export function quietLookDue(lastAt: number | null, now: number): boolean {
  return lastAt === null || now - lastAt >= QUIET_EVERY_MS || now < lastAt;
}
