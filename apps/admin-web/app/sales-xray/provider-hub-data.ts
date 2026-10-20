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
