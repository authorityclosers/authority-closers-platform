/** Feedback answers: POST /v1/feedback and GET /v1/feedback/state (ac_platform/feedback/http.py). */

import { BugReportError } from "../bug-report/bug-report-client";
import type { ReportContext } from "../bug-report/device";

export type Moment =
  | "report_read"
  | "call_outcome"
  | "first_import"
  | "plan_purchase"
  | "chats_used"
  | "app_update"
  | "general";

export type Answer = Readonly<{
  commandId: string;
  moment: Moment;
  kind: "rating" | "dismissed" | "opt_out";
  rating?: 1 | 2 | 3;
  comment?: string;
  subject?: string;
  route: string;
  context: ReportContext;
}>;

export type FeedbackState = Readonly<{
  optedOut: readonly string[];
  last: Readonly<Record<string, string>>;
  askedToday: number;
  askedThisWeek: number;
  subjects: readonly string[];
}>;

export function feedbackRequest(answer: Answer): Record<string, unknown> {
  return {
    command_id: answer.commandId,
    moment: answer.moment,
    kind: answer.kind,
    rating: answer.rating ?? null,
    comment: answer.comment?.trim() || null,
    subject: answer.subject ?? null,
    route: answer.route,
    context: answer.context,
  };
}

async function call(
  path: string,
  init: RequestInit,
): Promise<Record<string, unknown>> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: { accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch {
    throw new BugReportError("No connection.", 0);
  }
  const body = (await response.json().catch(() => null)) as Record<
    string,
    unknown
  > | null;
  if (!response.ok) {
    throw new BugReportError(
      typeof body?.detail === "string" ? body.detail : "Not sent.",
      response.status,
    );
  }
  return body ?? {};
}

export async function postFeedbackRequest(
  request: Record<string, unknown>,
): Promise<{ feedbackId: string; bugId: string | null }> {
  const body = await call("/v1/feedback", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
  return {
    feedbackId: String(body.feedback_id ?? ""),
    bugId: typeof body.bug_id === "string" ? body.bug_id : null,
  };
}

export async function feedbackState(): Promise<FeedbackState> {
  const body = await call("/v1/feedback/state", { method: "GET" });
  const last =
    body.last && typeof body.last === "object"
      ? (body.last as Record<string, string>)
      : {};
  return {
    optedOut: Array.isArray(body.opted_out) ? (body.opted_out as string[]) : [],
    last,
    askedToday: Number(body.asked_today ?? 0),
    askedThisWeek: Number(body.asked_this_week ?? 0),
    subjects: Array.isArray(body.subjects) ? (body.subjects as string[]) : [],
  };
}
