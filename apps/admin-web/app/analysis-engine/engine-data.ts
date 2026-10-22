/**
 * The analysis engine (adaptive analysis, phase 1; owner, 22 Oct 2026: "design an algorithm
 * that is most optimized ... very cheap"): GET /v1/admin/conversation/engine. The module
 * registry with its measured cost fits, what each module was expected to cost against what
 * it cost over a window, and every plan projected on that window's calls and on
 * production's measured 14-day mix. Pure.
 */
import { read } from "../lib/read";
import type { Tone } from "../ui/kit";

export type EngineStatus = "live" | "sealed" | "trial" | "beta" | "planned";

export type TokenPair = {
  actual: number;
  expected: number | null;
  ratio: number | null;
};

export type EngineModuleRow = {
  id: string;
  label: string | null;
  stage: string;
  model: string | null;
  modelled: boolean;
  calls: number;
  steps: number;
  unpricedSteps: number;
  audioMinutes: number;
  actualRupees: number;
  expectedRupees: number | null;
  ratio: number | null;
  drifting: boolean;
  tokensIn: TokenPair;
  tokensOut: TokenPair;
};

/** Gold agreement for one artifact of one setup (beta and research, never a score). */
export type QualityRow = {
  artifact: string;
  setup: string;
  module: string | null;
  nearest: string | null;
  agreement: number | null;
  low: number | null;
  high: number | null;
  evidence: string;
};

export type RegistryModule = {
  id: string;
  label: string;
  stage: string;
  models: string[];
  status: EngineStatus;
  evidence: string;
  note: string;
  examples: { minutes: number; rupees: number }[];
};

export type Projection = {
  calls: number;
  audioMinutes: number;
  rupees: number;
  perMinute: number | null;
};

export type EnginePlan = {
  id: string;
  label: string;
  status: EngineStatus;
  onDemand: string[];
  window: Projection | null;
  reference: Projection | null;
  /** The reference mix with the registry's uptake of on-demand modules. */
  referenceWithUptake: Projection | null;
};

export type AnalysisEngine = {
  environment: string;
  available: boolean;
  generatedAt: string | null;
  ageSeconds: number | null;
  days: number;
  drift: number;
  registry: {
    version: string;
    digest: string;
    planningFx: number;
    shortCallMinutes: number;
    uptake: number;
    modules: RegistryModule[];
    quality: QualityRow[];
  };
  window: {
    calls: number;
    analysed: number;
    short: number;
    audioMinutes: number;
    actualRupees: number;
    expectedRupees: number;
    actualPerMinute: number | null;
    expectedPerMinute: number | null;
  };
  modules: EngineModuleRow[];
  plans: EnginePlan[];
  problems: string[];
};

const STATUSES: readonly EngineStatus[] = [
  "live",
  "sealed",
  "trial",
  "beta",
  "planned",
];

const status = (value: unknown): EngineStatus =>
  STATUSES.find((item) => item === value) ?? "planned";

const projection = (raw: unknown): Projection | null => {
  if (typeof raw !== "object" || raw === null) return null;
  const row = read.object(raw);
  return {
    calls: read.number(row.calls),
    audioMinutes: read.number(row.audio_minutes),
    rupees: read.number(row.rupees),
    perMinute: read.optionalNumber(row.per_minute),
  };
};

const tokens = (
  raw: Record<string, unknown>,
  side: "in" | "out",
): TokenPair => ({
  actual: read.number(raw[`actual_${side}`]),
  expected: read.optionalNumber(raw[`expected_${side}`]),
  ratio: read.optionalNumber(raw[`ratio_${side}`]),
});

export function normalizeEngine(raw: unknown): AnalysisEngine {
  const body = read.object(raw);
  const registry = read.object(body.registry);
  const window = read.object(body.window);
  const windowPlans = new Map(
    read.array(body.plans).map((item) => {
      const row = read.object(item);
      return [read.string(row.id), projection(row.window)] as const;
    }),
  );
  return {
    environment: read.string(body.environment, "production"),
    available: read.boolean(body.available),
    generatedAt: read.optionalString(body.generated_at),
    ageSeconds: read.optionalNumber(body.age_seconds),
    days: read.number(body.days, 7),
    drift: read.number(body.drift, 0.25),
    registry: {
      version: read.string(registry.version, "–"),
      digest: read.string(registry.digest, "–"),
      planningFx: read.number(registry.planning_fx, 100),
      shortCallMinutes: read.number(registry.short_call_minutes, 1),
      uptake: read.number(registry.uptake, 0.1),
      quality: read.array(registry.quality).map((item) => {
        const row = read.object(item);
        return {
          artifact: read.string(row.artifact),
          setup: read.string(row.setup),
          module: read.optionalString(row.module),
          nearest: read.optionalString(row.nearest),
          agreement: read.optionalNumber(row.agreement),
          low: read.optionalNumber(row.low),
          high: read.optionalNumber(row.high),
          evidence: read.string(row.evidence),
        };
      }),
      modules: read.array(registry.modules).map((item) => {
        const row = read.object(item);
        return {
          id: read.string(row.id),
          label: read.string(row.label, read.string(row.id)),
          stage: read.string(row.stage),
          models: read
            .array(row.models)
            .filter((model): model is string => typeof model === "string"),
          status: status(row.status),
          evidence: read.string(row.evidence),
          note: read.string(row.note),
          examples: read.array(row.examples).map((example) => {
            const pair = read.object(example);
            return {
              minutes: read.number(pair.minutes),
              rupees: read.number(pair.rupees),
            };
          }),
        };
      }),
    },
    window: {
      calls: read.number(window.calls),
      analysed: read.number(window.analysed),
      short: read.number(window.short),
      audioMinutes: read.number(window.audio_minutes),
      actualRupees: read.number(window.actual_rupees),
      expectedRupees: read.number(window.expected_rupees),
      actualPerMinute: read.optionalNumber(window.actual_per_minute),
      expectedPerMinute: read.optionalNumber(window.expected_per_minute),
    },
    modules: read.array(body.modules).map((item) => {
      const row = read.object(item);
      const pair = read.object(row.tokens);
      return {
        id: read.string(row.id),
        label: read.optionalString(row.label),
        stage: read.string(row.stage),
        model: read.optionalString(row.model),
        modelled: read.boolean(row.modelled),
        calls: read.number(row.calls),
        steps: read.number(row.steps),
        unpricedSteps: read.number(row.unpriced_steps),
        audioMinutes: read.number(row.audio_minutes),
        actualRupees: read.number(row.actual_rupees),
        expectedRupees: read.optionalNumber(row.expected_rupees),
        ratio: read.optionalNumber(row.ratio),
        drifting: read.boolean(row.drifting),
        tokensIn: tokens(pair, "in"),
        tokensOut: tokens(pair, "out"),
      };
    }),
    plans: read.array(registry.plans).map((item) => {
      const row = read.object(item);
      const id = read.string(row.id);
      return {
        id,
        label: read.string(row.label, id),
        status: status(row.status),
        onDemand: read
          .array(row.on_demand)
          .filter((module): module is string => typeof module === "string"),
        window: windowPlans.get(id) ?? null,
        reference: projection(row.reference),
        referenceWithUptake: projection(row.reference_with_uptake),
      };
    }),
    problems: read
      .array(body.problems)
      .map((item) => read.string(read.object(item).problem))
      .filter(Boolean),
  };
}

/** Within the drift band is good; up to twice it, a look; beyond, a refit. */
export function ratioTone(ratio: number | null, drift: number): Tone {
  if (ratio === null) return "neutral";
  const off = Math.abs(ratio - 1);
  if (off <= drift) return "good";
  return off <= drift * 2 ? "warn" : "bad";
}

/** "×1.29", or "–" when nothing was expected. */
export const ratioWords = (ratio: number | null) =>
  ratio === null ? "–" : `×${ratio.toFixed(2)}`;

const RUPEES = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const rupeeWords = (value: number | null) =>
  value === null ? "–" : RUPEES.format(value);

/** "12.4k" tokens, "860", or "–". */
export function tokenWords(value: number | null): string {
  if (value === null) return "–";
  if (value < 1000) return String(Math.round(value));
  if (value < 1_000_000) return `${(value / 1000).toFixed(1)}k`;
  return `${(value / 1_000_000).toFixed(2)}M`;
}

/** "64% (49–77)", or "Not scored". */
export function agreementWords(row: QualityRow): string {
  if (row.agreement === null) return "Not scored";
  const share = (value: number) => Math.round(value * 100);
  return row.low === null || row.high === null
    ? `${share(row.agreement)}%`
    : `${share(row.agreement)}% (${share(row.low)}–${share(row.high)})`;
}

export const STATUS_WORDS: Record<EngineStatus, { label: string; tone: Tone }> =
  {
    live: { label: "Live", tone: "good" },
    sealed: { label: "Sealed, off", tone: "info" },
    trial: { label: "Trial", tone: "accent" },
    beta: { label: "Beta", tone: "accent" },
    planned: { label: "Planned", tone: "neutral" },
  };

export const ENVIRONMENTS = [
  { key: "production", label: "Production" },
  { key: "staging", label: "Staging" },
  { key: "development", label: "Dev" },
] as const;

export const WINDOWS = [
  { key: "7", label: "7 days" },
  { key: "1", label: "24 hours" },
  { key: "30", label: "30 days" },
] as const;

/** The page's query, bounded to what the API takes. */
export function engineQuery(env?: string, days?: string) {
  const environment =
    ENVIRONMENTS.find((item) => item.key === env)?.key ?? "production";
  const window = WINDOWS.find((item) => item.key === days)?.key ?? "7";
  return {
    environment,
    days: window,
    path: `/v1/admin/conversation/engine?env=${environment}&days=${window}`,
  };
}
