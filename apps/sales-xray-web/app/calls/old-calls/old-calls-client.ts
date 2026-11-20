/**
 * Find my old calls, the reads: the server's lead calls with no recording
 * over the last 14 India days (one read a day, as the bell's reminder reads
 * them), after the phone looks at its call history again so calls it missed
 * become rows; then the phone's matches for them (findOldRecordings). The
 * lead's number goes to the phone only, inside the app, never into a log.
 * What the seller dealt with stays on this phone (handled), so the card on
 * Calls shows only new ones. Rules: old-calls-rules.
 */

import {
  readMissingRecordings,
  type MissingCall,
} from "../../capture-setup/capture-setup-client";
import { readLead, type LeadDetail } from "../../leads/leads-client";
import {
  callLogSyncNow,
  findOldRecordings,
  inPhoneApp,
} from "../../leads/native-phone";
import {
  LOOK_BACK_DAYS,
  joinFound,
  lookBackDays,
  mergeMissing,
  parseFound,
  type OldCallsScan,
} from "./old-calls-rules";

export type ScanOutcome =
  | { scan: OldCallsScan; leads: Record<string, LeadDetail> }
  /** A browser or iPhone: no recordings to look at. */
  | { error: "no_app" }
  /** An Android app without findOldRecordings (before sales-xray-apps #38). */
  | { error: "old_app" }
  | { error: "failed" };

const HANDLED = "sx:old-calls:handled";
const LOOKED = "sx:old-calls:looked";
const HANDLED_MAX = 500;

/** Run `work` over `items`, `limit` at a time. */
async function inTurns<T, R>(
  items: ReadonlyArray<T>,
  limit: number,
  work: (item: T) => Promise<R>,
): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, async () => {
      while (next < items.length) {
        const index = next++;
        out[index] = await work(items[index]);
      }
    }),
  );
  return out;
}

/** The phone's look back: never uploads; recordings stay on the phone. */
export async function scanOldCalls(
  signal?: AbortSignal,
  now: Date = new Date(),
): Promise<ScanOutcome> {
  if (!inPhoneApp()) return { error: "no_app" };
  // Lead calls the phone's call history holds but Sales X-Ray doesn't yet.
  await callLogSyncNow(LOOK_BACK_DAYS);
  const days = await inTurns(lookBackDays(now), 4, (day) =>
    readMissingRecordings(signal, day).then(
      (read) => read.items,
      () => null,
    ),
  );
  if (signal?.aborted) return { error: "failed" };
  if (days.every((day) => day === null)) return { error: "failed" };
  const missing = mergeMissing(days);
  // Each call's lead: its number for the phone's match, and the lead to upload onto.
  const leadIds = [...new Set(missing.map((call) => call.lead_id))];
  const details = await inTurns(leadIds, 6, (id) =>
    readLead(id, signal).then(
      (detail) => detail,
      () => null,
    ),
  );
  const leads: Record<string, LeadDetail> = {};
  details.forEach((detail, index) => {
    if (detail) leads[leadIds[index]] = detail;
  });
  const calls = missing.flatMap((call: MissingCall) => {
    const phone = leads[call.lead_id]?.phone;
    return phone
      ? [
          {
            eventId: call.event_id,
            number: phone,
            startedMs: Date.parse(call.at),
            seconds: call.seconds,
          },
        ]
      : [];
  });
  let raw: unknown;
  try {
    raw = await findOldRecordings({
      calls,
      sinceMs: now.getTime() - LOOK_BACK_DAYS * 24 * 60 * 60 * 1000,
    });
  } catch (error) {
    return error instanceof Error && error.message === "unknown_method"
      ? { error: "old_app" }
      : { error: "failed" };
  }
  const found = parseFound(raw);
  if (!found) return { error: "failed" };
  return {
    scan: {
      access: found.access,
      scanned: found.scanned,
      missing: missing.length,
      calls: joinFound(missing, found).filter((call) => leads[call.leadId]),
      unplaced: found.unmatched,
    },
    leads,
  };
}

function readList(key: string): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(key) ?? "[]") as unknown;
    return Array.isArray(raw)
      ? raw.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

/** Calls and recordings the seller dealt with on this phone. */
export function readHandled(): Set<string> {
  return new Set(readList(HANDLED));
}

export function markHandled(ids: ReadonlyArray<string>): void {
  if (!ids.length) return;
  try {
    const next = [...new Set([...readList(HANDLED), ...ids])].slice(
      -HANDLED_MAX,
    );
    localStorage.setItem(HANDLED, JSON.stringify(next));
  } catch {
    // Private mode: the card may show a call again; nothing goes up twice.
  }
}

/** When this phone last looked (ms), or null. */
export function readLooked(): number | null {
  try {
    const raw = Number(localStorage.getItem(LOOKED));
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  } catch {
    return null;
  }
}

export function markLooked(at: number = Date.now()): void {
  try {
    localStorage.setItem(LOOKED, String(at));
  } catch {
    // Nothing kept: the card offers the look again.
  }
}
