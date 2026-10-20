/**
 * Where this environment's AI money goes (GET /v1/admin/ai-spend): spend per
 * day, feature and who started it, the caps every background job checks
 * before it calls a model, and alerts at 50, 80 and 100% of a cap (owner,
 * 20 Oct 2026). Rupees are list-price estimates for Admin only. Pure.
 */
import { read } from "../lib/read";

export const WINDOWS = ["7", "14", "30"] as const;

export type Cap = {
  target: string;
  label: string;
  window: string;
  spentInr: number;
  capInr: number;
  level: 50 | 80 | 100 | null;
  raiseToInr: number;
};

export type CapElsewhere = {
  feature: string;
  label: string;
  enabled: boolean;
  spentInr: number;
  capInr: number;
  window: string;
  page: string | null;
};

export type FeatureLine = {
  key: string;
  label: string;
  inr: number;
  requests: number;
  byTrigger: { trigger: string; label: string; inr: number }[];
};

export type DayLine = {
  day: string;
  inr: number;
  parts: { feature: string; inr: number }[];
};

export type ModelLine = {
  feature: string;
  provider: string;
  model: string;
  inr: number;
  requests: number;
  inputTokens: number;
  outputTokens: number;
  audioMinutes: number;
};

export type AiSpend = {
  environment: string;
  generatedAt: string | null;
  days: number;
  revision: number | null;
  config: Record<string, unknown>;
  backgroundEnabled: boolean;
  last24hInr: number;
  monthInr: number;
  totalInr: number;
  projectedMonthInr: number;
  caps: Cap[];
  elsewhere: CapElsewhere[];
  alerts: Cap[];
  features: FeatureLine[];
  byDay: DayLine[];
  models: ModelLine[];
  rules: string[];
  history: { revision: number; reason: string | null; at: string | null }[];
  unpriced: number;
};

const level = (value: unknown): Cap["level"] =>
  value === 50 || value === 80 || value === 100 ? value : null;

function cap(raw: unknown): Cap {
  const item = read.object(raw);
  return {
    target: read.string(item.target),
    label: read.string(item.label),
    window: read.string(item.window),
    spentInr: read.number(item.spent_inr),
    capInr: read.number(item.cap_inr),
    level: level(item.level),
    raiseToInr: read.number(item.raise_to_inr),
  };
}

export function normalizeAiSpend(raw: unknown): AiSpend {
  const body = read.object(raw);
  const settings = read.object(body.settings);
  const config = read.object(settings.config);
  const now = read.object(body.now);
  const window = read.object(body.window);
  const labels = new Map(
    read
      .array(body.features)
      .map((item) => read.object(item))
      .map((item) => [read.string(item.key), read.string(item.label)]),
  );
  const triggers = read.object(body.triggers);
  const series = read.array(body.series).map((item) => read.object(item));

  const featureMap = new Map<string, FeatureLine>();
  const dayMap = new Map<string, DayLine>();
  for (const item of series) {
    const feature = read.string(item.feature);
    const trigger = read.string(item.trigger);
    const inr = read.number(item.inr);
    const line = featureMap.get(feature) ?? {
      key: feature,
      label: labels.get(feature) || feature,
      inr: 0,
      requests: 0,
      byTrigger: [],
    };
    line.inr += inr;
    line.requests += read.number(item.requests);
    const part = line.byTrigger.find((entry) => entry.trigger === trigger);
    if (part) part.inr += inr;
    else
      line.byTrigger.push({
        trigger,
        label: read.string(triggers[trigger], trigger),
        inr,
      });
    featureMap.set(feature, line);
    const dayKey = read.string(item.day);
    const day = dayMap.get(dayKey) ?? { day: dayKey, inr: 0, parts: [] };
    day.inr += inr;
    const slice = day.parts.find((entry) => entry.feature === feature);
    if (slice) slice.inr += inr;
    else day.parts.push({ feature, inr });
    dayMap.set(dayKey, day);
  }
  const features = [...featureMap.values()]
    .map((line) => ({
      ...line,
      byTrigger: line.byTrigger.sort((a, b) => b.inr - a.inr),
    }))
    .sort((a, b) => b.inr - a.inr);

  return {
    environment: read.string(body.environment, "unknown"),
    generatedAt: read.optionalString(body.generated_at),
    days: read.number(body.days, 14),
    revision: read.optionalNumber(settings.revision),
    config,
    backgroundEnabled: read.boolean(config.background_enabled),
    last24hInr: read.number(now.last_24h_inr),
    monthInr: read.number(now.month_inr),
    totalInr: read.number(window.total_inr),
    projectedMonthInr: read.number(window.projected_month_inr),
    caps: read.array(body.caps).map(cap),
    elsewhere: read.array(body.elsewhere).map((raw) => {
      const item = read.object(raw);
      return {
        feature: read.string(item.feature),
        label: read.string(item.label),
        enabled: read.boolean(item.enabled),
        spentInr: read.number(item.spent_inr),
        capInr: read.number(item.cap_inr),
        window: read.string(item.window),
        page: read.optionalString(item.page),
      };
    }),
    alerts: read.array(body.alerts).map(cap),
    features,
    byDay: [...dayMap.values()].sort((a, b) => a.day.localeCompare(b.day)),
    models: read.array(body.models).map((raw) => {
      const item = read.object(raw);
      return {
        feature:
          labels.get(read.string(item.feature)) || read.string(item.feature),
        provider: read.string(item.provider),
        model: read.string(item.model),
        inr: read.number(item.inr),
        requests: read.number(item.requests),
        inputTokens: read.number(item.input_tokens),
        outputTokens: read.number(item.output_tokens),
        audioMinutes: read.number(item.audio_minutes),
      };
    }),
    rules: read.strings(body.rules),
    history: read.array(settings.history).map((raw) => {
      const item = read.object(raw);
      return {
        revision: read.number(item.revision),
        reason: read.optionalString(item.reason),
        at: read.optionalString(item.at),
      };
    }),
    unpriced: read.number(body.unpriced_requests),
  };
}

export const rupees = (value: number) =>
  `₹${value.toLocaleString("en-IN", {
    maximumFractionDigits: value >= 100 ? 0 : 2,
  })}`;

/** "24h" → "last 24 hours", "month" → "this month", "daily" → "today". */
export const windowLabel = (value: string) =>
  ({
    "24h": "last 24 hours",
    month: "this month",
    daily: "today",
    monthly: "this month",
    lifetime: "in all",
  })[value] ?? value;
