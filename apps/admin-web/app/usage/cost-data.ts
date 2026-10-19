/**
 * Normalizer for GET /v1/admin/conversation/metrics: what Sales X-Ray costs
 * and earns in every environment. Money is a list-price estimate from the
 * repo price sheet (tokens and audio minutes x approved rates), never an
 * invoice, and it never becomes payment or progress state.
 */
import { read } from "../lib/read";

export const ENVIRONMENTS = ["production", "staging", "development"] as const;
export type Environment = (typeof ENVIRONMENTS)[number];

export const ENVIRONMENT_LABEL: Record<string, string> = {
  production: "Production",
  staging: "Staging",
  development: "Dev",
};

export const STAGE_LABEL: Record<string, string> = {
  C1: "Audio check",
  C2: "Transcription",
  C4: "Facts",
  C5: "Report",
  PR: "Pointer review",
};

export const KIND_LABEL: Record<string, string> = {
  real: "Real",
  canary: "Canary",
  qa: "QA test",
  synthetic: "Synthetic",
};

const env = (value: unknown) => read.string(value, "development");

export type Source = {
  environment: string;
  generatedAt: string | null;
  stale: boolean;
  migration: string | null;
  calls: number;
  steps: number;
  copies: number;
  synthetic: number;
};

export type EnvRow = {
  environment: string;
  today: number;
  month: number;
  window: number;
  tests: number;
  testRuns: number;
  calls: number;
  reports: number;
  audioMinutes: number;
  perMinute: number | null;
  billedMinutes: number;
  reportP50: number | null;
};

export type Day = {
  day: string;
  byEnvironment: Record<string, number>;
  spend: number;
  audioMinutes: number;
  perMinute: number | null;
  calls: number;
};

export type StageRow = {
  stage: string;
  label: string;
  rupees: number;
  share: number;
  perMinute: number | null;
};

export type ModelRow = {
  provider: string;
  model: string;
  stages: string[];
  calls: number;
  steps: number;
  failed: number;
  inputTokens: number;
  outputTokens: number;
  audioMinutes: number;
  rupees: number;
  share: number;
};

export type ProviderDay = {
  day: string;
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  audioMinutes: number;
  rupees: number;
};

export type StageCost = {
  inputTokens: number;
  outputTokens: number;
  rupees: number;
  runs: number;
  failed: number;
};

export type CallRow = {
  environment: string;
  id: string;
  company: string;
  companyKind: string;
  kind: string;
  at: string;
  audioMinutes: number;
  stages: Record<string, StageCost>;
  rupees: number;
  perMinute: number | null;
  billedMinutes: number;
  report: boolean;
  reportMs: number | null;
  version: string;
  revenue: number | null;
  margin: number | null;
};

export type RevenueRow = {
  environment: string;
  company: string;
  companyKind: string;
  plan: {
    name: string | null;
    interval: string | null;
    rupees: number;
    includedMinutes: number;
    mode: string | null;
  } | null;
  revenue: number;
  testRevenue: number;
  cost: number;
  margin: number;
  calls: number;
  billedMinutes: number;
  costPerBilledMinute: number | null;
};

export type Pipeline = {
  id: string;
  label: string;
  prompt: string | null;
  facts: string | null;
  reportModel: string | null;
  transcriptionModel: string | null;
  settings: string | null;
  environments: string[];
  firstSeen: string;
  lastSeen: string;
  calls: number;
  testRuns: number;
  steps: number;
  failureRate: number | null;
  retryRate: number | null;
  rupees: number;
  perMinute: number | null;
  audioMinutes: number;
  stageMs: Record<string, number | null>;
  reportP50: number | null;
  gold: {
    reviewed: number;
    agree: number;
    partly: number;
    disagree: number;
    agreement: number | null;
  };
};

export type MoneyEnv = {
  environment: string;
  cap: number | null;
  open: number;
  openRupees: number;
  capShare: number | null;
  /** Spent and held against the cap, the share of the cap, calls waiting for budget. */
  usedRupees: number;
  usedShare: number | null;
  waitingCalls: number;
  settled: number;
  settledRupees: number;
  byReason: { ref: string; label: string; n: number; rupees: number }[];
  byKind: Record<string, number>;
  recent: { day: string; n: number; heldRupees: number; canary: number }[];
};

export type TopCompany = {
  environment: string;
  company: string;
  companyKind: string;
  rupees: number;
  calls: number;
  perCall: number;
};

export type TopCall = {
  environment: string;
  id: string;
  company: string;
  kind: string;
  audioMinutes: number | null;
  rupees: number;
};

export type Metrics = {
  days: number;
  environment: string;
  tests: boolean;
  here: string | null;
  available: string[];
  problems: { environment: string; problem: string }[];
  sources: Source[];
  overview: {
    spendToday: number;
    spendMonth: number;
    spendWindow: number;
    testsWindow: number;
    testRuns: number;
    calls: number;
    reports: number;
    audioMinutes: number;
    perMinute: number | null;
    billedMinutes: number;
    reportP50: number | null;
    reportP90: number | null;
    unpricedSteps: number;
    environments: EnvRow[];
    daily: Day[];
    byStage: StageRow[];
  };
  providers: { models: ModelRow[]; daily: ProviderDay[] };
  calls: { rows: CallRow[]; total: number };
  revenue: {
    rows: RevenueRow[];
    totals: Record<string, { revenue: number; cost: number; margin: number }>;
    paymentsRecorded: number;
    plansRecorded: number;
  };
  pipelines: Pipeline[];
  money: { environments: MoneyEnv[]; finding: string };
  ideas: {
    topCompanies: TopCompany[];
    topCalls: TopCall[];
    perReport: number | null;
    failedRupees: number;
    repeatTranscriptions: number;
    repeatRupees: number;
    noReportCalls: number;
    noReportRupees: number;
    testsShare: number;
    missing: string[];
  };
};

const n = read.number;
const on = read.optionalNumber;
const s = read.string;
const os = read.optionalString;
const numbers = (value: unknown): Record<string, number> =>
  Object.fromEntries(
    Object.entries(read.object(value)).map(([key, item]) => [key, n(item)]),
  );

export function normalizeMetrics(raw: unknown): Metrics {
  const body = read.object(raw);
  const window = read.object(body.window);
  const overview = read.object(body.overview);
  const providers = read.object(body.providers);
  const calls = read.object(body.calls);
  const revenue = read.object(body.revenue);
  const money = read.object(body.money);
  const ideas = read.object(body.ideas);
  return {
    days: n(window.days, 30),
    environment: s(body.environment, "all"),
    tests: read.boolean(body.tests),
    here: os(body.here),
    available: read.strings(body.available),
    problems: read.array(body.problems).map((item) => {
      const row = read.object(item);
      return { environment: s(row.environment), problem: s(row.problem) };
    }),
    sources: read.array(body.sources).map((item) => {
      const row = read.object(item);
      return {
        environment: env(row.environment),
        generatedAt: os(row.generated_at),
        stale: read.boolean(row.stale, true),
        migration: os(row.migration),
        calls: n(row.calls),
        steps: n(row.steps),
        copies: n(row.copies_counted_upstream),
        synthetic: n(row.synthetic_calls),
      };
    }),
    overview: {
      spendToday: n(overview.spend_today),
      spendMonth: n(overview.spend_month),
      spendWindow: n(overview.spend_window),
      testsWindow: n(overview.tests_window),
      testRuns: n(overview.test_runs),
      calls: n(overview.calls),
      reports: n(overview.reports),
      audioMinutes: n(overview.audio_minutes),
      perMinute: on(overview.per_minute),
      billedMinutes: n(overview.billed_minutes),
      reportP50: on(overview.report_p50_ms),
      reportP90: on(overview.report_p90_ms),
      unpricedSteps: n(overview.unpriced_steps),
      environments: read.array(overview.environments).map((item) => {
        const row = read.object(item);
        return {
          environment: env(row.environment),
          today: n(row.today),
          month: n(row.month),
          window: n(row.window),
          tests: n(row.tests),
          testRuns: n(row.test_runs),
          calls: n(row.calls),
          reports: n(row.reports),
          audioMinutes: n(row.audio_minutes),
          perMinute: on(row.per_minute),
          billedMinutes: n(row.billed_minutes),
          reportP50: on(row.report_p50_ms),
        };
      }),
      daily: read.array(overview.daily).map((item) => {
        const row = read.object(item);
        return {
          day: s(row.day),
          byEnvironment: numbers(row.by_environment),
          spend: n(row.spend),
          audioMinutes: n(row.audio_minutes),
          perMinute: on(row.per_minute),
          calls: n(row.calls),
        };
      }),
      byStage: read.array(overview.by_stage).map((item) => {
        const row = read.object(item);
        const stage = s(row.stage);
        return {
          stage,
          label: s(row.label, STAGE_LABEL[stage] ?? stage),
          rupees: n(row.rupees),
          share: n(row.share),
          perMinute: on(row.per_minute),
        };
      }),
    },
    providers: {
      models: read.array(providers.models).map((item) => {
        const row = read.object(item);
        return {
          provider: s(row.provider, "?"),
          model: s(row.model, "?"),
          stages: read.strings(row.stages),
          calls: n(row.calls),
          steps: n(row.steps),
          failed: n(row.failed),
          inputTokens: n(row.input_tokens),
          outputTokens: n(row.output_tokens),
          audioMinutes: n(row.audio_minutes),
          rupees: n(row.rupees),
          share: n(row.share),
        };
      }),
      daily: read.array(providers.daily).map((item) => {
        const row = read.object(item);
        return {
          day: s(row.day),
          provider: s(row.provider, "?"),
          model: s(row.model, "?"),
          inputTokens: n(row.input_tokens),
          outputTokens: n(row.output_tokens),
          audioMinutes: n(row.audio_minutes),
          rupees: n(row.rupees),
        };
      }),
    },
    calls: {
      total: n(calls.total),
      rows: read.array(calls.rows).map((item) => {
        const row = read.object(item);
        return {
          environment: env(row.environment),
          id: s(row.id),
          company: s(row.company, "Unknown"),
          companyKind: s(row.company_kind, "other"),
          kind: s(row.kind, "real"),
          at: s(row.at),
          audioMinutes: n(row.audio_minutes),
          stages: Object.fromEntries(
            Object.entries(read.object(row.stages)).map(([stage, value]) => {
              const cost = read.object(value);
              return [
                stage,
                {
                  inputTokens: n(cost.input_tokens),
                  outputTokens: n(cost.output_tokens),
                  rupees: n(cost.rupees),
                  runs: n(cost.runs),
                  failed: n(cost.failed),
                },
              ];
            }),
          ),
          rupees: n(row.rupees),
          perMinute: on(row.per_minute),
          billedMinutes: n(row.billed_minutes),
          report: read.boolean(row.report),
          reportMs: on(row.report_ms),
          version: s(row.version),
          revenue: on(row.revenue),
          margin: on(row.margin),
        };
      }),
    },
    revenue: {
      paymentsRecorded: n(revenue.payments_recorded),
      plansRecorded: n(revenue.plans_recorded),
      totals: Object.fromEntries(
        Object.entries(read.object(revenue.totals)).map(([key, value]) => {
          const row = read.object(value);
          return [
            key,
            {
              revenue: n(row.revenue),
              cost: n(row.cost),
              margin: n(row.margin),
            },
          ];
        }),
      ),
      rows: read.array(revenue.rows).map((item) => {
        const row = read.object(item);
        const plan =
          row.plan && typeof row.plan === "object"
            ? read.object(row.plan)
            : null;
        return {
          environment: env(row.environment),
          company: s(row.company, "Unknown"),
          companyKind: s(row.company_kind, "other"),
          plan: plan
            ? {
                name: os(plan.name),
                interval: os(plan.interval),
                rupees: n(plan.rupees),
                includedMinutes: n(plan.included_minutes),
                mode: os(plan.mode),
              }
            : null,
          revenue: n(row.revenue),
          testRevenue: n(row.test_revenue),
          cost: n(row.cost),
          margin: n(row.margin),
          calls: n(row.calls),
          billedMinutes: n(row.billed_minutes),
          costPerBilledMinute: on(row.cost_per_billed_minute),
        };
      }),
    },
    pipelines: read.array(body.pipelines).map((item) => {
      const row = read.object(item);
      const gold = read.object(row.gold);
      return {
        id: s(row.id),
        label: s(row.label, "Unknown version"),
        prompt: os(row.prompt),
        facts: os(row.facts),
        reportModel: os(row.report_model),
        transcriptionModel: os(row.transcription_model),
        settings: os(row.settings),
        environments: read.strings(row.environments),
        firstSeen: s(row.first_seen),
        lastSeen: s(row.last_seen),
        calls: n(row.calls),
        testRuns: n(row.test_runs),
        steps: n(row.steps),
        failureRate: on(row.failure_rate),
        retryRate: on(row.retry_rate),
        rupees: n(row.rupees),
        perMinute: on(row.per_minute),
        audioMinutes: n(row.audio_minutes),
        stageMs: Object.fromEntries(
          Object.entries(read.object(row.stage_ms)).map(([key, value]) => [
            key,
            on(value),
          ]),
        ),
        reportP50: on(row.report_p50_ms),
        gold: {
          reviewed: n(gold.reviewed),
          agree: n(gold.agree),
          partly: n(gold.partly),
          disagree: n(gold.disagree),
          agreement: on(gold.agreement),
        },
      };
    }),
    money: {
      finding: s(money.finding),
      environments: read.array(money.environments).map((item) => {
        const row = read.object(item);
        return {
          environment: env(row.environment),
          cap: on(row.cap),
          open: n(row.open),
          openRupees: n(row.open_rupees),
          capShare: on(row.cap_share),
          usedRupees: n(row.used_rupees),
          usedShare: on(row.used_share),
          waitingCalls: n(row.waiting_calls),
          settled: n(row.settled),
          settledRupees: n(row.settled_rupees),
          byReason: read.array(row.by_reason).map((value) => {
            const reason = read.object(value);
            return {
              ref: s(reason.ref),
              label: s(reason.label, s(reason.ref)),
              n: n(reason.n),
              rupees: n(reason.rupees),
            };
          }),
          byKind: numbers(row.by_kind),
          recent: read.array(row.recent).map((value) => {
            const day = read.object(value);
            return {
              day: s(day.day),
              n: n(day.n),
              heldRupees: n(day.held_paise),
              canary: n(day.canary),
            };
          }),
        };
      }),
    },
    ideas: {
      topCompanies: read.array(ideas.top_companies).map((item) => {
        const row = read.object(item);
        return {
          environment: env(row.environment),
          company: s(row.company, "Unknown"),
          companyKind: s(row.company_kind, "other"),
          rupees: n(row.rupees),
          calls: n(row.calls),
          perCall: n(row.per_call),
        };
      }),
      topCalls: read.array(ideas.top_calls).map((item) => {
        const row = read.object(item);
        return {
          environment: env(row.environment),
          id: s(row.id),
          company: s(row.company, "Unknown"),
          kind: s(row.kind, "real"),
          audioMinutes: on(row.audio_minutes),
          rupees: n(row.rupees),
        };
      }),
      perReport: on(ideas.per_report),
      failedRupees: n(ideas.failed_rupees),
      repeatTranscriptions: n(ideas.repeat_transcriptions),
      repeatRupees: n(ideas.repeat_rupees),
      noReportCalls: n(ideas.no_report_calls),
      noReportRupees: n(ideas.no_report_rupees),
      testsShare: n(ideas.tests_share),
      missing: read.strings(ideas.missing),
    },
  };
}

/* ---------- formatting ---------- */

const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});
const INR_ROUND = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const COUNT = new Intl.NumberFormat("en-IN");
const COMPACT = new Intl.NumberFormat("en-IN", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Rupees: paise shown under ₹1,000, whole rupees above. */
export const inr = (value: number | null) =>
  value === null
    ? "–"
    : Math.abs(value) >= 1000
      ? INR_ROUND.format(value)
      : INR.format(value);

/** Rupees per audio minute, always with paise. */
export const perMin = (value: number | null) =>
  value === null ? "–" : `${INR.format(value)}/min`;

export const count = (value: number) => COUNT.format(value);
export const tokens = (value: number) =>
  value >= 100_000 ? COMPACT.format(value) : COUNT.format(value);
export const minutes = (value: number) =>
  `${COUNT.format(Math.round(value * 10) / 10)} min`;
export const pct = (share: number | null) =>
  share === null ? "–" : `${Math.round(share * 1000) / 10}%`;

export function seconds(ms: number | null): string {
  if (ms === null) return "–";
  const total = Math.round(ms / 1000);
  if (total < 90) return `${total} s`;
  const m = Math.floor(total / 60);
  const rest = total % 60;
  return rest ? `${m} min ${rest} s` : `${m} min`;
}

/** "18 Oct, 14:02" in India time; days and months are India time throughout. */
const STAMP = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Kolkata",
});
export const stamp = (iso: string | null) => {
  if (!iso) return "never";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "unknown" : STAMP.format(date);
};

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});
/** A YYYY-MM-DD day key (already an India date) as "18 Oct". */
export const dayLabel = (day: string) => {
  const date = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? day : DAY.format(date);
};

/** Query string for the cost views, keeping the other filters. */
export function costQuery(
  current: { tab: string; days: string; env: string; tests: boolean },
  change: Partial<{ tab: string; days: string; env: string; tests: boolean }>,
  extra: Record<string, string> = {},
): string {
  const next = { ...current, ...change };
  const params = new URLSearchParams();
  if (next.tab !== "overview") params.set("tab", next.tab);
  if (next.days !== "30") params.set("days", next.days);
  if (next.env !== "all") params.set("env", next.env);
  if (next.tests) params.set("tests", "1");
  for (const [key, value] of Object.entries(extra)) params.set(key, value);
  const text = params.toString();
  return text ? `/usage?${text}` : "/usage";
}

/** The two pipeline versions to compare: chosen ids, else the two newest. */
export function comparePair(
  pipelines: Pipeline[],
  a: string | undefined,
  b: string | undefined,
): [Pipeline | null, Pipeline | null] {
  const find = (id: string | undefined) =>
    pipelines.find((item) => item.id === id) ?? null;
  const first = find(a) ?? pipelines[0] ?? null;
  const second =
    find(b) ?? pipelines.find((item) => item.id !== first?.id) ?? null;
  return [first, second];
}
