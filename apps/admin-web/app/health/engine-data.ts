/**
 * Analysis health's call data engine and Review 2.0 parts (admin revamp
 * Phase 4): the `engine` and `review` sections of GET
 * /v1/admin/conversation/health. Every field has a default. Pure.
 */
import { read } from "../lib/read";

export type Times = { count: number; p50: number | null; p90: number | null };

export type EngineOutcomes = {
  runs: number;
  succeeded: number;
  failed: number;
  skipped: number;
  successShare: number | null;
  time: Times;
  costInr: number;
  costPerRunInr: number | null;
};

export type EnginePipeline = EngineOutcomes & {
  pipeline: string;
  version: string | null;
  calls: number;
  running: number;
  quiet: number;
  reasons: { state: string; code: string; runs: number }[];
  models: { provider: string | null; model: string; runs: number }[];
};

export type EngineVersion = EngineOutcomes & {
  pipeline: string;
  version: string;
  lastAt: string | null;
};

export type EngineHealth = {
  pipelines: EnginePipeline[];
  versions: EngineVersion[];
  daily: {
    day: string;
    counts: Record<string, { succeeded: number; failed: number }>;
  }[];
  quiet: {
    runId: string;
    recordingId: string;
    pipeline: string;
    startedAt: string | null;
  }[];
  truncated: boolean;
};

export type ReviewQuestion = {
  key: string;
  label: string;
  kind: string;
  answers: number;
  counts: Record<string, number> | null;
  average: number | null;
};

export type ReviewShare = { answers: number; rightShare: number | null };

export type ReviewPipelineHealth = {
  key: string;
  title: string;
  answers: number;
  calls: number;
  items: number;
  reviewers: number;
  right: number;
  wrong: number;
  rightShare: number | null;
  questions: ReviewQuestion[];
  types: (ReviewShare & { type: string; right: number; wrong: number })[];
  agreement: { compared: number; agreed: number; share: number | null };
};

export type ReviewHealth = {
  answers: number;
  calls: number;
  pipelines: ReviewPipelineHealth[];
  engineVersions: (ReviewShare & { pipeline: string; version: string })[];
  reviewers: { name: string; answers: number; calls: number }[];
  truncated: boolean;
};

const times = (raw: unknown): Times => {
  const body = read.object(raw);
  return {
    count: read.number(body.count),
    p50: read.optionalNumber(body.p50_ms),
    p90: read.optionalNumber(body.p90_ms),
  };
};

const outcomes = (row: Record<string, unknown>): EngineOutcomes => ({
  runs: read.number(row.runs),
  succeeded: read.number(row.succeeded),
  failed: read.number(row.failed),
  skipped: read.number(row.skipped),
  successShare: read.optionalNumber(row.success_share),
  time: times(row.time),
  costInr: read.number(row.cost_inr),
  costPerRunInr: read.optionalNumber(row.cost_per_run_inr),
});

export function normalizeEngineHealth(raw: unknown): EngineHealth {
  const body = read.object(raw);
  return {
    pipelines: read.array(body.pipelines).map((item) => {
      const row = read.object(item);
      return {
        ...outcomes(row),
        pipeline: read.string(row.pipeline, "?"),
        version: read.optionalString(row.version),
        calls: read.number(row.calls),
        running: read.number(row.running),
        quiet: read.number(row.quiet),
        reasons: read.array(row.reasons).map((entry) => {
          const reason = read.object(entry);
          return {
            state: read.string(reason.state, "failed"),
            code: read.string(reason.code, "not_recorded"),
            runs: read.number(reason.runs),
          };
        }),
        models: read.array(row.models).map((entry) => {
          const model = read.object(entry);
          return {
            provider: read.optionalString(model.provider),
            model: read.string(model.model, "?"),
            runs: read.number(model.runs),
          };
        }),
      };
    }),
    versions: read.array(body.versions).map((item) => {
      const row = read.object(item);
      return {
        ...outcomes(row),
        pipeline: read.string(row.pipeline, "?"),
        version: read.string(row.version, "?"),
        lastAt: read.optionalString(row.last_at),
      };
    }),
    daily: read.array(body.daily).map((item) => {
      const { day, ...rest } = read.object(item);
      return {
        day: read.string(day),
        counts: Object.fromEntries(
          Object.entries(rest).map(([pipeline, value]) => {
            const counts = read.object(value);
            return [
              pipeline,
              {
                succeeded: read.number(counts.succeeded),
                failed: read.number(counts.failed),
              },
            ];
          }),
        ),
      };
    }),
    quiet: read.array(body.quiet).map((item) => {
      const row = read.object(item);
      return {
        runId: read.string(row.run_id),
        recordingId: read.string(row.recording_id),
        pipeline: read.string(row.pipeline, "?"),
        startedAt: read.optionalString(row.started_at),
      };
    }),
    truncated: read.boolean(body.truncated),
  };
}

const share = (row: Record<string, unknown>): ReviewShare => ({
  answers: read.number(row.answers),
  rightShare: read.optionalNumber(row.right_share),
});

export function normalizeReviewHealth(raw: unknown): ReviewHealth {
  const body = read.object(raw);
  return {
    answers: read.number(body.answers),
    calls: read.number(body.calls),
    pipelines: read.array(body.pipelines).map((item) => {
      const row = read.object(item);
      const agreement = read.object(row.agreement);
      return {
        key: read.string(row.key, "?"),
        title: read.string(row.title, read.string(row.key, "Review")),
        answers: read.number(row.answers),
        calls: read.number(row.calls),
        items: read.number(row.items),
        reviewers: read.number(row.reviewers),
        right: read.number(row.right),
        wrong: read.number(row.wrong),
        rightShare: read.optionalNumber(row.right_share),
        questions: read.array(row.questions).map((entry) => {
          const question = read.object(entry);
          const counts = read.object(question.counts);
          return {
            key: read.string(question.key, "?"),
            label: read.string(question.label, read.string(question.key, "?")),
            kind: read.string(question.kind, "verdict"),
            answers: read.number(question.answers),
            counts:
              question.counts === undefined || question.counts === null
                ? null
                : Object.fromEntries(
                    Object.entries(counts).map(([key, value]) => [
                      key,
                      read.number(value),
                    ]),
                  ),
            average: read.optionalNumber(question.average),
          };
        }),
        types: read.array(row.types).map((entry) => {
          const type = read.object(entry);
          return {
            ...share(type),
            type: read.string(type.type, "unknown"),
            right: read.number(type.right),
            wrong: read.number(type.wrong),
          };
        }),
        agreement: {
          compared: read.number(agreement.compared),
          agreed: read.number(agreement.agreed),
          share: read.optionalNumber(agreement.share),
        },
      };
    }),
    engineVersions: read.array(body.engine_versions).map((item) => {
      const row = read.object(item);
      return {
        ...share(row),
        pipeline: read.string(row.pipeline, "?"),
        version: read.string(row.version, "?"),
      };
    }),
    reviewers: read.array(body.reviewers).map((item) => {
      const row = read.object(item);
      return {
        name: read.string(row.name, "Reviewer"),
        answers: read.number(row.answers),
        calls: read.number(row.calls),
      };
    }),
    truncated: read.boolean(body.truncated),
  };
}

export const PIPELINE_LABEL: Record<string, string> = {
  fast: "Fast",
  deep: "Deep",
};

/** 0.756 → "76%"; null → "–". */
export const percent = (value: number | null) =>
  value === null ? "–" : `${Math.round(value * 100)}%`;

/** ₹0.42; null → "–". */
export const inr = (value: number | null) =>
  value === null
    ? "–"
    : new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 2,
      }).format(value);

/** "buyer.objection" → "Buyer objection"; "coaching.better" → "Coaching better". */
export function typeLabel(key: string): string {
  const words = key.replace(/[._-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}
