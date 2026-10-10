import type { LibrarySubmission } from "./acquisition-client";

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
  awaiting_upload: "Ready to analyse",
  ready: "Ready to analyse",
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

/** A call's date in lists: Today, Yesterday, 24 Sep, or 24 Sep 2025. */
export function callDate(createdAt: string, now = new Date()): string {
  const date = new Date(createdAt);
  // Intl throws on an invalid date; a list row must never take a screen down.
  if (Number.isNaN(date.getTime())) return "Date unknown";
  const day = (value: Date) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((day(now) - day(date)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
  }).format(date);
}
