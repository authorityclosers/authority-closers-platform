/**
 * The Reports library's data (Dipak's Reports V4 spec, 13 Nov 2026, section
 * 23): every saved call of this account, from the list the Calls page reads,
 * with how it arrived, its lead's side and whether this person saved it.
 * Counts, dates and order come from the stored rows, never from formatted text.
 *
 * GET /submissions?order=newest&limit=100&include_summary&include_leads
 * &include_owners&include_kind&include_saved, page after page; each page passes
 * the list's own contract (parseSubmissionLibraryPage) and the three extra
 * fields are checked here.
 */

import {
  acquisition,
  parseSubmissionLibraryPage,
  submissionPath,
  UUID,
  type LibrarySubmission,
} from "../acquisition-client";
import { callTitle } from "../call-label";
import { callTone, submissionState } from "../call-status";
import { dayKey, type DisplayDates } from "../display-dates";
import { displayName } from "../display-name";
import { ReportContractError } from "../report-contract";
import type { ReportRow, ReportSource } from "./report-filter";

export const REPORTS_PAGE = 100;
/** The most calls parseSubmissionLibraryPage takes in one page. */
const CONTRACT_PAGE = 20;
/** At most this many pages (2,000 calls) for one library. */
export const REPORTS_MAX_PAGES = 20;

export const reportsListPath = (before: string | null) =>
  `/submissions?order=newest&limit=${REPORTS_PAGE}&include_summary=true&include_leads=true&include_owners=true&include_kind=true&include_saved=true${before ? `&before=${encodeURIComponent(before)}` : ""}`;

/** What Reports adds to a listed call. */
export type ReportFacts = Readonly<{
  upload: "auto" | "manual";
  leadSide: "inbound" | "cold" | null;
  saved: boolean;
}>;

export type ReportsPage = Readonly<{
  submissions: readonly LibrarySubmission[];
  facts: ReadonlyMap<string, ReportFacts>;
  nextCursor: string | null;
}>;

const EXTRA = ["upload", "lead_side", "saved"] as const;

/** One page of the list, with Reports' three fields checked and set aside. */
export function parseReportsPage(value: unknown): ReportsPage {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new ReportContractError("reports_library");
  const body = value as Record<string, unknown>;
  if (!Array.isArray(body.submissions))
    throw new ReportContractError("reports_library");
  const facts = new Map<string, ReportFacts>();
  const plain = body.submissions.map((item: unknown) => {
    if (!item || typeof item !== "object" || Array.isArray(item))
      throw new ReportContractError("reports_library");
    const row = { ...(item as Record<string, unknown>) };
    const upload = row.upload;
    const side = row.lead_side;
    const saved = row.saved;
    if (
      (upload !== "auto" && upload !== "manual") ||
      (side !== "inbound" && side !== "cold" && side !== null) ||
      typeof saved !== "boolean" ||
      typeof row.submission_id !== "string"
    )
      throw new ReportContractError("reports_library");
    for (const key of EXTRA) delete row[key];
    facts.set(row.submission_id, { upload, leadSide: side, saved });
    return row;
  });
  // The list's contract reads a page of at most 20 calls (the Calls page's
  // size): a 100-call page passes it 20 rows at a time, the cursor once.
  const cursor = body.next_cursor;
  if (
    Object.keys(body).some(
      (key) => key !== "submissions" && key !== "next_cursor",
    ) ||
    plain.length > REPORTS_PAGE ||
    (cursor !== null && (typeof cursor !== "string" || !UUID.test(cursor)))
  )
    throw new ReportContractError("reports_library");
  const submissions: LibrarySubmission[] = [];
  const ids = new Set<string>();
  for (let start = 0; start < plain.length; start += CONTRACT_PAGE) {
    const part = parseSubmissionLibraryPage({
      submissions: plain.slice(start, start + CONTRACT_PAGE),
      next_cursor: null,
    });
    for (const submission of part.submissions) {
      if (ids.has(submission.id))
        throw new ReportContractError("reports_library");
      ids.add(submission.id);
      submissions.push(submission);
    }
  }
  return { submissions, facts, nextCursor: cursor as string | null };
}

/** A report's source (report-filter.ts): an auto call with no lead is Inbound. */
export function sourceOf(facts: ReportFacts): ReportSource {
  if (facts.upload === "manual") return "manual";
  return facts.leadSide === "cold" ? "cold_auto" : "inbound_auto";
}

/** How the Report's overview says the call ended, as a topic (call-auto-title.ts). */
const OUTCOME_TOPICS: Record<string, string> = {
  closed: "Deal closed",
  follow_up: "Follow-up agreed",
  future_date: "Meeting scheduled",
  no_sale: "No sale",
  disqualified: "Not a fit",
};

/**
 * The card's topic: the call's own name when it has one, else what the
 * Report says happened, else how it arrived.
 */
export function topicOf(
  submission: LibrarySubmission,
  facts: ReportFacts,
): string {
  const outcome = submission.summary?.outcome;
  const fallback =
    (outcome ? OUTCOME_TOPICS[outcome] : undefined) ??
    (facts.upload === "manual" ? "Uploaded recording" : "Sales call");
  return callTitle(submission.label, fallback);
}

export function toReportRow(
  submission: LibrarySubmission,
  facts: ReportFacts,
  dates: Pick<DisplayDates, "timeZone">,
  viewerId: string | null,
): ReportRow {
  const createdMs = Date.parse(submission.createdAt);
  const summary = submission.summary ?? null;
  return {
    id: submission.id,
    createdAt: submission.createdAt,
    createdMs,
    day: dayKey(createdMs, dates.timeZone) ?? submission.createdAt.slice(0, 10),
    prospect: submission.lead ? displayName(submission.lead.name) : null,
    topic: topicOf(submission, facts),
    summary:
      summary?.assessment ?? summary?.fixFirst ?? summary?.nextFocus ?? null,
    durationSeconds: submission.durationSeconds,
    status: submissionState(submission),
    ready: submission.hasReport,
    active: callTone(submission) === "active",
    source: sourceOf(facts),
    saved: facts.saved,
    owner:
      submission.owner && submission.owner.personId !== viewerId
        ? displayName(submission.owner.name)
        : null,
  };
}

/** The whole library, newest first, page after page (at most 2,000 calls). */
export async function readReports(
  dates: Pick<DisplayDates, "timeZone">,
  viewerId: string | null,
  signal?: AbortSignal,
  onPage?: (rows: ReportRow[], complete: boolean) => void,
): Promise<ReportRow[]> {
  const rows: ReportRow[] = [];
  const seen = new Set<string>();
  let before: string | null = null;
  for (let page = 0; page < REPORTS_MAX_PAGES; page += 1) {
    const read = parseReportsPage(
      await acquisition(reportsListPath(before), { signal }),
    );
    for (const submission of read.submissions) {
      const facts = read.facts.get(submission.id);
      if (!facts || seen.has(submission.id)) continue;
      seen.add(submission.id);
      rows.push(toReportRow(submission, facts, dates, viewerId));
    }
    before = read.nextCursor;
    onPage?.([...rows], before === null);
    if (before === null) break;
  }
  return rows;
}

/** Save or unsave a report for the signed-in person; the server's answer. */
export async function saveReport(
  id: string,
  saved: boolean,
  signal?: AbortSignal,
): Promise<boolean> {
  const body = await acquisition(`${submissionPath(id)}/saved`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ saved }),
    signal,
  });
  if (
    !body ||
    typeof body !== "object" ||
    typeof (body as { saved?: unknown }).saved !== "boolean"
  )
    throw new ReportContractError("report_saved");
  return (body as { saved: boolean }).saved;
}

/**
 * The last library read per identity (person, session, workspace), so coming
 * back from a report paints at once and reads again quietly. Memory only:
 * private rows never reach storage.
 */
type Shelf = { rows: ReportRow[]; complete: boolean };
const shelves = new Map<string, Shelf>();
const listeners = new Set<() => void>();

export function shelvedReports(identity: string): Shelf | null {
  return shelves.get(identity) ?? null;
}

export function shelveReports(identity: string, shelf: Shelf) {
  shelves.set(identity, shelf);
  for (const listener of listeners) listener();
}

/** One report's Save, applied to every shelf that holds it. */
export function markSaved(id: string, saved: boolean) {
  for (const [identity, shelf] of shelves)
    if (shelf.rows.some((row) => row.id === id))
      shelves.set(identity, {
        ...shelf,
        rows: shelf.rows.map((row) =>
          row.id === id ? { ...row, saved } : row,
        ),
      });
  for (const listener of listeners) listener();
}

export function watchShelves(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** For tests: forget every shelf. */
export function forgetReports() {
  shelves.clear();
}
