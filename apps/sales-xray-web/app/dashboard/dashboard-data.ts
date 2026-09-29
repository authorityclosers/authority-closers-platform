/**
 * Live dashboard reads (AUT-169). Every number comes from the signed-in
 * account's own data. An empty account reads as zeros and empty lists; a read
 * this server does not serve yet reads as null. Never substitute sample values.
 *
 * Reports carry no numeric score: numeric publication stays withheld until
 * the AC-SVAL gates pass, so this module has no score, grade or gap fields.
 */
import {
  acquisition,
  AcquisitionError,
  parseAllowance,
  parseSubmissionLibraryPage,
  record,
  type Allowance,
  type LibrarySubmission,
} from "../acquisition-client";
import { ReportContractError } from "../report-contract";

/** Mirrors the Calls list status families (`callTone` in calls-library). */
export type CallSummary = {
  total: number;
  processing: number;
  completed: number;
  needsAttention: number;
};

export type ActivityDay = {
  /** Calendar date in Asia/Kolkata, YYYY-MM-DD. */
  date: string;
  analysed: number;
  analysedSeconds: number;
};

export type CallActivity = {
  timezone: "Asia/Kolkata";
  /** Exactly 30 days, oldest first; the last entry is today. */
  days: ActivityDay[];
  analysedLast30Days: number;
  analysedPrevious30Days: number;
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;

function count(value: unknown, code: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0)
    throw new ReportContractError(code);
  return value as number;
}

function exactKeys(
  item: Record<string, unknown>,
  keys: readonly string[],
  code: string,
): void {
  const actual = Object.keys(item);
  if (
    actual.length !== keys.length ||
    actual.some((key) => !keys.includes(key))
  )
    throw new ReportContractError(code);
}

export function parseCallSummary(value: unknown): CallSummary {
  const item = record(value);
  const code = "dashboard_summary";
  exactKeys(
    item,
    ["total", "processing", "completed", "needs_attention"],
    code,
  );
  const summary = {
    total: count(item.total, code),
    processing: count(item.processing, code),
    completed: count(item.completed, code),
    needsAttention: count(item.needs_attention, code),
  };
  if (
    summary.processing + summary.completed + summary.needsAttention >
    summary.total
  )
    throw new ReportContractError(code);
  return summary;
}

export function parseCallActivity(value: unknown): CallActivity {
  const item = record(value);
  const code = "dashboard_activity";
  exactKeys(
    item,
    ["timezone", "days", "analysed_last_30_days", "analysed_previous_30_days"],
    code,
  );
  if (
    item.timezone !== "Asia/Kolkata" ||
    !Array.isArray(item.days) ||
    item.days.length !== 30
  )
    throw new ReportContractError(code);
  const days = item.days.map((entry: unknown): ActivityDay => {
    const day = record(entry);
    exactKeys(day, ["date", "analysed", "analysed_seconds"], code);
    if (typeof day.date !== "string" || !DATE.test(day.date))
      throw new ReportContractError(code);
    return {
      date: day.date,
      analysed: count(day.analysed, code),
      analysedSeconds: count(day.analysed_seconds, code),
    };
  });
  for (let index = 1; index < days.length; index += 1)
    if (days[index].date <= days[index - 1].date)
      throw new ReportContractError(code);
  const analysedLast30Days = count(item.analysed_last_30_days, code);
  if (analysedLast30Days !== days.reduce((sum, day) => sum + day.analysed, 0))
    throw new ReportContractError(code);
  return {
    timezone: "Asia/Kolkata",
    days,
    analysedLast30Days,
    analysedPrevious30Days: count(item.analysed_previous_30_days, code),
  };
}

/**
 * Until the new reads are deployed, `/activity` is 404 and
 * `/submissions/summary` is 422 (parsed as a call id). Both mean "not served
 * yet": the panel shows its not-available state instead of an error.
 */
async function servedRead<T>(
  path: string,
  parse: (value: unknown) => T,
  signal?: AbortSignal,
): Promise<T | null> {
  try {
    return parse(await acquisition(path, { signal }));
  } catch (error) {
    if (
      error instanceof AcquisitionError &&
      (error.status === 404 || error.status === 422)
    )
      return null;
    throw error;
  }
}

export const readCallSummary = (signal?: AbortSignal) =>
  servedRead("/submissions/summary", parseCallSummary, signal);

export const readCallActivity = (signal?: AbortSignal) =>
  servedRead("/activity", parseCallActivity, signal);

export async function readAllowance(signal?: AbortSignal): Promise<Allowance> {
  return parseAllowance(
    record(await acquisition("/session", { signal })).allowance,
  );
}

/** The newest calls from the Calls list's first page. */
export async function readRecentCalls(
  signal?: AbortSignal,
  limit = 5,
): Promise<LibrarySubmission[]> {
  const page = parseSubmissionLibraryPage(
    await acquisition("/submissions", { signal }),
  );
  return page.submissions.slice(0, limit);
}

export type Trend = { direction: "up" | "down" | "flat"; text: string };

/** Change in analysed calls against the previous 30 days; null with no history. */
export function analysedTrend(activity: CallActivity): Trend | null {
  const current = activity.analysedLast30Days;
  const previous = activity.analysedPrevious30Days;
  if (current === 0 && previous === 0) return null;
  const delta = current - previous;
  return {
    direction: delta > 0 ? "up" : delta < 0 ? "down" : "flat",
    text: `${delta > 0 ? "+" : ""}${delta} vs previous 30 days`,
  };
}

/** Same arithmetic as the shell's MinutesMeter, so the two never disagree. */
export function minutesLeft(allowance: Allowance): {
  value: string;
  subtext: string;
} {
  if (allowance.unlimited)
    return { value: "Unlimited", subtext: "Analysis time" };
  const left = Math.floor(allowance.available_seconds / 60);
  const total = Math.floor(allowance.allowance_seconds / 60);
  return { value: `${left} min`, subtext: `left of ${total} min` };
}

/** Saved calls that are not ready, in progress or flagged. */
export function otherSavedCalls(summary: CallSummary): number {
  return (
    summary.total -
    summary.processing -
    summary.completed -
    summary.needsAttention
  );
}

/** True when the account has nothing to show yet (drives the empty state). */
export function isEmptyAccount(
  summary: CallSummary | null,
  activity: CallActivity | null,
  recent: LibrarySubmission[] | null,
): boolean {
  return (
    (summary === null || summary.total === 0) &&
    (activity === null ||
      (activity.analysedLast30Days === 0 &&
        activity.analysedPrevious30Days === 0)) &&
    (recent === null || recent.length === 0)
  );
}
