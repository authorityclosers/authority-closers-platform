/**
 * Gold review (owner, 19 Oct): a reviewer checks the AI's Report line by line on
 * the phone, and every save is a human label in the gold set. The AI's values
 * stay the AI draft; the server picks them, never this page.
 */

const API = "/v1/sales-xray/review";

export type Verdict = "agree" | "partly" | "disagree";
export type AiStatus =
  | "excellent"
  | "good"
  | "average"
  | "needs_improvement"
  | "not_observed"
  | "not_applicable"
  | "insufficient_evidence";
export type Reason =
  | "wrong_evidence"
  | "missed_evidence"
  | "too_harsh"
  | "too_generous"
  | "wrong_status"
  | "misheard"
  | "wrong_speaker"
  | "not_relevant"
  | "feedback_unclear"
  | "other";
export type SkipReason =
  | "audio_unclear"
  | "not_sure"
  | "not_applicable"
  | "come_back";

export const STATUS_WORDS: Record<AiStatus, string> = {
  excellent: "Excellent",
  good: "Good",
  average: "Average",
  needs_improvement: "Needs work",
  not_observed: "Not seen",
  not_applicable: "Not relevant",
  insufficient_evidence: "Too little to judge",
};
export const STATUSES = Object.keys(STATUS_WORDS) as AiStatus[];

export const REASON_WORDS: Record<Reason, string> = {
  wrong_evidence: "Wrong lines quoted",
  missed_evidence: "Missed a moment",
  too_harsh: "Too harsh",
  too_generous: "Too generous",
  wrong_status: "Wrong status",
  misheard: "Misheard words",
  wrong_speaker: "Wrong speaker",
  not_relevant: "Doesn't apply here",
  feedback_unclear: "Advice unclear",
  other: "Other",
};
export const REASONS = Object.keys(REASON_WORDS) as Reason[];

export const SKIP_WORDS: Record<SkipReason, string> = {
  audio_unclear: "Audio unclear",
  not_sure: "Not sure",
  not_applicable: "Doesn't apply",
  come_back: "Come back later",
};

export type Badge = {
  reviewer: boolean;
  metrics: boolean;
  waiting: number;
  newest_at: string | null;
};

export type QueueItem = {
  assignment_id: string;
  recording_id: string;
  assigned_at: string;
  recorded_at: string;
  expires_at: string;
  handled: number;
  total: number;
  state: "new" | "in_progress" | "done";
};
export type Queue = {
  items: QueueItem[];
  calls_left: number;
  lines_left: number;
};

export type Evidence = {
  quote?: string;
  start_ms?: number;
  end_ms?: number;
  segment_id?: string;
};
export type Pointer = {
  id: string;
  number: number;
  label: string;
  status?: string;
  score?: number | null;
  evidence?: Evidence[];
  what_happened?: string;
  why_it_matters?: string;
  how_to_improve?: string[];
  training_topic?: string;
};
export type Line = { target: string; label: string; ai: unknown };
export type SavedValue = {
  verdict: Verdict | null;
  score: number | null;
  opinion: string;
  status?: AiStatus;
  reasons?: Reason[];
  skip?: SkipReason;
  seconds?: number;
};
export type SavedRow = {
  id: string;
  target: string;
  value: SavedValue | null;
  supersedes_id: string | null;
  created_at: string;
};
export type Segment = {
  id: string;
  text: string;
  speaker_id: string;
  start_ms: number;
  end_ms?: number;
};
export type Workspace = {
  review_id: string;
  review_status: string;
  lines: Line[];
  saved: SavedRow[];
  audio_source_url: string;
  transcript: { segments: Segment[] };
  context?: {
    recorded_at: string;
    duration_ms: number | null;
    summary: string | null;
    verdict: string | null;
  };
};

export type PointerFigures = {
  target: string;
  label: string;
  labels: number;
  agree: number;
  partly: number;
  disagree: number;
  agreement: number | null;
  wrong_rate: number | null;
  mean_score_gap: number | null;
  status_changed: number;
  ai_status: Record<string, number>;
  top_reasons: Reason[];
};
export type Summary = {
  labels: number;
  skipped: number;
  today: number;
  calls_done: number;
  calls_started: number;
  median_seconds: number | null;
  agreement: number | null;
  verdicts: Record<Verdict, number>;
};
export type Metrics = {
  scope: "reviewer" | "owner";
  as_of: string;
  me:
    | (Summary & {
        calls_left: number;
        lines_left: number;
        daily: { date: string; labels: number }[];
      })
    | null;
  team: Summary & { reviewers: number; calls_covered: number };
  pointers: PointerFigures[];
  wrong_most: string[];
  ai_status_coverage: Record<string, number>;
  between_reviewers: {
    calls: number;
    lines: number;
    differ: number;
    agreement: number | null;
    by_line: { target: string; label: string; lines: number; differ: number }[];
  };
  reviewers?: (Summary & { email: string | null })[];
  truncated: boolean;
};

export class ReviewError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const FALLBACK: Record<number, string> = {
  401: "Sign in to review.",
  403: "Review is open to gold reviewers.",
  404: "This review isn't available any more.",
  409: "This line changed elsewhere. Reload to see the latest.",
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      ...init,
      headers: { accept: "application/json", ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ReviewError("Sales Xray isn't answering. Try again.", 0);
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new ReviewError(
      detail ?? FALLBACK[response.status] ?? "Something went wrong. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export async function readBadge(): Promise<Badge | null> {
  try {
    const badge = await request<Partial<Badge>>("/badge");
    return typeof badge.reviewer === "boolean" &&
      typeof badge.waiting === "number"
      ? {
          reviewer: badge.reviewer,
          metrics: badge.metrics === true,
          waiting: badge.waiting,
          newest_at: badge.newest_at ?? null,
        }
      : null;
  } catch {
    return null;
  }
}

export const readQueue = (signal?: AbortSignal) =>
  request<Queue>("/queue", { signal });

export const readMetrics = (signal?: AbortSignal) =>
  request<Metrics>("/metrics", { signal });

export function readWorkspace(id: string, signal?: AbortSignal) {
  return request<Workspace>(`/assignments/${encodeURIComponent(id)}`, {
    signal,
  });
}

export type LineSave = {
  verdict?: Verdict | null;
  score?: number | null;
  opinion?: string;
  status?: AiStatus | null;
  reasons?: Reason[];
  skip?: SkipReason | null;
  seconds?: number;
};

export function saveLine(
  id: string,
  reviewId: string,
  target: string,
  value: LineSave,
  supersedes: string | null,
  key: string,
) {
  const body: Record<string, unknown> = {
    review_id: reviewId,
    target,
    supersedes_id: supersedes,
  };
  for (const [name, item] of Object.entries(value))
    if (item !== null && item !== undefined && item !== "") body[name] = item;
  return request<SavedRow>(`/assignments/${encodeURIComponent(id)}/lines`, {
    method: "POST",
    headers: { "content-type": "application/json", "idempotency-key": key },
    body: JSON.stringify(body),
  });
}

/** The app's Firebase client settings for review alerts; off for non-reviewers. */
export type ReviewPush = {
  enabled: boolean;
  project_id?: string | null;
  app_id?: string | null;
  api_key?: string | null;
  sender_id?: string | null;
};

export async function readReviewPush(): Promise<ReviewPush | null> {
  try {
    return await request<ReviewPush>("/push");
  } catch {
    return null;
  }
}

/** This phone gets my review alerts (its FCM address). */
export function registerReviewPhone(token: string, appVersion?: string) {
  return request<{ registered: boolean }>("/devices", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      token,
      platform: "android",
      app_version: appVersion,
    }),
  });
}

/** The newest save per line (a re-save supersedes the one before it). */
export function headsByTarget(saved: SavedRow[]): Map<string, SavedRow> {
  return new Map(saved.map((row) => [row.target, row]));
}

export function asPointer(ai: unknown): Pointer | null {
  if (!ai || typeof ai !== "object" || Array.isArray(ai)) return null;
  const value = ai as Partial<Pointer>;
  return typeof value.label === "string" && typeof value.id === "string"
    ? (value as Pointer)
    : null;
}

export function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function callName(recordedAt: string, durationMs?: number | null) {
  const date = new Date(recordedAt);
  const when = Number.isNaN(date.getTime())
    ? "Call"
    : date.toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
      });
  return durationMs ? `${when} · ${clock(durationMs)}` : when;
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "–"
    : `${Math.round(value * 100)}%`;
}
