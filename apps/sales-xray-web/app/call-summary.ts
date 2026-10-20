import type { LibrarySubmission, RowSummary } from "./acquisition-client";
import type { CallInsight, OutcomeKind } from "./calls-insights";

/** The outcomes the Report names (calls-insights.ts OUTCOME_LABEL's keys). */
export const SUMMARY_OUTCOMES: readonly OutcomeKind[] = [
  "follow_up",
  "closed",
  "future_date",
  "unclear",
  "no_sale",
  "disqualified",
];

/**
 * A row's insight from the list's summary (include_summary=true): the
 * Report's assessment, what to fix first and next, strengths, missed chances
 * and outcome, with no read of the row's Report. What only the full Report
 * or the call record carries (length, speakers, moments) stays empty.
 */
export function insightFromSummary(summary: RowSummary): CallInsight {
  const outcome = SUMMARY_OUTCOMES.find((kind) => kind === summary.outcome);
  return {
    durationMs: null,
    speakers: [],
    questions: null,
    callType: null,
    signals: { commitments: null, business: null, concerns: null },
    assessment: summary.assessment,
    fixFirst: summary.fixFirst,
    nextFocus: summary.nextFocus,
    strengths: summary.strengths,
    missed: summary.missed,
    outcome: outcome ?? null,
    moments: [],
  };
}

/** Rows whose list entry has no summary key (an older server) read their own. */
export function needsOwnRead(submission: LibrarySubmission): boolean {
  return submission.hasReport && submission.summary === undefined;
}
