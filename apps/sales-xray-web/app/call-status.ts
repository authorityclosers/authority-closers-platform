import type { LibrarySubmission } from "./acquisition-client";
import { dayKey, daysBetween, type DisplayDates } from "./display-dates";

/** Status families from the saved state only; no inferred outcome. */
export type CallTone = "ready" | "active" | "attention" | "idle";

export function callTone(submission: LibrarySubmission): CallTone {
  if (submission.hasReport) return "ready";
  if (
    ["uploading", "queued", "processing", "running", "active"].includes(
      submission.state,
    )
  )
    return "active";
  if (["held", "uncertain", "failed", "blocked"].includes(submission.state))
    return "attention";
  return "idle";
}

const STATE_COPY: Record<string, string> = {
  // A saved call whose analysis never started (16 Oct: imported calls).
  awaiting_upload: "Not analysed yet",
  ready: "Not analysed yet",
  uploading: "Preparing call",
  queued: "Queued for analysis",
  processing: "Analysis in progress",
  running: "Analysis in progress",
  active: "Analysis in progress",
  completed: "Analysis complete",
  held: "Analysis paused",
  uncertain: "Needs attention",
  failed: "Needs attention",
  blocked: "Needs attention",
  cancelled: "Cancelled",
};

export function submissionState(submission: LibrarySubmission) {
  return submission.hasReport
    ? "Report ready"
    : (STATE_COPY[submission.state] ?? "Saved call");
}

/**
 * A call's date in lists: Today, Yesterday, 24 Sep, or 24 Sep 2025. In the
 * runtime's own language and zone, or as `dates` says (display-clock.tsx).
 */
export function callDate(
  createdAt: string,
  now = new Date(),
  dates?: DisplayDates,
): string {
  const date = new Date(createdAt);
  // Intl throws on an invalid date; a list row must never take a screen down.
  const day = dayKey(date, dates?.timeZone);
  const today = dates?.today ?? dayKey(now, dates?.timeZone);
  if (day === null || today === null) return "Date unknown";
  const days = daysBetween(day, today);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return new Intl.DateTimeFormat(dates?.locale, {
    day: "numeric",
    month: "short",
    year: day.slice(0, 4) === today.slice(0, 4) ? undefined : "numeric",
    timeZone: dates?.timeZone,
  }).format(date);
}
