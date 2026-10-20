/**
 * Admin's Providers hub (owner, 20 Oct 2026: "just search for a provider name ... and all
 * its models listed"): GET /v1/admin/providers/hub, and the search, filters and words the
 * hub uses. List prices in US dollars with rupees at the price sheet's one rate. Pure.
 */
import { read } from "../lib/read";

export type ProviderKind = "llm" | "speech" | "router";
export type PipelineState = "ready" | "planned" | "none";

export type HubProvider = {
  id: string;
  name: string;
  kind: ProviderKind;
  kindLabel: string;
  blurb: string;
  console: string | null;
  compatible: boolean;
  aliases: string[];
  pipeline: PipelineState;
  models: number;
  pipelineModels: number;
  cheapestInPerMillion: number | null;
};

export type HubModel = {
  id: string;
  name: string;
  context: number | null;
  inputs: string[];
  outputs: string[];
  audioIn: boolean;
  json: boolean;
  usdInPerMillion: number | null;
  usdOutPerMillion: number | null;
  usdPerAudioHour: number | null;
  free: boolean;
  /** Pipeline stages that can run on it here today. */
  stages: string[];
  source: string;
};

export type Hub = {
  providers: HubProvider[];
  selected: string | null;
  models: HubModel[];
  catalogue: {
    source: string;
    fetchedAt: string | null;
    problem: string | null;
  };
  usdToInr: number;
};

const KINDS: readonly ProviderKind[] = ["llm", "speech", "router"];
const STATES: readonly PipelineState[] = ["ready", "planned", "none"];

export function normalizeHub(raw: unknown): Hub {
  const body = read.object(raw);
  const catalogue = read.object(body.catalogue);
  const fx = read.object(body.fx);
  return {
    providers: read.array(body.providers).map((item) => {
      const row = read.object(item);
      const kind = read.string(row.kind);
      const pipeline = read.string(row.pipeline);
      return {
        id: read.string(row.id),
        name: read.string(row.name, read.string(row.id)),
        kind: (KINDS as readonly string[]).includes(kind)
          ? (kind as ProviderKind)
          : "llm",
        kindLabel: read.string(row.kind_label),
        blurb: read.string(row.blurb),
        console: read.optionalString(row.console),
        compatible: read.boolean(row.compatible),
        aliases: read.strings(row.aliases),
        pipeline: (STATES as readonly string[]).includes(pipeline)
          ? (pipeline as PipelineState)
          : "none",
        models: read.number(row.models),
        pipelineModels: read.number(row.pipeline_models),
        cheapestInPerMillion: read.optionalNumber(row.cheapest_in_per_million),
      };
    }),
    selected: read.optionalString(body.selected),
    models: read.array(body.models).map((item) => {
      const row = read.object(item);
      return {
        id: read.string(row.id),
        name: read.string(row.name, read.string(row.id)),
        context: read.optionalNumber(row.context),
        inputs: read.strings(row.inputs),
        outputs: read.strings(row.outputs),
        audioIn: read.boolean(row.audio_in),
        json: read.boolean(row.json),
        usdInPerMillion: read.optionalNumber(row.usd_in_per_million),
        usdOutPerMillion: read.optionalNumber(row.usd_out_per_million),
        usdPerAudioHour: read.optionalNumber(row.usd_per_audio_hour),
        free: read.boolean(row.free),
        stages: read.strings(row.stages),
        source: read.string(row.source),
      };
    }),
    catalogue: {
      source: read.string(catalogue.source, "OpenRouter"),
      fetchedAt: read.optionalString(catalogue.fetched_at),
      problem: read.optionalString(catalogue.problem),
    },
    usdToInr: read.number(fx.usd_to_inr, 100) || 100,
  };
}

/* ---------- search and filters ---------- */

export type KindFilter = "all" | ProviderKind;

/** Providers matching every word typed (name, id, kind or alias), in catalogue order. */
export function searchProviders(
  providers: readonly HubProvider[],
  query: string,
  kind: KindFilter = "all",
): HubProvider[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return providers.filter((provider) => {
    if (kind !== "all" && provider.kind !== kind) return false;
    const hay = [
      provider.id,
      provider.name,
      provider.kindLabel,
      ...provider.aliases,
    ]
      .join(" ")
      .toLowerCase();
    return words.every((word) => hay.includes(word));
  });
}

export type ModelFilter = {
  query: string;
  audio: boolean;
  json: boolean;
  runsHere: boolean;
  cheapest: boolean;
};

export const NO_MODEL_FILTER: ModelFilter = {
  query: "",
  audio: false,
  json: false,
  runsHere: false,
  cheapest: false,
};

/** A comparable price: per million input tokens, or an audio hour for speech. */
const priceKey = (model: HubModel) =>
  model.free
    ? 0
    : (model.usdInPerMillion ??
      model.usdPerAudioHour ??
      Number.POSITIVE_INFINITY);

export function filterModels(
  models: readonly HubModel[],
  filter: ModelFilter,
): HubModel[] {
  const words = filter.query.toLowerCase().split(/\s+/).filter(Boolean);
  const kept = models.filter(
    (model) =>
      (!filter.audio || model.audioIn) &&
      (!filter.json || model.json) &&
      (!filter.runsHere || model.stages.length > 0) &&
      words.every((word) =>
        `${model.id} ${model.name}`.toLowerCase().includes(word),
      ),
  );
  if (filter.cheapest)
    return [...kept].sort((a, b) => priceKey(a) - priceKey(b));
  // Pipeline models first, then the catalogue's order.
  return [...kept].sort(
    (a, b) => Number(b.stages.length > 0) - Number(a.stages.length > 0),
  );
}

/* ---------- words ---------- */

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 4,
});
const INR = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

/** "$0.75 in · $3.75 out per 1M tokens", "$0.22 an audio hour", "Free", or "–". */
export function priceWords(model: HubModel): string {
  if (model.free) return "Free";
  if (model.usdPerAudioHour !== null)
    return `${USD.format(model.usdPerAudioHour)} an audio hour`;
  const parts = [
    model.usdInPerMillion !== null
      ? `${USD.format(model.usdInPerMillion)} in`
      : null,
    model.usdOutPerMillion !== null
      ? `${USD.format(model.usdOutPerMillion)} out`
      : null,
  ].filter(Boolean);
  return parts.length ? `${parts.join(" · ")} per 1M tokens` : "–";
}

/** The same price in rupees at the sheet's rate, for the line under it. */
export function rupeeWords(model: HubModel, usdToInr: number): string {
  if (model.free) return "";
  if (model.usdPerAudioHour !== null)
    return `${INR.format(model.usdPerAudioHour * usdToInr)} an hour`;
  if (model.usdInPerMillion === null && model.usdOutPerMillion === null)
    return "";
  return [model.usdInPerMillion, model.usdOutPerMillion]
    .map((value) => (value === null ? "–" : INR.format(value * usdToInr)))
    .join(" · ");
}

/** "1M", "400K", "32K" tokens of context. */
export function contextWords(tokens: number | null): string {
  if (tokens === null) return "–";
  if (tokens >= 1_000_000) return `${+(tokens / 1_000_000).toFixed(1)}M`;
  return `${Math.round(tokens / 1000)}K`;
}

export const PIPELINE_WORDS: Record<PipelineState, string> = {
  ready: "Runs in the pipeline",
  planned: "Adapter planned",
  none: "Browse and compare",
};

/* ---------- who does each job ---------- */

/** A model a stage's setting offers, with its list prices in dollars per million tokens. */
export type ModelPrice = {
  model: string;
  label: string;
  usdIn: number;
  usdOut: number;
};

export function modelPrices(
  models: readonly {
    model: string;
    label: string;
    inputUsd: string;
    outputUsd: string;
  }[],
): ModelPrice[] {
  return models
    .map((item) => ({
      model: item.model,
      label: item.label,
      usdIn: Number.parseFloat(item.inputUsd),
      usdOut: Number.parseFloat(item.outputUsd),
    }))
    .filter(
      (item) => Number.isFinite(item.usdIn) && Number.isFinite(item.usdOut),
    );
}

/**
 * Rupees per audio minute if a stage ran on this model: the stage's tokens per transcribed
 * minute in the window, priced at the model's list prices. Null without audio to divide by.
 */
export function estimatePerMinute(
  stage: { inputTokens: number; outputTokens: number },
  audioMinutes: number,
  price: ModelPrice,
  usdToInr: number,
): number | null {
  if (audioMinutes <= 0) return null;
  const usd =
    ((stage.inputTokens / audioMinutes) * price.usdIn +
      (stage.outputTokens / audioMinutes) * price.usdOut) /
    1_000_000;
  return usd * usdToInr;
}

const PAISE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 3,
});

/** "₹0.084 a min", or "–". */
export const rupeesPerMinute = (value: number | null) =>
  value === null ? "–" : `${PAISE.format(value)} a min`;

/* ---------- health and spend here (slice 4) ---------- */

/** What fixes a failure: the provider's console, a new key, another model, an engineer, or
 * nothing (it retries by itself). */
export type HealthFix = "console" | "key" | "model" | "engineer" | "wait";
export type HealthState = "attention" | "ok" | "idle";

export type ProviderHealthRow = {
  id: string;
  state: HealthState;
  spend: {
    todayInr: number;
    monthInr: number;
    windowInr: number;
    requests: number;
  } | null;
  failures: {
    last7Days: number;
    last24Hours: number;
    latest: {
      at: string;
      status: number | null;
      featureLabel: string;
      words: string;
      fix: HealthFix;
    } | null;
  } | null;
};

export type ProviderHealth = {
  environment: string;
  windowDays: number;
  failureDays: number;
  month: { spentInr: number; capInr: number };
  providers: Record<string, ProviderHealthRow>;
};

const FIXES: readonly HealthFix[] = [
  "console",
  "key",
  "model",
  "engineer",
  "wait",
];
const HEALTH_STATES: readonly HealthState[] = ["attention", "ok", "idle"];

/** GET /v1/admin/providers/health: spend and failures per provider in this environment. */
export function normalizeHealth(raw: unknown): ProviderHealth {
  const body = read.object(raw);
  const month = read.object(body.month);
  const providers: Record<string, ProviderHealthRow> = {};
  for (const item of read.array(body.providers)) {
    const row = read.object(item);
    const id = read.string(row.id);
    if (!id) continue;
    const state = read.string(row.state);
    const spend = row.spend ? read.object(row.spend) : null;
    const failures = row.failures ? read.object(row.failures) : null;
    const latest = failures?.latest ? read.object(failures.latest) : null;
    const fix = latest ? read.string(latest.fix) : "";
    providers[id] = {
      id,
      state: (HEALTH_STATES as readonly string[]).includes(state)
        ? (state as HealthState)
        : "idle",
      spend: spend
        ? {
            todayInr: read.number(spend.today_inr),
            monthInr: read.number(spend.month_inr),
            windowInr: read.number(spend.window_inr),
            requests: read.number(spend.requests),
          }
        : null,
      failures: failures
        ? {
            last7Days: read.number(failures.last_7_days),
            last24Hours: read.number(failures.last_24_hours),
            latest: latest
              ? {
                  at: read.string(latest.at),
                  status: read.optionalNumber(latest.status),
                  featureLabel: read.string(
                    latest.feature_label,
                    read.string(latest.feature),
                  ),
                  words: read.string(latest.words),
                  fix: (FIXES as readonly string[]).includes(fix)
                    ? (fix as HealthFix)
                    : "engineer",
                }
              : null,
          }
        : null,
    };
  }
  return {
    environment: read.string(body.environment),
    windowDays: read.number(body.window_days, 30),
    failureDays: read.number(body.failure_days, 7),
    month: {
      spentInr: read.number(month.spent_inr),
      capInr: read.number(month.cap_inr),
    },
    providers,
  };
}

const SPEND = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** "₹1.50" (a list-price estimate, never a charge). */
export const spendWords = (rupees: number) => SPEND.format(rupees);

/** "just now", "40 min ago", "3 h ago", "2 days ago". */
export function agoWords(at: string, now: Date = new Date()): string {
  const minutes = Math.round((now.getTime() - new Date(at).getTime()) / 60_000);
  if (!Number.isFinite(minutes)) return "";
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/** "3 failures in the last 7 days, 1 in the last 24 hours", or "No failures in …". */
export function failureCountWords(
  row: ProviderHealthRow,
  days: number,
): string {
  const failures = row.failures;
  if (!failures || failures.last7Days === 0)
    return `No failures in the last ${days} days.`;
  const total = `${failures.last7Days} ${failures.last7Days === 1 ? "failure" : "failures"} in the last ${days} days`;
  return failures.last24Hours
    ? `${total}, ${failures.last24Hours} in the last 24 hours.`
    : `${total}, none in the last 24 hours.`;
}

/* ---------- keys here (slice 2) ---------- */

/** A connection test: the server's plain words and what fixes a failure. */
export type KeyTest = {
  at: string;
  ok: boolean | null;
  status: number | null;
  models: number | null;
  words: string;
  fix: string | null;
};

export type ProviderKeyRow = {
  provider: string;
  hint: string;
  addedAt: string;
  freeCheck: boolean;
  tested: KeyTest | null;
};

export type ProviderKeys = {
  environment: string;
  /** False until this environment's API holds its platform key (Root). */
  sealing: boolean;
  freshMinutes: number;
  keys: Record<string, ProviderKeyRow>;
};

/** GET /v1/admin/providers/keys: the last four characters and the last test, never a key. */
export function normalizeKeys(raw: unknown): ProviderKeys {
  const body = read.object(raw);
  const keys: Record<string, ProviderKeyRow> = {};
  for (const item of read.array(body.keys)) {
    const row = read.object(item);
    const provider = read.string(row.provider);
    if (!provider) continue;
    const tested = row.tested ? read.object(row.tested) : null;
    keys[provider] = {
      provider,
      hint: read.string(row.hint),
      addedAt: read.string(row.added_at),
      freeCheck: read.boolean(row.free_check),
      tested: tested
        ? {
            at: read.string(tested.at),
            ok: typeof tested.ok === "boolean" ? tested.ok : null,
            status: read.optionalNumber(tested.status),
            models: read.optionalNumber(tested.models),
            words: read.string(tested.words),
            fix: read.optionalString(tested.fix),
          }
        : null,
    };
  }
  return {
    environment: read.string(body.environment),
    sealing: read.boolean(body.sealing),
    freshMinutes: read.number(body.fresh_minutes, 10),
    keys,
  };
}

/** A test in plain words: the server's own, or a fallback for an older answer. */
export function keyTestWords(test: KeyTest): string {
  if (test.words) return test.words;
  if (test.ok === null)
    return "This provider has no free check: its first real use is the test.";
  if (test.ok)
    return test.models === null
      ? "The key works."
      : `The key works: ${test.models} ${test.models === 1 ? "model" : "models"} listed.`;
  return test.status
    ? `The last test failed (HTTP ${test.status}). Test again to see what fixes it.`
    : "The last test could not reach the provider.";
}
