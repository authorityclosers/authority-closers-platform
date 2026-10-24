/**
 * The improvement loop's data (owner, 24 Oct 2026: "where is the telemetry data of each
 * device ... use in our recursive improvement pipeline each new update"): Devices, Releases
 * and Fix next, read from /v1/admin/telemetry/{devices,compare,fix-next}. Counts, timings
 * and codes only: no person, workspace or call is named.
 */
import type { Tone } from "../ui/kit";
import { msWords } from "./telemetry-data";

type Json = Record<string, unknown>;
const object = (value: unknown): Json =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Json)
    : {};
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value.slice(0, 300) : fallback;
const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;
const maybe = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

export const KEY_ACTIONS = [
  "lead_open",
  "tab_switch",
  "call_start",
  "report_open",
] as const;
export type KeyAction = (typeof KEY_ACTIONS)[number];
export const ACTION_WORDS: Record<KeyAction, string> = {
  lead_open: "Open a lead",
  tab_switch: "Switch tab",
  call_start: "Call",
  report_open: "Open a report",
};
const SLOW_MS: Record<KeyAction, number> = {
  lead_open: 1_000,
  tab_switch: 500,
  call_start: 1_000,
  report_open: 1_500,
};

/* ---------- Devices ---------- */

export type Counted = { value: string; people: number };
export type ActionTiming = {
  taps: number;
  p50: number | null;
  p75: number | null;
  slowShare: number | null;
};
export type Issues = {
  scriptErrors: number;
  errorsShown: number;
  failedCalls: number;
  crashes: number;
  killed: number;
  rageTaps: number;
  deadTaps: number;
};
type DeviceName = {
  key: string;
  kind: "model" | "class";
  maker: string;
  model: string;
  app: string;
  device: string;
  tier: string;
  label: string;
};
export type DeviceGroup = DeviceName &
  Issues & {
    people: number;
    events: number;
    appVersions: Counted[];
    android: Counted[];
    webview: Counted[];
    ram: Counted[];
    tiers: Counted[];
    networks: Counted[];
    actions: Partial<Record<KeyAction, ActionTiming>>;
    taps: number;
    slowTailTaps: number;
    slowTailShare: number | null;
    speedIndex: number | null;
  };
export type SlowDevice = DeviceName &
  Issues & {
    speedIndex: number;
    taps: number;
    appVersion: string;
    android: number | null;
    ram: string | null;
    network: string | null;
    actions: Partial<Record<KeyAction, ActionTiming>>;
  };
export type Devices = {
  available: boolean;
  environment: string;
  window: string;
  totals: {
    devices: number;
    ranked: number;
    models: number;
    classes: number;
    slowDevices: number;
    slowShare: number | null;
  };
  groups: DeviceGroup[];
  slowest: SlowDevice[];
  cutoffIndex: number | null;
  medianIndex: number | null;
  truncated: boolean;
};

const DEVICE_WORDS: Record<string, string> = {
  phone: "Phone",
  tablet: "Tablet",
  desktop: "Computer",
};
const TIER_WORDS: Record<string, string> = {
  low: "low-end",
  mid: "mid-range",
  high: "high-end",
  unknown: "unknown tier",
};

/** "xiaomi", "redmi_note_8_pro" → "Xiaomi Redmi Note 8 Pro"; codes stay in capitals. */
export function modelWords(maker: string, model: string): string {
  const word = (part: string) =>
    /\d/.test(part)
      ? part.toUpperCase()
      : part.charAt(0).toUpperCase() + part.slice(1);
  const name = model
    .split(/[_\s]+/)
    .filter(Boolean)
    .map(word)
    .join(" ");
  const make = maker ? word(maker) : "";
  return make && !name.toLowerCase().startsWith(make.toLowerCase())
    ? `${make} ${name}`
    : name || make || "Unknown phone";
}

export function deviceLabel(name: Omit<DeviceName, "label">): string {
  if (name.kind === "model") return modelWords(name.maker, name.model);
  const device = DEVICE_WORDS[name.device] ?? "Device";
  const app = name.app === "android" ? "Android app" : "web";
  return `${device}, ${app}, ${TIER_WORDS[name.tier] ?? name.tier}`;
}

const counted = (value: unknown): Counted[] =>
  list(value).map((item) => {
    const row = object(item);
    return { value: text(row.value, "unknown"), people: count(row.people) };
  });

function actions(value: unknown): Partial<Record<KeyAction, ActionTiming>> {
  const raw = object(value);
  const out: Partial<Record<KeyAction, ActionTiming>> = {};
  for (const action of KEY_ACTIONS) {
    const timing = object(raw[action]);
    if (!Object.keys(timing).length) continue;
    out[action] = {
      taps: count(timing.taps),
      p50: maybe(timing.p50),
      p75: maybe(timing.p75),
      slowShare: maybe(timing.slow_share),
    };
  }
  return out;
}

function deviceName(row: Json): DeviceName {
  const raw = {
    key: text(row.key),
    kind: row.kind === "model" ? ("model" as const) : ("class" as const),
    maker: text(row.maker),
    model: text(row.model),
    app: text(row.app, "web"),
    device: text(row.device, "unknown"),
    tier: text(row.tier, "unknown"),
  };
  return { ...raw, label: deviceLabel(raw) };
}

const issues = (row: Json): Issues => ({
  scriptErrors: count(row.script_errors),
  errorsShown: count(row.errors_shown),
  failedCalls: count(row.failed_calls),
  crashes: count(row.crashes),
  killed: count(row.killed),
  rageTaps: count(row.rage_taps),
  deadTaps: count(row.dead_taps),
});

export function normalizeDevices(raw: unknown): Devices {
  const body = object(raw);
  const totals = object(body.totals);
  const slowest = object(body.slowest);
  return {
    available: body.schema === "ac.sales-xray.telemetry-devices/1",
    environment: text(body.environment),
    window: text(body.window, "7d"),
    totals: {
      devices: count(totals.devices),
      ranked: count(totals.ranked),
      models: count(totals.models),
      classes: count(totals.classes),
      slowDevices: count(totals.slow_devices),
      slowShare: maybe(totals.slow_share),
    },
    groups: list(body.groups).map((item) => {
      const row = object(item);
      return {
        ...deviceName(row),
        ...issues(row),
        people: count(row.people),
        events: count(row.events),
        appVersions: counted(row.app_versions),
        android: counted(row.android),
        webview: counted(row.webview),
        ram: counted(row.ram),
        tiers: counted(row.tiers),
        networks: counted(row.networks),
        actions: actions(row.actions),
        taps: count(row.taps),
        slowTailTaps: count(row.slow_tail_taps),
        slowTailShare: maybe(row.slow_tail_share),
        speedIndex: maybe(row.speed_index),
      };
    }),
    slowest: list(slowest.devices).map((item) => {
      const row = object(item);
      return {
        ...deviceName(row),
        ...issues(row),
        speedIndex: count(row.speed_index),
        taps: count(row.taps),
        appVersion: text(row.app_version),
        android: maybe(row.android),
        ram: typeof row.ram === "string" ? row.ram : null,
        network: typeof row.network === "string" ? row.network : null,
        actions: actions(row.actions),
      };
    }),
    cutoffIndex: maybe(slowest.cutoff_index),
    medianIndex: maybe(slowest.median_index),
    truncated: body.truncated === true,
  };
}

/** People per value across devices (each device's own count added up). */
export function mixOf(
  groups: readonly DeviceGroup[],
  pick: (group: DeviceGroup) => Counted[],
): Counted[] {
  const totals = new Map<string, number>();
  for (const group of groups)
    for (const item of pick(group))
      totals.set(item.value, (totals.get(item.value) ?? 0) + item.people);
  return [...totals]
    .map(([value, people]) => ({ value, people }))
    .sort((a, b) => b.people - a.people || a.value.localeCompare(b.value));
}

export const RAM_WORDS = (tier: string) =>
  tier === "12plus" ? "12 GB or more" : `${tier} GB`;
export const NET_WORDS: Record<string, string> = {
  "4g": "4G",
  "3g": "3G",
  "2g": "2G",
  "slow-2g": "Slow 2G",
  offline: "Offline",
  unknown: "Unknown",
};

/** A device's typical tap against the slow limit: 1.0 is a tap exactly at "slow". */
export const indexWords = (value: number | null) =>
  value === null ? "–" : `${value.toFixed(1)}×`;

export function speedTone(action: KeyAction, p75: number | null): Tone {
  if (p75 === null) return "neutral";
  const limit = SLOW_MS[action];
  return p75 <= limit ? "good" : p75 <= limit * 2 ? "warn" : "bad";
}

export const slowLimit = (action: KeyAction) => SLOW_MS[action];

/** Bars for one key action, slowest first: the devices with taps on it. */
export function actionBars(
  groups: readonly DeviceGroup[],
  action: KeyAction,
): Array<{ key: string; label: string; p75: number; taps: number }> {
  return groups
    .flatMap((group) => {
      const timing = group.actions[action];
      return timing && timing.p75 !== null
        ? [
            {
              key: group.key,
              label: group.label,
              p75: timing.p75,
              taps: timing.taps,
            },
          ]
        : [];
    })
    .sort((a, b) => b.p75 - a.p75);
}

/* ---------- Releases ---------- */

export type Verdict = "better" | "same" | "worse" | "too_few";
export type Metric = {
  key: string;
  kind: "speed" | "rate" | "vital" | "funnel";
  label: string;
  unit: "ms" | "per_100_sessions" | "share";
  base: number | null;
  head: number | null;
  baseSamples: number;
  headSamples: number;
  change: number | null;
  verdict: Verdict;
  regression: boolean;
};
export type ReleaseRow = {
  release: string;
  firstAt: string;
  events: number;
  sessions: number;
  taps: number;
};
export type Comparison = {
  available: boolean;
  environment: string;
  head: string | null;
  base: string | null;
  releases: ReleaseRow[];
  metrics: Metric[];
  blockRule: string;
  warnRule: string;
};

const VERDICTS: readonly Verdict[] = ["better", "same", "worse", "too_few"];
const KINDS = ["speed", "rate", "vital", "funnel"] as const;
const UNITS = ["ms", "per_100_sessions", "share"] as const;

export function normalizeComparison(raw: unknown): Comparison {
  const body = object(raw);
  const thresholds = object(body.thresholds);
  return {
    available: body.schema === "ac.sales-xray.telemetry-compare/1",
    environment: text(body.environment),
    head: typeof body.head === "string" ? body.head : null,
    base: typeof body.base === "string" ? body.base : null,
    releases: list(body.releases).map((item) => {
      const row = object(item);
      return {
        release: text(row.release),
        firstAt: text(row.first_at),
        events: count(row.events),
        sessions: count(row.sessions),
        taps: count(row.taps),
      };
    }),
    metrics: list(body.metrics).map((item) => {
      const row = object(item);
      const verdict = text(row.verdict) as Verdict;
      const kind = text(row.kind) as Metric["kind"];
      const unit = text(row.unit) as Metric["unit"];
      return {
        key: text(row.key),
        kind: KINDS.includes(kind) ? kind : "rate",
        label: text(row.label),
        unit: UNITS.includes(unit) ? unit : "ms",
        base: maybe(row.base),
        head: maybe(row.head),
        baseSamples: count(row.base_samples),
        headSamples: count(row.head_samples),
        change: maybe(row.change),
        verdict: VERDICTS.includes(verdict) ? verdict : "too_few",
        regression: row.regression === true,
      };
    }),
    blockRule: text(thresholds.block),
    warnRule: text(thresholds.warn),
  };
}

export function metricWords(unit: Metric["unit"], value: number | null) {
  if (value === null) return "–";
  if (unit === "ms") return msWords(value);
  if (unit === "share") return `${Math.round(value * 100)}%`;
  return `${value % 1 ? value.toFixed(1) : value} per 100 sessions`;
}

/** "v0.85 880 ms → v0.86 920 ms"; rates say their unit once, at the end. */
export function trendWords(
  unit: Metric["unit"],
  parts: ReadonlyArray<{ release: string; value: number | null }>,
): string {
  const line = parts
    .map(
      (part) =>
        `${part.release} ${
          unit === "per_100_sessions"
            ? part.value === null
              ? "–"
              : String(part.value)
            : metricWords(unit, part.value)
        }`,
    )
    .join(" → ");
  return unit === "per_100_sessions" ? `${line} per 100 sessions` : line;
}

export function changeWords(metric: Metric): string {
  if (metric.change === null) return "–";
  if (metric.unit === "share") {
    const points = Math.round(metric.change * 100);
    return `${points > 0 ? "+" : ""}${points} points`;
  }
  const percent = Math.round(metric.change * 100);
  return `${percent > 0 ? "+" : ""}${percent}%`;
}

export const VERDICT_WORDS: Record<Verdict, string> = {
  better: "Better",
  same: "About the same",
  worse: "Worse",
  too_few: "Too few to say",
};
export const verdictTone = (verdict: Verdict): Tone =>
  verdict === "better" ? "good" : verdict === "worse" ? "warn" : "neutral";

/** The release gate's answer for the head release (the same rule the API's gate applies). */
export function gateWords(comparison: Comparison): {
  verdict: "pass" | "block" | "not_enough_data";
  line: string;
} {
  const regressions = comparison.metrics.filter((item) => item.regression);
  if (regressions.length)
    return {
      verdict: "block",
      line: `Would block promotion: ${regressions.map((item) => item.label.toLowerCase()).join(", ")} got slower past the limit. The owner can override.`,
    };
  const measured = comparison.metrics.some(
    (item) => item.kind === "speed" && item.verdict !== "too_few",
  );
  return measured && comparison.base
    ? {
        verdict: "pass",
        line: "Passes: no key action got slower past the limit.",
      }
    : {
        verdict: "not_enough_data",
        line: "Not enough taps in both releases to judge; that never blocks.",
      };
}

/* ---------- Fix next ---------- */

export type FixItem = {
  key: string;
  kind: string;
  title: string;
  screenLabel: string;
  severity: number;
  severityLabel: string;
  people: number;
  events: number;
  score: number;
  evidence: Array<[string, string]>;
  unit: Metric["unit"];
  now: number | null;
  before: number | null;
  isNew: boolean;
  byRelease: Array<{ release: string; value: number | null }>;
  owner: string;
  task: string;
};
export type Improved = {
  key: string;
  title: string;
  unit: Metric["unit"];
  before: number | null;
  now: number | null;
  gone: boolean;
  peopleBefore: number;
};
export type FixNext = {
  available: boolean;
  environment: string;
  window: string;
  items: FixItem[];
  more: number;
  improved: Improved[];
  people: number;
};

const EVIDENCE_WORDS: Record<string, string> = {
  taps: "taps",
  p50: "median",
  p75: "75th percentile",
  slow_share: "slow share",
  slow_ms: "slow over",
  slow_tiers: "mostly on",
  count: "times",
  source: "from",
  screens: "screens",
  kind: "kind",
  failed: "failed",
  calls: "calls",
  foreground: "while open",
  metric: "measure",
  poor_over: "poor over",
  denied: "refused",
  asked: "asked",
  share: "share refused",
  target: "on a",
};
const MS_KEYS = new Set(["p50", "p75", "slow_ms", "poor_over"]);
const SHARE_KEYS = new Set(["slow_share", "share"]);

function evidence(value: unknown): Array<[string, string]> {
  return Object.entries(object(value)).flatMap(([key, item]) => {
    if (item === null || item === undefined || item === "") return [];
    const label = EVIDENCE_WORDS[key] ?? key.replace(/_/g, " ");
    if (Array.isArray(item))
      return item.length
        ? [[label, item.map((part) => String(part)).join(", ")]]
        : [];
    if (typeof item === "number")
      return [
        [
          label,
          MS_KEYS.has(key)
            ? msWords(item)
            : SHARE_KEYS.has(key)
              ? `${Math.round(item * 100)}%`
              : String(item),
        ],
      ];
    return [[label, String(item).slice(0, 80)]];
  }) as Array<[string, string]>;
}

export function normalizeFixNext(raw: unknown): FixNext {
  const body = object(raw);
  const unitOf = (value: unknown): Metric["unit"] =>
    UNITS.includes(value as Metric["unit"])
      ? (value as Metric["unit"])
      : "per_100_sessions";
  return {
    available: body.schema === "ac.sales-xray.telemetry-fix-next/1",
    environment: text(body.environment),
    window: text(body.window, "7d"),
    items: list(body.items).map((item) => {
      const row = object(item);
      return {
        key: text(row.key),
        kind: text(row.kind),
        title: text(row.title),
        screenLabel: text(row.screen_label),
        severity: count(row.severity),
        severityLabel: text(row.severity_label),
        people: count(row.people),
        events: count(row.events),
        score: count(row.score),
        evidence: evidence(row.evidence),
        unit: unitOf(row.unit),
        now: maybe(row.now),
        before: maybe(row.before),
        isNew: row.new === true,
        byRelease: list(row.by_release).map((part) => {
          const value = object(part);
          return { release: text(value.release), value: maybe(value.value) };
        }),
        owner: text(row.owner),
        task: typeof row.task === "string" ? row.task.slice(0, 2_000) : "",
      };
    }),
    more: count(body.more),
    improved: list(body.improved).map((item) => {
      const row = object(item);
      return {
        key: text(row.key),
        title: text(row.title),
        unit: unitOf(row.unit),
        before: maybe(row.before),
        now: maybe(row.now),
        gone: row.gone === true,
        peopleBefore: count(row.people_before),
      };
    }),
    people: count(body.people),
  };
}

export const severityTone = (severity: number): Tone =>
  severity >= 4 ? "bad" : severity === 3 ? "warn" : "neutral";

/* ---------- Addresses ---------- */

export const LOOP_WINDOWS = ["7d", "24h", "30d"] as const;
const pickWindow = (value: string | undefined) =>
  (LOOP_WINDOWS as readonly string[]).includes(value ?? "")
    ? (value as (typeof LOOP_WINDOWS)[number])
    : "7d";
const release = (value: string | undefined) =>
  value && /^[A-Za-z0-9._-]{1,64}$/.test(value) ? value : undefined;

export function devicesQuery(params: {
  window?: string;
  app?: string;
  action?: string;
}) {
  const window = pickWindow(params.window);
  const app =
    params.app === "web" || params.app === "android" ? params.app : "all";
  const action = (KEY_ACTIONS as readonly string[]).includes(
    params.action ?? "",
  )
    ? (params.action as KeyAction)
    : "lead_open";
  const query = new URLSearchParams({ window });
  if (app !== "all") query.set("app", app);
  return {
    window,
    app,
    action,
    path: `/v1/admin/telemetry/devices?${query.toString()}`,
  };
}

export function compareQuery(params: { head?: string; base?: string }) {
  const head = release(params.head);
  const base = release(params.base);
  const query = new URLSearchParams();
  if (head) query.set("head", head);
  if (base) query.set("base", base);
  const search = query.toString();
  return {
    head,
    base,
    path: `/v1/admin/telemetry/compare${search ? `?${search}` : ""}`,
  };
}

export function fixNextQuery(params: { window?: string }) {
  const window = pickWindow(params.window);
  return { window, path: `/v1/admin/telemetry/fix-next?window=${window}` };
}
