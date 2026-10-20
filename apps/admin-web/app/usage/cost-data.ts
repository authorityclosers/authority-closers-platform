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
  CDF: "Call data · fast",
  CDD: "Call data · deep",
  AR: "AI replies",
  QF: "Quote facts",
};

/** How rupees were made from the dollars providers bill (one rate, and since when). */
export type Fx = { currency: string; usdToInr: number; setOn: string | null };

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
  /** Model steps: input and output tokens. Transcription: audio minutes. */
  inputTokens: number;
  outputTokens: number;
  audioMinutes: number;
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

/** One provider step of a call (Per call drill-down, 19 Oct 2026). */
export type CallStep = {
  stage: string;
  provider: string | null;
  model: string | null;
  status: string;
  attempts: number;
  inputTokens: number;
  outputTokens: number;
  audioMinutes: number | null;
  elapsedMs: number | null;
  rupees: number | null;
  at: string;
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
  tokens: number;
  models: string[];
  /** How many of its steps ended in each status. */
  statuses: Record<string, number>;
  /** Each step, when the Per call tab asked for them. */
  steps: CallStep[];
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
  /** lifetime, monthly or daily: what the cap and the spend refer to. */
  period: string;
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

/** What the organisation and feature filters offer, and what is chosen. */
export type Choices = {
  companies: {
    id: string;
    name: string;
    environment: string;
    rupees: number;
  }[];
  stages: { stage: string; label: string }[];
};

export type Metrics = {
  days: number;
  fx: Fx;
  filters: { company: string | null; stage: string | null };
  choices: Choices;
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
  calls: {
    rows: CallRow[];
    total: number;
    sort: string;
    /** Calls that cost nothing, listed apart. */
    zeroRows: CallRow[];
    zeroTotal: number;
  };
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

function callRow(item: unknown): CallRow {
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
    tokens: n(row.tokens),
    models: read.strings(row.models),
    statuses: numbers(row.statuses),
    steps: read.array(row.steps).map((value) => {
      const step = read.object(value);
      return {
        stage: s(step.stage),
        provider: os(step.provider),
        model: os(step.model),
        status: s(step.status),
        attempts: n(step.attempts),
        inputTokens: n(step.input_tokens),
        outputTokens: n(step.output_tokens),
        audioMinutes: on(step.audio_minutes),
        elapsedMs: on(step.elapsed_ms),
        rupees: on(step.rupees),
        at: s(step.at),
      };
    }),
  };
}

export function normalizeMetrics(raw: unknown): Metrics {
  const body = read.object(raw);
  const window = read.object(body.window);
  const overview = read.object(body.overview);
  const providers = read.object(body.providers);
  const calls = read.object(body.calls);
  const revenue = read.object(body.revenue);
  const money = read.object(body.money);
  const ideas = read.object(body.ideas);
  const fx = read.object(body.fx);
  const filters = read.object(body.filters);
  const choices = read.object(body.choices);
  return {
    days: n(window.days, 30),
    filters: { company: os(filters.company), stage: os(filters.stage) },
    choices: {
      companies: read.array(choices.companies).map((item) => {
        const row = read.object(item);
        return {
          id: s(row.id),
          name: s(row.name, "Unknown"),
          environment: s(row.environment),
          rupees: n(row.rupees),
        };
      }),
      stages: read.array(choices.stages).map((item) => {
        const row = read.object(item);
        const stage = s(row.stage);
        return { stage, label: s(row.label, STAGE_LABEL[stage] ?? stage) };
      }),
    },
    fx: {
      currency: s(fx.currency, "USD"),
      usdToInr: n(fx.usd_to_inr, 100) || 100,
      setOn: os(fx.set_on),
    },
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
          inputTokens: n(row.input_tokens),
          outputTokens: n(row.output_tokens),
          audioMinutes: n(row.audio_minutes),
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
      sort: s(calls.sort, "newest"),
      rows: read.array(calls.rows).map(callRow),
      zeroTotal: n(calls.zero_total),
      zeroRows: read.array(calls.zero_rows).map(callRow),
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
          period: s(row.period) || "lifetime",
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

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

/** Dollars, as providers bill them, from rupees made at the one rate. */
export const usd = (rupees: number | null, fx: Fx) =>
  rupees === null ? "–" : USD.format(rupees / fx.usdToInr);

/** "$5.33 · ₹533": dollars first, rupees beside them. */
export const money = (rupees: number | null, fx: Fx) =>
  rupees === null ? "–" : `${usd(rupees, fx)} · ${inr(rupees)}`;

/** The rate in words: "₹100 per $1, set 19 Sep 2026". */
export function rateWords(fx: Fx): string {
  const day = fx.setOn ? Date.parse(`${fx.setOn}T00:00:00Z`) : Number.NaN;
  const when = Number.isNaN(day)
    ? ""
    : `, set ${new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(day)}`;
  return `₹${fx.usdToInr} per $1${when}`;
}

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
  current: {
    tab: string;
    days: string;
    env: string;
    tests: boolean;
  } & ChartView,
  change: Partial<
    { tab: string; days: string; env: string; tests: boolean } & ChartView
  >,
  extra: Record<string, string> = {},
): string {
  const next = { ...current, ...change };
  const params = new URLSearchParams();
  if (next.tab !== "overview") params.set("tab", next.tab);
  if (next.days !== "30") params.set("days", next.days);
  if (next.env !== "all") params.set("env", next.env);
  if (next.tests) params.set("tests", "1");
  // The Overview's chosen charts and compared pair stay with every filter change.
  if (next.charts) params.set("charts", next.charts);
  if (next.ca && next.cb) {
    params.set("ca", next.ca);
    params.set("cb", next.cb);
  }
  if (next.sort && next.sort !== "newest") params.set("sort", next.sort);
  if (next.org) params.set("org", next.org);
  if (next.feature) params.set("feature", next.feature);
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

/* ---------- Charts the owner picks and compares (owner, 19 Oct 2026) ---------- */

export type SeriesUnit = "inr" | "perMin" | "minutes" | "count" | "tokens";

/** One per-day line: a value per day of the window, oldest first. */
export type Series = {
  key: string;
  label: string;
  unit: SeriesUnit;
  days: string[];
  /** null where there is nothing to divide (cost per minute on a day with no audio). */
  values: (number | null)[];
};

/** Shown when the link names no charts: the two the page always had. */
export const DEFAULT_CHARTS = ["spend", "perMinute"];
export const MAX_CHARTS = 8;

const providerName = (provider: string) =>
  provider
    ? `${provider.charAt(0).toUpperCase()}${provider.slice(1)}`
    : "Unknown";

const slug = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

/** Every per-day series this read can draw, each with a stable key for the link. */
export function chartSeries(metrics: Metrics): Series[] {
  const daily = metrics.overview.daily;
  const days = daily.map((day) => day.day);
  const series: Series[] = [
    {
      key: "spend",
      label: "Spend per day",
      unit: "inr",
      days,
      values: daily.map((day) => day.spend),
    },
    {
      key: "perMinute",
      label: "Cost per audio minute",
      unit: "perMin",
      days,
      values: daily.map((day) => day.perMinute),
    },
    {
      key: "audio",
      label: "Audio minutes",
      unit: "minutes",
      days,
      values: daily.map((day) => day.audioMinutes),
    },
    {
      key: "calls",
      label: "Calls analysed",
      unit: "count",
      days,
      values: daily.map((day) => day.calls),
    },
  ];
  for (const name of ENVIRONMENTS)
    if (daily.some((day) => (day.byEnvironment[name] ?? 0) > 0))
      series.push({
        key: `env-${name}`,
        label: `${ENVIRONMENT_LABEL[name] ?? name} spend`,
        unit: "inr",
        days,
        values: daily.map((day) => day.byEnvironment[name] ?? 0),
      });
  const tokensByDay = new Map<string, number>();
  const spendByProvider = new Map<string, Map<string, number>>();
  for (const row of metrics.providers.daily) {
    tokensByDay.set(
      row.day,
      (tokensByDay.get(row.day) ?? 0) + row.inputTokens + row.outputTokens,
    );
    const byDay =
      spendByProvider.get(row.provider) ?? new Map<string, number>();
    byDay.set(row.day, (byDay.get(row.day) ?? 0) + row.rupees);
    spendByProvider.set(row.provider, byDay);
  }
  if (tokensByDay.size)
    series.push({
      key: "tokens",
      label: "AI tokens (in + out)",
      unit: "tokens",
      days,
      values: days.map((day) => tokensByDay.get(day) ?? 0),
    });
  for (const [provider, byDay] of [...spendByProvider].sort(([a], [b]) =>
    a.localeCompare(b),
  ))
    series.push({
      key: `provider-${slug(provider) || "unknown"}`,
      label: `${providerName(provider)} spend`,
      unit: "inr",
      days,
      values: days.map((day) => byDay.get(day) ?? 0),
    });
  return series;
}

/** The charts a link asks for, in its order, known keys only; "none" hides them all. */
export function chartsFrom(
  value: string | undefined,
  available: readonly string[],
): string[] {
  if (value === undefined || value === "")
    return DEFAULT_CHARTS.filter((key) => available.includes(key));
  if (value === "none") return [];
  return [...new Set(value.split(","))]
    .filter((key) => available.includes(key))
    .slice(0, MAX_CHARTS);
}

/** The link value after showing or hiding one chart. */
export function toggleChart(shown: readonly string[], key: string): string {
  const next = shown.includes(key)
    ? shown.filter((item) => item !== key)
    : [...shown, key].slice(0, MAX_CHARTS);
  return next.length ? next.join(",") : "none";
}

/** How closely two daily series move together (Pearson r), over days both have. */
export function correlation(
  a: readonly (number | null)[],
  b: readonly (number | null)[],
): number | null {
  const pairs: [number, number][] = [];
  a.forEach((x, index) => {
    const y = b[index];
    if (x !== null && y !== null && y !== undefined) pairs.push([x, y]);
  });
  if (pairs.length < 3) return null;
  const meanX = pairs.reduce((sum, [x]) => sum + x, 0) / pairs.length;
  const meanY = pairs.reduce((sum, [, y]) => sum + y, 0) / pairs.length;
  let xy = 0;
  let xx = 0;
  let yy = 0;
  for (const [x, y] of pairs) {
    xy += (x - meanX) * (y - meanY);
    xx += (x - meanX) ** 2;
    yy += (y - meanY) ** 2;
  }
  return xx && yy ? xy / Math.sqrt(xx * yy) : null;
}

/** "move together", "move opposite" or "aren't related", in plain words. */
export function together(r: number | null): string {
  if (r === null) return "too few days to tell";
  if (r >= 0.6) return "move together";
  if (r <= -0.6) return "move opposite";
  return "aren't clearly related";
}

/** A value in its own unit, for labels and tooltips. */
export function seriesValue(unit: SeriesUnit, value: number | null): string {
  if (unit === "inr") return inr(value);
  if (unit === "perMin") return perMin(value);
  if (value === null) return "–";
  if (unit === "minutes") return minutes(value);
  if (unit === "tokens") return tokens(value);
  return count(value);
}

/** The chart view kept in the link: shown charts and the compared pair. */
export type ChartView = {
  charts?: string;
  ca?: string;
  cb?: string;
  /** Per call order: newest unless chosen. */
  sort?: string;
  /** One organisation (its id) and one feature (a stage key), else everything. */
  org?: string;
  feature?: string;
};

const ORG = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

/** The organisation and feature filters from a link; anything else is ignored. */
export function scopeView(query: { org?: string; feature?: string }): {
  org?: string;
  feature?: string;
} {
  return {
    org: query.org && ORG.test(query.org) ? query.org : undefined,
    feature:
      query.feature && query.feature in STAGE_LABEL ? query.feature : undefined,
  };
}

/** The orders the Per call tab offers (the API accepts the same keys). */
export const CALL_SORTS = [
  { key: "newest", label: "Newest" },
  { key: "cost", label: "Most expensive" },
  { key: "per_minute", label: "Highest per minute" },
  { key: "audio", label: "Longest audio" },
  { key: "tokens", label: "Most tokens" },
];

/** Why a call cost nothing, from how its steps ended. */
export function zeroReason(statuses: Record<string, number>): string {
  const failed = statuses.dead_letter ?? 0;
  const done = statuses.succeeded ?? 0;
  const waiting = Object.entries(statuses)
    .filter(([status]) => status !== "dead_letter" && status !== "succeeded")
    .reduce((sum, [, value]) => sum + value, 0);
  if (failed)
    return `${count(failed)} ${failed === 1 ? "step" : "steps"} failed before any paid work`;
  if (waiting)
    return `${count(waiting)} ${waiting === 1 ? "step hasn't" : "steps haven't"} finished`;
  if (done) return "its finished steps have no price on the price sheet yet";
  return "no provider step ran";
}

const VIEW_VALUE = /^[a-zA-Z0-9_,-]{1,300}$/;

/** Only well-formed view values survive into links. */
export function chartView(query: {
  charts?: string;
  ca?: string;
  cb?: string;
  sort?: string;
}): ChartView {
  const keep = (value: string | undefined) =>
    value !== undefined && VIEW_VALUE.test(value) ? value : undefined;
  return {
    charts: keep(query.charts),
    ca: keep(query.ca),
    cb: keep(query.cb),
    sort: CALL_SORTS.some(
      (item) => item.key === query.sort && item.key !== "newest",
    )
      ? query.sort
      : undefined,
  };
}

/**
 * Revenue against cost in plain sentences, one per environment (owner, 20 Oct
 * 2026: "explained in plain words on the page"). Customers pay in rupees; the AI
 * cost is shown as billed (dollars) with rupees beside it.
 */
export function revenueWords(metrics: Metrics): string[] {
  const lines: string[] = [];
  for (const name of ENVIRONMENTS) {
    const value = metrics.revenue.totals[name];
    if (!value) continue;
    const label = ENVIRONMENT_LABEL[name] ?? name;
    const cost = money(value.cost, metrics.fx);
    if (name !== "production") {
      lines.push(
        `${label}: payments here are test money, but the AI it used cost ${cost}, real spend on the shared provider account.`,
      );
    } else if (value.revenue > 0) {
      const share = Math.round((value.margin / value.revenue) * 100);
      lines.push(
        `${label}: customers paid ${inr(value.revenue)} in the last ${metrics.days} days and the AI behind their calls cost ${cost}, so ${inr(value.margin)} is left after AI (${share}% of what came in).`,
      );
    } else {
      lines.push(
        `${label}: no money came in during the last ${metrics.days} days while the AI cost ${cost}, so for now the AI runs at a cost.`,
      );
    }
  }
  return lines;
}
