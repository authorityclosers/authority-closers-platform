/** Normalizer for GET /v1/admin/conversation/health; every field has a default. */
import { read } from "../lib/read";

export const JOB_STATUSES = [
  "queued",
  "leased",
  "retry_wait",
  "held",
  "succeeded",
  "dead_letter",
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];
export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  queued: "Queued",
  leased: "Working",
  retry_wait: "Retrying",
  held: "Held",
  succeeded: "Done",
  dead_letter: "Failed",
};
export const STAGE_LABEL: Record<string, string> = {
  C1: "Audio check",
  C2: "Transcript",
  C4: "Facts",
  C5: "Report",
};

export type Duration = {
  count: number;
  p50: number | null;
  p90: number | null;
  max: number | null;
};
export type FailedJob = {
  jobId: string;
  stage: string;
  recordingId: string | null;
  attempts: number;
  code: string;
  failedAt: string | null;
  retryable: boolean;
};
export type Health = {
  days: number;
  truncated: boolean;
  total: number;
  byStatus: Record<JobStatus, number>;
  byStage: { stage: string; counts: Record<JobStatus, number> }[];
  retried: number;
  failed: FailedJob[];
  held: {
    jobId: string;
    stage: string;
    recordingId: string | null;
    reason: string;
    heldAt: string | null;
  }[];
  stuck: {
    id: string;
    recordingId: string | null;
    state: string;
    since: string | null;
    kind: "plan" | "run";
  }[];
  stuckTruncated: boolean;
  runs: Duration;
  providerByStage: { stage: string; duration: Duration }[];
  cost: {
    paise: number;
    minutes: number;
    paisePerMinute: number | null;
    unpriced: number;
  };
  daily: { day: string; analysed: number; failed: number }[];
};

const counts = (raw: unknown) => {
  const body = read.object(raw);
  return Object.fromEntries(
    JOB_STATUSES.map((status) => [status, read.number(body[status])]),
  ) as Record<JobStatus, number>;
};
const duration = (raw: unknown): Duration => {
  const body = read.object(raw);
  return {
    count: read.number(body.count),
    p50: read.optionalNumber(body.p50_ms),
    p90: read.optionalNumber(body.p90_ms),
    max: read.optionalNumber(body.max_ms),
  };
};

export function normalizeHealth(raw: unknown): Health {
  const body = read.object(raw);
  const window = read.object(body.window);
  const jobs = read.object(body.jobs);
  const stuck = read.object(body.stuck);
  const durations = read.object(body.durations);
  const cost = read.object(body.cost);
  return {
    days: read.number(window.days, 7),
    truncated: read.boolean(window.truncated),
    total: read.number(jobs.total),
    byStatus: counts(jobs.by_status),
    byStage: Object.entries(read.object(jobs.by_stage)).map(
      ([stage, value]) => ({ stage, counts: counts(value) }),
    ),
    retried: Object.values(read.object(jobs.retried)).reduce<number>(
      (sum, value) => sum + read.number(value),
      0,
    ),
    failed: read.array(body.failed).map((item) => {
      const row = read.object(item);
      return {
        jobId: read.string(row.job_id),
        stage: read.string(row.stage, "?"),
        recordingId: read.optionalString(row.recording_id),
        attempts: read.number(row.attempts),
        code: read.string(row.code, "not_recorded"),
        failedAt: read.optionalString(row.failed_at),
        retryable: read.boolean(row.retryable),
      };
    }),
    held: read.array(body.held).map((item) => {
      const row = read.object(item);
      return {
        jobId: read.string(row.job_id),
        stage: read.string(row.stage, "?"),
        recordingId: read.optionalString(row.recording_id),
        reason: read.string(row.reason, "held"),
        heldAt: read.optionalString(row.held_at),
      };
    }),
    stuck: [
      ...read.array(stuck.plans).map((item) => {
        const row = read.object(item);
        return {
          id: read.string(row.plan_id),
          recordingId: read.optionalString(row.recording_id),
          state: read.string(row.state, "active"),
          since: read.optionalString(row.budget_expires_at),
          kind: "plan" as const,
        };
      }),
      ...read.array(stuck.unfinished_runs).map((item) => {
        const row = read.object(item);
        return {
          id: read.string(row.run_id),
          recordingId: read.optionalString(row.recording_id),
          state: read.string(row.state, "running"),
          since: null,
          kind: "run" as const,
        };
      }),
    ],
    stuckTruncated: read.boolean(stuck.truncated),
    runs: duration(durations.runs),
    providerByStage: Object.entries(
      read.object(durations.provider_by_stage),
    ).map(([stage, value]) => ({
      stage,
      duration: duration(value),
    })),
    cost: {
      paise: read.number(cost.estimated_paise),
      minutes: read.number(cost.priced_minutes),
      paisePerMinute: read.optionalNumber(cost.paise_per_minute),
      unpriced: read.number(cost.unpriced_jobs),
    },
    daily: read.array(body.daily).map((item) => {
      const row = read.object(item);
      return {
        day: read.string(row.day),
        analysed: read.number(row.analysed),
        failed: read.number(row.failed),
      };
    }),
  };
}

export const rupees = (paise: number | null) =>
  paise === null
    ? "–"
    : new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 2,
      }).format(paise / 100);

/** 950 ms, 42 s, 3 min 5 s. */
export function span(ms: number | null): string {
  if (ms === null) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}
