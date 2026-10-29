/**
 * Admin → Product telemetry → Speed and journeys: the API's answer
 * (GET /v1/admin/telemetry/speed, telemetry/speed_view.py) read defensively,
 * and the words the page uses. Every number keeps its sample count; a 95th
 * percentile comes only from 20 samples or more.
 */
import type { Tone } from "../ui/kit";
import {
  msWords,
  normalizeTelemetry,
  type ProductTelemetry,
} from "./telemetry-data";

export const SPEED_WINDOWS = ["7d", "24h", "30d"] as const;
export type SpeedWindow = (typeof SPEED_WINDOWS)[number];
export const SPEED_APPS = ["all", "android", "web"] as const;
export type SpeedApp = (typeof SPEED_APPS)[number];

export type SpeedQuery = { window: SpeedWindow; app: SpeedApp; path: string };

export function speedQuery(params: {
  window?: string;
  app?: string;
}): SpeedQuery {
  const window = SPEED_WINDOWS.find((key) => key === params.window) ?? "7d";
  const app = SPEED_APPS.find((key) => key === params.app) ?? "all";
  const search = new URLSearchParams({ window });
  if (app !== "all") search.set("app", app);
  return { window, app, path: `/v1/admin/telemetry/speed?${search}` };
}

/** n samples, median, 75%, 95% (null under 20), and whether n is too few to tell. */
export type Stat = {
  n: number;
  p50: number | null;
  p75: number | null;
  p95: number | null;
  few: boolean;
};

export type FrameSummary = {
  sessions: number;
  people: number;
  frames: number;
  slowShare: number | null;
  frozenShare: number | null;
  p90: Stat;
};

export type ApiRelease = {
  release: string;
  firstAt: string;
  slowCalls: number;
  screenViews: number;
  per100Views: number | null;
  people: number;
};

export type ApiEndpoint = {
  endpoint: string;
  calls: number;
  people: number;
  wait: Stat;
  total: Stat;
  failed: number;
  refused: number;
  screens: string[];
};

export type StartRow = Stat & {
  app: string;
  start: string;
  what: "page" | "launch";
};

export type ModelCpu = {
  model: string;
  people: number;
  cpu: Stat;
  tier: string;
  start: Stat;
};

export type TapRow = {
  action: string;
  label: string;
  slowMs: number;
  all: Stat;
  byTier: Array<Stat & { tier: string; slowShare: number | null }>;
};

export type JourneyStep = {
  key: string;
  label: string;
  people: number;
  ofFirst: number | null;
  ofPrevious: number | null;
};

export type SpeedJourneys = {
  heartbeat?: ProductTelemetry["heartbeat"];
  environment: string;
  generatedAt: string;
  window: string;
  app: string | null;
  minP95: number;
  few: number;
  truncated: boolean;
  totals: { people: number; sessions: number; events: number };
  frames: {
    all: FrameSummary;
    byVersion: Array<FrameSummary & { version: string }>;
    byModel: Array<FrameSummary & { model: string }>;
  };
  apis: {
    calls: number;
    people: number;
    screenViews: number;
    per100Views: number | null;
    byRelease: ApiRelease[];
    endpoints: ApiEndpoint[];
  };
  load: {
    lcpByTier: Array<Stat & { tier: string; rating: string | null }>;
    starts: StartRow[];
    cpu: {
      tests: number;
      people: number;
      all: Stat;
      bands: { high: number; mid: number; low: number };
      byModel: ModelCpu[];
    };
  };
  taps: TapRow[];
  journey: { from: string; steps: JourneyStep[] };
};

type Json = Record<string, unknown>;
const object = (value: unknown): Json =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Json)
    : {};
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;
const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value > 0
    ? Math.round(value)
    : 0;
const maybe = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

function stat(value: unknown): Stat {
  const raw = object(value);
  const n = count(raw.n);
  return {
    n,
    p50: maybe(raw.p50),
    p75: maybe(raw.p75),
    // Never a 95th from fewer than 20, whatever the server says.
    p95: n >= 20 ? maybe(raw.p95) : null,
    few: raw.few === true || n < 5,
  };
}

function frames(value: unknown): FrameSummary {
  const raw = object(value);
  return {
    sessions: count(raw.sessions),
    people: count(raw.people),
    frames: count(raw.frames),
    slowShare: maybe(raw.slow_share),
    frozenShare: maybe(raw.frozen_share),
    p90: stat(raw.p90_ms),
  };
}

export function normalizeSpeed(raw: unknown): SpeedJourneys {
  const body = object(raw);
  const framesRaw = object(body.frames);
  const apis = object(body.apis);
  const load = object(body.load);
  const cpu = object(load.cpu);
  const bands = object(cpu.bands);
  const totals = object(body.totals);
  const journey = object(body.journey);
  return {
    heartbeat: normalizeTelemetry(body).heartbeat,
    environment: text(body.environment),
    generatedAt: text(body.generated_at),
    window: text(body.window, "7d"),
    app: typeof body.app === "string" ? body.app : null,
    minP95: count(body.min_p95) || 20,
    few: count(body.few) || 5,
    truncated: body.truncated === true,
    totals: {
      people: count(totals.people),
      sessions: count(totals.sessions),
      events: count(totals.events),
    },
    frames: {
      all: frames(framesRaw.all),
      byVersion: list(framesRaw.by_version).map((item) => ({
        version: text(object(item).version, "unknown"),
        ...frames(item),
      })),
      byModel: list(framesRaw.by_model).map((item) => ({
        model: text(object(item).model, "unknown"),
        ...frames(item),
      })),
    },
    apis: {
      calls: count(apis.calls),
      people: count(apis.people),
      screenViews: count(apis.screen_views),
      per100Views: maybe(apis.per_100_views),
      byRelease: list(apis.by_release).map((item) => {
        const row = object(item);
        return {
          release: text(row.release, "unknown"),
          firstAt: text(row.first_at),
          slowCalls: count(row.slow_calls),
          screenViews: count(row.screen_views),
          per100Views: maybe(row.per_100_views),
          people: count(row.people),
        };
      }),
      endpoints: list(apis.endpoints).map((item) => {
        const row = object(item);
        return {
          endpoint: text(row.endpoint),
          calls: count(row.calls),
          people: count(row.people),
          wait: stat(row.wait),
          total: stat(row.total),
          failed: count(row.failed),
          refused: count(row.refused),
          screens: list(row.screens).filter(
            (screen): screen is string => typeof screen === "string",
          ),
        };
      }),
    },
    load: {
      lcpByTier: list(load.lcp_by_tier).map((item) => {
        const row = object(item);
        return {
          tier: text(row.tier, "unknown"),
          ...stat(row),
          rating: typeof row.rating === "string" ? row.rating : null,
        };
      }),
      starts: list(load.starts).map((item) => {
        const row = object(item);
        return {
          app: text(row.app, "web"),
          start: text(row.start, "cold"),
          what: row.what === "launch" ? ("launch" as const) : ("page" as const),
          ...stat(row),
        };
      }),
      cpu: {
        tests: count(cpu.tests),
        people: count(cpu.people),
        all: stat(cpu.all),
        bands: {
          high: count(bands.high),
          mid: count(bands.mid),
          low: count(bands.low),
        },
        byModel: list(cpu.by_model).map((item) => {
          const row = object(item);
          return {
            model: text(row.model, "unknown"),
            people: count(row.people),
            cpu: stat(row.cpu),
            tier: text(row.tier, "unknown"),
            start: stat(row.start),
          };
        }),
      },
    },
    taps: list(body.taps).map((item) => {
      const row = object(item);
      return {
        action: text(row.action),
        label: text(row.label, text(row.action)),
        slowMs: count(row.slow_ms) || 1_000,
        all: stat(row.all),
        byTier: list(row.by_tier).map((part) => ({
          tier: text(object(part).tier, "unknown"),
          ...stat(part),
          slowShare: maybe(object(part).slow_share),
        })),
      };
    }),
    journey: {
      from: text(journey.from, "leads"),
      steps: list(journey.steps).map((item) => {
        const row = object(item);
        return {
          key: text(row.key),
          label: text(row.label),
          people: count(row.people),
          ofFirst: maybe(row.of_first),
          ofPrevious: maybe(row.of_previous),
        };
      }),
    },
  };
}

/** A stat's value ("120 ms", "2.4 s"), or "–" without samples. */
export function statWords(value: Stat, which: "p50" | "p75" | "p95" = "p75") {
  const number = value[which];
  if (value.n === 0 || number === null) return "–";
  return msWords(number);
}

/** How many samples, said plainly: "3 samples, too few to tell", "48 samples". */
export function samplesWords(n: number, few: boolean): string {
  if (n === 0) return "no samples";
  const words = `${n} ${n === 1 ? "sample" : "samples"}`;
  return few ? `${words}, too few to tell` : words;
}

export const TIER_WORDS: Record<string, string> = {
  low: "Low-end",
  mid: "Mid-range",
  high: "High-end",
  unknown: "Not yet tested",
};

/** Frames slower than a refresh: under 10% is smooth, over 30% feels slow. */
export function frameTone(share: number | null): Tone {
  if (share === null) return "neutral";
  return share > 0.3 ? "bad" : share > 0.1 ? "warn" : "good";
}

/** Slow calls per 100 screen views. */
export function apiTone(per100: number | null): Tone {
  if (per100 === null) return "neutral";
  return per100 > 20 ? "bad" : per100 > 5 ? "warn" : "good";
}

export function overTone(value: number | null, limit: number): Tone {
  if (value === null) return "neutral";
  return value > limit * 2 ? "bad" : value > limit ? "warn" : "good";
}

export function cpuWords(value: number | null): string {
  return value === null ? "–" : `${value.toFixed(1)} ms`;
}

/** "v1_conversation_acquisition_submissions_id_sourc" → "conversation acquisition submissions · id · sourc". */
export function endpointWords(endpoint: string): string {
  return (
    endpoint
      .replace(/^v\d+_/, "")
      .split("_id_")
      .map((part) => part.replace(/_id$/, " · id").replace(/_/g, " "))
      .join(" · id · ") || endpoint
  );
}
