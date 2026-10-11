/*
 * One person in the organisation (owner, 11 Oct: people pages like Pulse).
 * Everything here is read from the organisation's existing answers: the
 * member directory, the organisation's activity for the last twelve weeks
 * and, for skills and outcomes, the labels each report already gave. Nothing
 * is scored or ranked (AC-SVAL).
 */
import { submissionState, callTone, type CallTone } from "../../call-status";
import type { OrgActivity, OrgMember, PersonWeeks } from "../organisation-api";
import type { ReportPattern } from "../team-patterns";
import { getReportUiCopy } from "../../report-ui-copy";

/** Twelve 7-day weeks, within the activity read's 90-day limit. */
export const PERSON_WEEKS = 12;
export const PERSON_DAYS = PERSON_WEEKS * 7;
const WEEK_MS = 7 * 86_400_000;

/** The profile address for an active member (person id) or an invite. */
export const personHref = (id: string) =>
  `/organisation/people/${encodeURIComponent(id.toLowerCase())}`;

export type PersonCall = OrgActivity["calls"][number];

/** The directory row for this address: a person id or an invite id. */
export function findMember(members: OrgMember[], id: string): OrgMember | null {
  const key = id.toLowerCase();
  return (
    members.find(
      (member) =>
        member.personId?.toLowerCase() === key ||
        member.inviteId?.toLowerCase() === key,
    ) ?? null
  );
}

export type PersonActivity = {
  calls: number;
  minutes: number;
  reportsReady: number;
  /** Newest first: this person's calls among those the server listed. */
  listed: PersonCall[];
  /** Whether `listed` holds every call the totals count. */
  complete: boolean;
  lastCallAt: string | null;
};

/**
 * Totals come from the server's per-person counts (every permitted call in
 * the window); the list and the weekly bars from the calls it listed (the
 * newest 500 across the organisation), so a busy organisation can list fewer
 * than it counts. `complete` says which.
 */
export function personActivity(
  activity: OrgActivity,
  personId: string,
): PersonActivity {
  const key = personId.toLowerCase();
  const rep = activity.perRep.find((row) => row.personId.toLowerCase() === key);
  const listed = activity.calls
    .filter((call) => call.ownerPersonId.toLowerCase() === key)
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  const listedMinutes =
    listed.reduce((sum, call) => sum + call.durationSeconds, 0) / 60;
  const calls = rep?.calls ?? listed.length;
  return {
    calls,
    minutes: rep?.recordedMinutes ?? listedMinutes,
    reportsReady:
      rep?.reportsReady ?? listed.filter((call) => call.hasReport).length,
    listed,
    complete: listed.length >= calls,
    lastCallAt: listed[0]?.createdAt ?? null,
  };
}

export type Week = { start: number; calls: number; minutes: number };

/** Twelve rolling 7-day weeks ending now, oldest first (this week last). */
export function weeklyTotals(
  calls: PersonCall[],
  now = Date.now(),
  weeks = PERSON_WEEKS,
): Week[] {
  const out = Array.from({ length: weeks }, (_, index) => ({
    start: now - (weeks - index) * WEEK_MS,
    calls: 0,
    minutes: 0,
  }));
  for (const call of calls) {
    const at = Date.parse(call.createdAt);
    if (!Number.isFinite(at)) continue;
    const age = Math.floor((now - at) / WEEK_MS);
    if (age < 0 || age >= weeks) continue;
    const week = out[weeks - 1 - age];
    week.calls += 1;
    week.minutes += call.durationSeconds / 60;
  }
  return out.map((week) => ({ ...week, minutes: Math.round(week.minutes) }));
}

/** What the profile draws: the figures, the listed calls and the weeks. */
export type PersonSummary = { data: PersonActivity; weeks: Week[] };

/**
 * From the per-person read: weeks and totals count every call; the newest
 * calls (up to 50) are listed.
 */
export function fromPersonWeeks(read: PersonWeeks): PersonSummary {
  const listed = [...read.calls].sort(
    (a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt),
  );
  return {
    data: {
      calls: read.totals.calls,
      minutes: read.totals.recordedMinutes,
      reportsReady: read.totals.reportsReady,
      listed,
      complete: listed.length >= read.totals.calls,
      lastCallAt: listed[0]?.createdAt ?? null,
    },
    weeks: read.weeks.map((week) => ({
      start: Date.parse(week.start),
      calls: week.calls,
      minutes: Math.round(week.recordedMinutes),
    })),
  };
}

/** From the organisation's read (servers without the per-person one). */
export function fromOrganisation(
  activity: OrgActivity,
  personId: string,
  now = Date.now(),
): PersonSummary {
  const data = personActivity(activity, personId);
  return { data, weeks: weeklyTotals(data.listed, now) };
}

/** The call-status helpers take a library row; the activity row has its parts. */
export function callStatus(call: PersonCall): {
  label: string;
  tone: CallTone;
} {
  const submission = {
    id: call.id,
    createdAt: call.createdAt,
    durationSeconds: call.durationSeconds,
    state: call.state,
    hasReport: call.hasReport,
    label: null,
  };
  return { label: submissionState(submission), tone: callTone(submission) };
}

export type SkillCell = { callId: string; status: string | null };
export type SkillRow = { id: string; label: string; cells: SkillCell[] };

/**
 * Each skill the reports assessed, against the calls they were read from
 * (oldest first, so time runs left to right). A call whose report didn't
 * mention the skill has an empty cell.
 */
export function skillMatrix(
  reads: { callId: string; pattern: ReportPattern }[],
): SkillRow[] {
  const ordered = [...reads].reverse();
  const rows = new Map<string, SkillRow>();
  for (const { pattern } of ordered)
    for (const skill of pattern.skills)
      if (!rows.has(skill.id))
        rows.set(skill.id, { id: skill.id, label: skill.label, cells: [] });
  for (const row of rows.values())
    row.cells = ordered.map(({ callId, pattern }) => ({
      callId,
      status:
        pattern.skills.find((skill) => skill.id === row.id)?.status ?? null,
    }));
  return [...rows.values()];
}

/**
 * The report's own skill words (report-ui-copy.ts, Dipak's): the same word
 * here as in the Report. Not a score, so the cells use shapes (filled, half,
 * ring), never good/bad colour.
 */
const WORDS = getReportUiCopy("en").factorStatus;
const MARKS: Record<string, string> = {
  observed: "full",
  partial: "half",
  insufficient_evidence: "ring",
  conflicted: "mixed",
  not_applicable: "none",
  unknown: "none",
};
export const SKILL_STATUS: Record<string, { label: string; mark: string }> =
  Object.fromEntries(
    Object.entries(MARKS).map(([status, mark]) => [
      status,
      { label: WORDS[status] ?? status.replace(/_/g, " "), mark },
    ]),
  );

export function skillStatus(status: string | null) {
  if (status === null) return { label: "Not in this report", mark: "none" };
  return (
    SKILL_STATUS[status] ?? { label: status.replace(/_/g, " "), mark: "none" }
  );
}
