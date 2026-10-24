/**
 * Admin → Product telemetry's data (GET /v1/admin/telemetry/overview, schema
 * ac.sales-xray.product-telemetry/1): read defensively, so an older API's
 * answer shows as less, never as a crash. Pure.
 */
import type { Tone } from "../ui/kit";

export const WINDOWS = ["7d", "24h", "30d"] as const;
export type TelemetryWindow = (typeof WINDOWS)[number];
export const DEVICES = ["all", "phone", "tablet", "desktop"] as const;
export const APPS = ["all", "web", "android"] as const;
export const TIERS = ["all", "low", "mid", "high", "unknown"] as const;

export type TelemetryQuery = {
  window: TelemetryWindow;
  release: string | null;
  device: (typeof DEVICES)[number];
  app: (typeof APPS)[number];
  tier: (typeof TIERS)[number];
  path: string;
};

const pick = <T extends string>(
  value: string | undefined,
  allowed: readonly T[],
): T => (allowed.includes(value as T) ? (value as T) : allowed[0]!);

/** The page's filters from its address, and the API path they ask for. */
export function telemetryQuery(params: {
  window?: string;
  release?: string;
  device?: string;
  app?: string;
  tier?: string;
}): TelemetryQuery {
  const window = pick(params.window, WINDOWS);
  const device = pick(params.device, DEVICES);
  const app = pick(params.app, APPS);
  const tier = pick(params.tier, TIERS);
  const release =
    params.release && /^[\w.:+-]{1,64}$/.test(params.release)
      ? params.release
      : null;
  const query = new URLSearchParams({ window });
  if (release) query.set("release", release);
  if (device !== "all") query.set("device", device);
  if (app !== "all") query.set("app", app);
  if (tier !== "all") query.set("tier", tier);
  return {
    window,
    release,
    device,
    app,
    tier,
    path: `/v1/admin/telemetry/overview?${query.toString()}`,
  };
}

/** The other filters, as an address part, for one row of tabs to keep. */
export function keepFilters(
  query: TelemetryQuery,
  without: keyof Omit<TelemetryQuery, "path">,
): string | undefined {
  const parts = new URLSearchParams();
  if (without !== "window" && query.window !== WINDOWS[0])
    parts.set("window", query.window);
  if (without !== "release" && query.release)
    parts.set("release", query.release);
  if (without !== "device" && query.device !== "all")
    parts.set("device", query.device);
  if (without !== "app" && query.app !== "all") parts.set("app", query.app);
  if (without !== "tier" && query.tier !== "all") parts.set("tier", query.tier);
  return parts.toString() || undefined;
}

export type Timing = {
  taps: number;
  p50: number | null;
  p75: number | null;
  p95: number | null;
  slowShare: number | null;
};

export type SpeedRow = Timing & {
  action: string;
  label: string;
  slowMs: number;
  people: number;
  devices: number;
  slowDeviceShare: number | null;
  paintP75: number | null;
  results: { settled: number; timeout: number; noChange: number };
  byTier: Array<Timing & { tier: string }>;
  byDevice: Array<Timing & { device: string }>;
  byRelease: Array<Timing & { release: string }>;
};

export type Vital = {
  metric: string;
  samples: number;
  p75: number | null;
  rating: "good" | "needs_improvement" | "poor" | null;
  shares: {
    good: number | null;
    needsImprovement: number | null;
    poor: number | null;
  };
  byDevice: Array<{ device: string; samples: number; p75: number | null }>;
  byScreen: Array<{ screen: string; samples: number; p75: number | null }>;
};

export type StartRow = {
  start: string;
  app: string;
  samples: number;
  p50: number | null;
  p75: number | null;
};

export type ScreenRow = {
  screen: string;
  views: number;
  people: number;
  stayP50: number | null;
  exitShare: number | null;
  heat: number[];
};

export type FunnelStep = {
  key: string;
  label: string;
  people: number;
  share: number | null;
};

export type ScriptError = {
  error: string;
  where: string;
  kind: string;
  source: string;
  count: number;
  people: number;
  screens: string[];
  releases: string[];
  lastAt: string;
};

export type ProductTelemetry = {
  available: boolean;
  environment: string;
  generatedAt: string;
  window: string;
  releases: string[];
  rowsRead: number;
  truncated: boolean;
  totals: {
    events: number;
    people: number;
    sessions: number;
    workspaces: number;
  };
  consent: { peopleOff: number; workspacesOff: number };
  speed: SpeedRow[];
  vitals: Vital[];
  starts: StartRow[];
  screens: {
    buckets: string[];
    hourly: boolean;
    rows: ScreenRow[];
    flows: Array<{ from: string; to: string; count: number }>;
  };
  funnels: Array<{ key: string; label: string; steps: FunnelStep[] }>;
  features: {
    activePeople: number;
    rows: Array<{
      feature: string;
      label: string;
      people: number;
      share: number | null;
    }>;
  };
  errors: {
    scripts: ScriptError[];
    apis: Array<{
      endpoint: string;
      count: number;
      failed: number;
      p75: number | null;
      screens: string[];
    }>;
    taps: Array<{
      kind: string;
      screen: string;
      target: string;
      count: number;
      people: number;
    }>;
    shown: Array<{ surface: string; code: string; count: number }>;
  };
  mix: Record<
    "device" | "tier" | "app" | "net",
    Array<{ value: string; people: number }>
  >;
  /** Phones holding a seller's changes the server doesn't have yet (counts only). */
  unsent: {
    phones: number;
    waiting: number;
    refused: number;
    oldestMin: number | null;
    rows: Array<{
      person: string;
      waiting: number;
      refused: number;
      oldestMin: number;
      reportedAt: string;
      app: string;
      appVersion: string | null;
    }>;
  };
  releaseRows: Array<{
    release: string;
    events: number;
    people: number;
    firstAt: string;
    leadOpen: Timing;
    scriptErrors: number;
  }>;
};

type Json = Record<string, unknown>;
const object = (value: unknown): Json =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Json)
    : {};
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value.slice(0, 200) : fallback;
const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;
const maybe = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const strings = (value: unknown): string[] =>
  list(value).filter((item): item is string => typeof item === "string");

function timing(value: unknown): Timing {
  const raw = object(value);
  return {
    taps: count(raw.taps),
    p50: maybe(raw.p50),
    p75: maybe(raw.p75),
    p95: maybe(raw.p95),
    slowShare: maybe(raw.slow_share),
  };
}

const RATINGS = ["good", "needs_improvement", "poor"] as const;

export function normalizeTelemetry(raw: unknown): ProductTelemetry {
  const unsent = object(object(raw).unsent);
  const body = object(raw);
  const filters = object(body.filters);
  const totals = object(body.totals);
  const consent = object(body.consent);
  const screens = object(body.screens);
  const features = object(body.features);
  const errors = object(body.errors);
  const mix = object(body.mix);
  const mixOf = (key: string) =>
    list(mix[key]).map((item) => {
      const row = object(item);
      return { value: text(row.value, "unknown"), people: count(row.people) };
    });
  return {
    available: body.schema === "ac.sales-xray.product-telemetry/1",
    environment: text(body.environment),
    generatedAt: text(body.generated_at),
    window: text(body.window, "7d"),
    releases: strings(filters.releases),
    rowsRead: count(body.rows_read),
    truncated: body.truncated === true,
    totals: {
      events: count(totals.events),
      people: count(totals.people),
      sessions: count(totals.sessions),
      workspaces: count(totals.workspaces),
    },
    consent: {
      peopleOff: count(consent.people_off),
      workspacesOff: count(consent.workspaces_off),
    },
    speed: list(body.speed).map((item) => {
      const row = object(item);
      const results = object(row.results);
      return {
        ...timing(row),
        action: text(row.action, "other"),
        label: text(row.label, text(row.action, "Other")),
        slowMs: count(row.slow_ms) || 1_000,
        people: count(row.people),
        devices: count(row.devices),
        slowDeviceShare: maybe(row.slow_device_share),
        paintP75: maybe(row.paint_p75),
        results: {
          settled: count(results.settled),
          timeout: count(results.timeout),
          noChange: count(results.no_change),
        },
        byTier: list(row.by_tier).map((part) => ({
          ...timing(part),
          tier: text(object(part).tier, "unknown"),
        })),
        byDevice: list(row.by_device).map((part) => ({
          ...timing(part),
          device: text(object(part).device, "unknown"),
        })),
        byRelease: list(row.by_release).map((part) => ({
          ...timing(part),
          release: text(object(part).release),
        })),
      };
    }),
    vitals: list(body.vitals).map((item) => {
      const row = object(item);
      const shares = object(row.shares);
      const rating = text(row.rating);
      return {
        metric: text(row.metric),
        samples: count(row.samples),
        p75: maybe(row.p75),
        rating: (RATINGS as readonly string[]).includes(rating)
          ? (rating as Vital["rating"])
          : null,
        shares: {
          good: maybe(shares.good),
          needsImprovement: maybe(shares.needs_improvement),
          poor: maybe(shares.poor),
        },
        byDevice: list(row.by_device).map((part) => {
          const value = object(part);
          return {
            device: text(value.device),
            samples: count(value.samples),
            p75: maybe(value.p75),
          };
        }),
        byScreen: list(row.by_screen).map((part) => {
          const value = object(part);
          return {
            screen: text(value.screen),
            samples: count(value.samples),
            p75: maybe(value.p75),
          };
        }),
      };
    }),
    starts: list(body.starts).map((item) => {
      const row = object(item);
      return {
        start: text(row.start),
        app: text(row.app),
        samples: count(row.samples),
        p50: maybe(row.p50),
        p75: maybe(row.p75),
      };
    }),
    screens: {
      buckets: strings(screens.buckets),
      hourly: screens.hourly === true,
      rows: list(screens.rows).map((item) => {
        const row = object(item);
        return {
          screen: text(row.screen, "other"),
          views: count(row.views),
          people: count(row.people),
          stayP50: maybe(row.stay_p50),
          exitShare: maybe(row.exit_share),
          heat: list(row.heat).map(count),
        };
      }),
      flows: list(screens.flows).map((item) => {
        const row = object(item);
        return {
          from: text(row.from),
          to: text(row.to),
          count: count(row.count),
        };
      }),
    },
    funnels: list(body.funnels).map((item) => {
      const row = object(item);
      return {
        key: text(row.key),
        label: text(row.label),
        steps: list(row.steps).map((part) => {
          const step = object(part);
          return {
            key: text(step.key),
            label: text(step.label),
            people: count(step.people),
            share: maybe(step.share),
          };
        }),
      };
    }),
    features: {
      activePeople: count(features.active_people),
      rows: list(features.rows).map((item) => {
        const row = object(item);
        return {
          feature: text(row.feature),
          label: text(row.label, text(row.feature)),
          people: count(row.people),
          share: maybe(row.share),
        };
      }),
    },
    errors: {
      scripts: list(errors.scripts).map((item) => {
        const row = object(item);
        return {
          error: text(row.error, "error"),
          where: text(row.where),
          kind: text(row.kind, "error"),
          source: text(row.source, "unknown"),
          count: count(row.count),
          people: count(row.people),
          screens: strings(row.screens),
          releases: strings(row.releases),
          lastAt: text(row.last_at),
        };
      }),
      apis: list(errors.apis).map((item) => {
        const row = object(item);
        return {
          endpoint: text(row.endpoint),
          count: count(row.count),
          failed: count(row.failed),
          p75: maybe(row.p75),
          screens: strings(row.screens),
        };
      }),
      taps: list(errors.taps).map((item) => {
        const row = object(item);
        return {
          kind: text(row.kind),
          screen: text(row.screen),
          target: text(row.target),
          count: count(row.count),
          people: count(row.people),
        };
      }),
      shown: list(errors.shown).map((item) => {
        const row = object(item);
        return {
          surface: text(row.surface),
          code: text(row.code),
          count: count(row.count),
        };
      }),
    },
    mix: {
      device: mixOf("device"),
      tier: mixOf("tier"),
      app: mixOf("app"),
      net: mixOf("net"),
    },
    unsent: {
      phones: count(unsent.phones),
      waiting: count(unsent.waiting),
      refused: count(unsent.refused),
      oldestMin: maybe(unsent.oldest_min),
      rows: list(unsent.rows).map((item) => {
        const row = object(item);
        return {
          person: text(row.person),
          waiting: count(row.waiting),
          refused: count(row.refused),
          oldestMin: count(row.oldest_min),
          reportedAt: text(row.reported_at),
          app: text(row.app, "web"),
          appVersion:
            typeof row.app_version === "string" ? row.app_version : null,
        };
      }),
    },
    releaseRows: list(body.releases).map((item) => {
      const row = object(item);
      return {
        release: text(row.release),
        events: count(row.events),
        people: count(row.people),
        firstAt: text(row.first_at),
        leadOpen: timing(row.lead_open),
        scriptErrors: count(row.script_errors),
      };
    }),
  };
}

/** 95 → "1 h 35 min"; 12 → "12 min". */
export function ageWords(minutes: number | null): string {
  if (minutes === null) return "–";
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 48 * 60)
    return `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
  return `${Math.floor(minutes / (24 * 60))} days`;
}

/** 0.6 → "60%"; a share of nothing is a dash. */
export function shareWords(value: number | null): string {
  if (value === null) return "–";
  const percent = value * 100;
  return `${percent >= 10 || percent === 0 ? Math.round(percent) : percent.toFixed(1)}%`;
}

/** 840 → "840 ms"; 1840 → "1.84 s"; 65000 → "65 s". */
export function msWords(value: number | null): string {
  if (value === null) return "–";
  if (value < 1_000) return `${Math.round(value)} ms`;
  const seconds = value / 1_000;
  return `${seconds < 10 ? Number(seconds.toFixed(2)) : Math.round(seconds)} s`;
}

/** Green under 10% slow, amber under 25%, red above. */
export function slowTone(share: number | null): Tone {
  if (share === null) return "neutral";
  return share < 0.1 ? "good" : share < 0.25 ? "warn" : "bad";
}

export function ratingTone(rating: Vital["rating"]): Tone {
  return rating === "good"
    ? "good"
    : rating === "needs_improvement"
      ? "warn"
      : rating === "poor"
        ? "bad"
        : "neutral";
}

const SCREEN_WORDS: Record<string, string> = {
  home: "Home",
  dashboard: "Dashboard",
  analysis: "Analysis",
  new_call: "New call",
  calls_list: "Calls (analysis)",
  report: "Call report",
  calls: "Calls",
  leads: "Leads",
  lead: "A lead",
  chats: "Chats",
  coaching: "Coaching",
  prospects: "Prospects",
  prospect: "A prospect",
  organisation: "Organisation",
  org_insights: "Organisation insights",
  org_invites: "Invites",
  org_person: "A team member",
  settings: "Settings",
  settings_section: "A settings section",
  account: "Account",
  billing: "Billing",
  plans: "Plans",
  apps: "Apps",
  developers: "Developers",
  review: "Review",
  other: "Other",
  none: "Start",
};

export const screenWords = (screen: string) => SCREEN_WORDS[screen] ?? screen;

export const VITAL_WORDS: Record<
  string,
  { label: string; unit: "ms" | "cls" }
> = {
  lcp: { label: "Largest paint (LCP)", unit: "ms" },
  inp: { label: "Response to input (INP)", unit: "ms" },
  cls: { label: "Layout shift (CLS)", unit: "cls" },
  fcp: { label: "First paint (FCP)", unit: "ms" },
  ttfb: { label: "First byte (TTFB)", unit: "ms" },
};

/** A vital's value in its unit: CLS arrives times 1,000. */
export function vitalWords(metric: string, value: number | null): string {
  if (value === null) return "–";
  return VITAL_WORDS[metric]?.unit === "cls"
    ? (value / 1_000).toFixed(2)
    : msWords(value);
}

/** Heat level 0 (none) to 4 (the busiest bucket of the row). */
export function heatLevel(value: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (!value || !max) return 0;
  return Math.min(4, Math.max(1, Math.ceil((value / max) * 4))) as
    | 1
    | 2
    | 3
    | 4;
}

/** The headline for the action people asked about: how many devices are slow. */
export function slowDeviceLine(row: SpeedRow | undefined): string | null {
  if (!row || row.devices === 0 || row.slowDeviceShare === null) return null;
  return `${shareWords(row.slowDeviceShare)} of devices are slow when they ${
    row.action === "lead_open" ? "open a lead" : row.label.toLowerCase()
  } (their median is over ${msWords(row.slowMs)}).`;
}
