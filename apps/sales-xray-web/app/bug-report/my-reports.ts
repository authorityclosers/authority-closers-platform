/**
 * "We'll tell you when it's fixed": the app looks at the person's own reports
 * now and then (at most every six hours, a few seconds after the frame is up)
 * and says so in a corner card when one has been fixed since it last looked.
 * What it last saw is kept on this device; the first look only remembers.
 */

import { myReports, type MyReport } from "./bug-report-client";

const KEY = "sx-my-reports-seen";
const LOOKED = "sx-my-reports-looked";
const EVERY_MS = 6 * 3600 * 1000;

export const STATUS_WORDS: Record<string, string> = {
  new: "Sent",
  triaged: "Seen by the team",
  in_progress: "Being fixed",
  fixed: "Fixed",
  verified: "Fixed",
  closed: "Closed",
};

function load(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function save(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private mode: it asks again next time.
  }
}

/** Reports fixed since the last look, given what was seen then. */
export function newlyFixed(
  reports: readonly MyReport[],
  seen: Record<string, string> | null,
): MyReport[] {
  if (!seen) return [];
  return reports.filter(
    (report) =>
      (report.status === "fixed" || report.status === "verified") &&
      seen[report.bugId] !== undefined &&
      seen[report.bugId] !== "fixed" &&
      seen[report.bugId] !== "verified",
  );
}

/** Look now if it is time; returns the reports fixed since the last look. */
export async function lookForFixes(now = Date.now()): Promise<MyReport[]> {
  const looked = Number(load(LOOKED) ?? 0);
  if (now - looked < EVERY_MS) return [];
  const reports = await myReports();
  let seen: Record<string, string> | null = null;
  try {
    seen = JSON.parse(load(KEY) ?? "null") as Record<string, string> | null;
  } catch {
    seen = null;
  }
  const fixed = newlyFixed(reports, seen);
  save(
    KEY,
    JSON.stringify(Object.fromEntries(reports.map((r) => [r.bugId, r.status]))),
  );
  save(LOOKED, String(now));
  return fixed;
}

/** After a send: remember the new report as sent, so a later fix is news. */
export function rememberSent(bugId: string): void {
  let seen: Record<string, string> = {};
  try {
    seen = (JSON.parse(load(KEY) ?? "{}") as Record<string, string>) ?? {};
  } catch {
    seen = {};
  }
  save(KEY, JSON.stringify({ ...seen, [bugId]: "new" }));
}
