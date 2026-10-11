import {
  parseAllowance,
  parseSubmissionLibraryPage,
  type Allowance,
  type LibrarySubmission,
} from "../acquisition-client";
import type { ReadState } from "./dashboard-body";
import {
  parseCallActivity,
  parseCallSummary,
  type CallActivity,
  type CallSummary,
} from "./dashboard-data";

/** The dashboard's reads, exactly as the browser makes them. */
export const DASHBOARD_PATHS = {
  summary: "/v1/conversation/acquisition/submissions/summary",
  activity: "/v1/conversation/acquisition/activity",
  allowance: "/v1/conversation/acquisition/session",
  recent: "/v1/conversation/acquisition/submissions?include_owners=true",
} as const;

export type ServerAnswer = { status: number; body: unknown } | null;
export type ServerDashboard = Readonly<
  Partial<Record<keyof typeof DASHBOARD_PATHS, ServerAnswer>>
>;

type Seed = {
  summary?: ReadState<CallSummary | null>;
  activity?: ReadState<CallActivity | null>;
  allowance?: ReadState<Allowance>;
  recent?: ReadState<LibrarySubmission[]>;
};

/**
 * A server answer as the panel's read state, with the browser read's own
 * rules: a success is parsed (a bad shape is an error), 403 says this
 * workspace has no Sales Xray, and for the two newer reads 404/422 mean
 * "not served yet". No answer (or a sign-in problem) leaves the panel to the
 * browser.
 */
function seedOf<T>(
  answer: ServerAnswer | undefined,
  parse: (body: unknown) => T,
  notServed?: T,
): ReadState<T> | undefined {
  if (!answer || answer.status === 401) return undefined;
  if (answer.status >= 200 && answer.status < 300)
    try {
      return { status: "ready", value: parse(answer.body) };
    } catch {
      return { status: "error", forbidden: false };
    }
  if (
    notServed !== undefined &&
    (answer.status === 404 || answer.status === 422)
  )
    return { status: "ready", value: notServed };
  return { status: "error", forbidden: answer.status === 403 };
}

export function seededDashboard(initial: ServerDashboard | null): Seed {
  if (!initial) return {};
  return {
    summary: seedOf<CallSummary | null>(
      initial.summary,
      parseCallSummary,
      null,
    ),
    activity: seedOf<CallActivity | null>(
      initial.activity,
      parseCallActivity,
      null,
    ),
    allowance: seedOf(initial.allowance, (body) =>
      parseAllowance(
        body && typeof body === "object" && "allowance" in body
          ? (body as { allowance: unknown }).allowance
          : null,
      ),
    ),
    recent: seedOf(initial.recent, (body) =>
      parseSubmissionLibraryPage(body).submissions.slice(0, 5),
    ),
  };
}
