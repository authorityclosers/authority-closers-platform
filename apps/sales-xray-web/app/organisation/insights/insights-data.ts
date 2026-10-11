/**
 * The company view's data (AUT-1798): one read with every aggregate, and a
 * paged list of the calls behind it. Parsing never throws on a missing or
 * odd field: numbers default to 0, lists to empty, text to null, so a page
 * built from an older or partial answer still renders.
 */

export const INSIGHTS_PATH = "/v1/conversation/acquisition/insights";

export const RANGES = [
  { key: "30d", label: "30 days" },
  { key: "90d", label: "90 days" },
  { key: "12m", label: "12 months" },
  { key: "all", label: "All time" },
] as const;
export type RangeKey = (typeof RANGES)[number]["key"];

export const OUTCOMES = [
  { key: "won", label: "Won" },
  { key: "booked", label: "Meeting booked" },
  { key: "follow_up", label: "Follow-up set" },
  { key: "deferred", label: "Deferred" },
  { key: "lost", label: "Lost" },
  { key: "disqualified", label: "Disqualified" },
  { key: "unclear", label: "No clear next step" },
] as const;
export type OutcomeKey = (typeof OUTCOMES)[number]["key"];
export const outcomeLabel = (key: string) =>
  OUTCOMES.find((item) => item.key === key)?.label ?? "No clear next step";

export const SKILLS = [
  { id: "human_connection_trust", short: "Trust" },
  { id: "discovery_deep_understanding", short: "Discovery" },
  { id: "qualification", short: "Qualify" },
  { id: "problem_impact_desire", short: "Impact" },
  { id: "solution_relevance_presentation", short: "Solution" },
  { id: "certainty_objection_intelligence", short: "Objections" },
  { id: "closing_decision_management", short: "Closing" },
  { id: "communication_tonality", short: "Tone" },
] as const;

export const VIEWS = [
  { key: "overview", label: "Overview" },
  { key: "people", label: "People" },
  { key: "calls", label: "Calls" },
] as const;
export type View = (typeof VIEWS)[number]["key"];

/** The view from the address (?view=people|calls); Overview by default. */
export function viewFrom(
  params: Readonly<Record<string, string | string[] | undefined>>,
): View {
  const value = params.view;
  const text = Array.isArray(value) ? value[0] : value;
  return VIEWS.find((item) => item.key === text)?.key ?? "overview";
}

export type Filters = {
  range: RangeKey;
  person: string | null;
  team: string | null;
  outcome: OutcomeKey | null;
  language: string | null;
};

export const DEFAULT_FILTERS: Filters = {
  range: "90d",
  person: null,
  team: null,
  outcome: null,
  language: null,
};

export type Totals = {
  calls: number;
  minutes: number;
  people: number;
  won: number;
  nextStep: number;
  nextStepShare: number | null;
  winShare: number | null;
  talkShare: number | null;
  talkCalls: number;
  needsAttentionShare: number | null;
  wonValue: number | null;
  firstAt: string | null;
  lastAt: string | null;
};

export type TrendPoint = {
  at: string;
  calls: number;
  won: number;
  nextStep: number;
  needsAttentionShare: number | null;
  talkShare: number | null;
};

export type SkillTotal = {
  id: string;
  label: string;
  strong: number;
  observed: number;
  needsAttention: number;
  unknown: number;
};

export type Group = {
  key: string | null;
  name: string;
  team: string | null;
  calls: number;
  minutes: number;
  won: number;
  nextStep: number;
  talkShare: number | null;
  lastAt: string | null;
  coachingDone: number | null;
  skills: { id: string; observed: number; needsAttention: number }[];
  needsAttentionChange: number | null;
};

export type CallRow = {
  key: string;
  personKey: string | null;
  person: string;
  team: string | null;
  at: string | null;
  outcome: string;
  durationMs: number | null;
  skills: string | null;
  observed: number | null;
  needsAttention: number | null;
  language: string | null;
  talkShare: number | null;
  objections: string[];
  dealValue: number | null;
};

export type Insights = {
  source: "call" | "synthetic";
  synthetic: boolean;
  window: { from: string | null; to: string | null; unit: "week" | "month" };
  pending: number;
  totals: Totals;
  previous: Totals | null;
  trend: TrendPoint[];
  outcomes: { outcome: string; calls: number }[];
  skills: SkillTotal[];
  people: Group[];
  teams: Group[];
  objections: { kind: string; label: string; calls: number; won: number }[];
  mistakes: { kind: string; label: string; calls: number }[];
  talk: { band: string; label: string; calls: number }[];
  strongest: CallRow[];
  weakest: CallRow[];
  facets: {
    people: { key: string; name: string; team: string | null }[];
    teams: { key: string; name: string }[];
    languages: { key: string; label: string }[];
  };
};

export type CallPage = {
  synthetic: boolean;
  total: number;
  nextOffset: number | null;
  items: CallRow[];
};

type Raw = Record<string, unknown>;
const record = (value: unknown): Raw =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Raw)
    : {};
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const num = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) ? value : 0;
const maybe = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const str = (value: unknown): string | null =>
  typeof value === "string" && value ? value : null;

function totals(value: unknown): Totals {
  const raw = record(value);
  return {
    calls: num(raw.calls),
    minutes: num(raw.minutes),
    people: num(raw.people),
    won: num(raw.won),
    nextStep: num(raw.next_step),
    nextStepShare: maybe(raw.next_step_share),
    winShare: maybe(raw.win_share),
    talkShare: maybe(raw.talk_share),
    talkCalls: num(raw.talk_calls),
    needsAttentionShare: maybe(raw.needs_attention_share),
    wonValue: maybe(raw.won_value),
    firstAt: str(raw.first_at),
    lastAt: str(raw.last_at),
  };
}

function group(value: unknown): Group {
  const raw = record(value);
  return {
    key: str(raw.key),
    name: str(raw.name) ?? "Unassigned",
    team: str(raw.team),
    calls: num(raw.calls),
    minutes: num(raw.minutes),
    won: num(raw.won),
    nextStep: num(raw.next_step),
    talkShare: maybe(raw.talk_share),
    lastAt: str(raw.last_at),
    coachingDone: maybe(raw.coaching_done),
    skills: list(raw.skills).map((cell) => {
      const item = record(cell);
      return {
        id: str(item.id) ?? "",
        observed: num(item.observed),
        needsAttention: num(item.needs_attention),
      };
    }),
    needsAttentionChange: maybe(raw.needs_attention_change),
  };
}

export function callRow(value: unknown): CallRow {
  const raw = record(value);
  const skills = str(raw.skills);
  return {
    key: str(raw.key) ?? "",
    personKey: str(raw.person_key),
    person: str(raw.person) ?? "Unassigned",
    team: str(raw.team),
    at: str(raw.at),
    outcome: str(raw.outcome) ?? "unclear",
    durationMs: maybe(raw.duration_ms),
    skills: skills && skills.length === 8 ? skills : null,
    observed: maybe(raw.observed),
    needsAttention: maybe(raw.needs_attention),
    language: str(raw.language),
    talkShare: maybe(raw.talk_share),
    objections: list(raw.objections).filter(
      (item): item is string => typeof item === "string",
    ),
    dealValue: maybe(raw.deal_value),
  };
}

export function parseInsights(body: unknown): Insights {
  const raw = record(body);
  const window = record(raw.window);
  const facets = record(raw.facets);
  const calls = record(raw.calls);
  return {
    source: raw.source === "synthetic" ? "synthetic" : "call",
    synthetic: raw.synthetic === true,
    window: {
      from: str(window.from),
      to: str(window.to),
      unit: window.unit === "week" ? "week" : "month",
    },
    pending: num(raw.pending),
    totals: totals(raw.totals),
    previous: raw.previous ? totals(raw.previous) : null,
    trend: list(raw.trend).map((point) => {
      const item = record(point);
      return {
        at: str(item.at) ?? "",
        calls: num(item.calls),
        won: num(item.won),
        nextStep: num(item.next_step),
        needsAttentionShare: maybe(item.needs_attention_share),
        talkShare: maybe(item.talk_share),
      };
    }),
    outcomes: list(raw.outcomes).map((entry) => {
      const item = record(entry);
      return {
        outcome: str(item.outcome) ?? "unclear",
        calls: num(item.calls),
      };
    }),
    skills: list(raw.skills).map((entry) => {
      const item = record(entry);
      return {
        id: str(item.id) ?? "",
        label: str(item.label) ?? "",
        strong: num(item.strong),
        observed: num(item.observed),
        needsAttention: num(item.needs_attention),
        unknown: num(item.unknown),
      };
    }),
    people: list(raw.people).map(group),
    teams: list(raw.teams).map(group),
    objections: list(raw.objections).map((entry) => {
      const item = record(entry);
      return {
        kind: str(item.kind) ?? "",
        label: str(item.label) ?? "Other",
        calls: num(item.calls),
        won: num(item.won),
      };
    }),
    mistakes: list(raw.mistakes).map((entry) => {
      const item = record(entry);
      return {
        kind: str(item.kind) ?? "",
        label: str(item.label) ?? "Other",
        calls: num(item.calls),
      };
    }),
    talk: list(raw.talk).map((entry) => {
      const item = record(entry);
      return {
        band: str(item.band) ?? "",
        label: str(item.label) ?? "",
        calls: num(item.calls),
      };
    }),
    strongest: list(calls.strongest).map(callRow),
    weakest: list(calls.weakest).map(callRow),
    facets: {
      people: list(facets.people).flatMap((entry) => {
        const item = record(entry);
        const key = str(item.key);
        return key
          ? [
              {
                key,
                name: str(item.name) ?? "Unassigned",
                team: str(item.team),
              },
            ]
          : [];
      }),
      teams: list(facets.teams).flatMap((entry) => {
        const item = record(entry);
        const key = str(item.key);
        return key ? [{ key, name: str(item.name) ?? key }] : [];
      }),
      languages: list(facets.languages).flatMap((entry) => {
        const item = record(entry);
        const key = str(item.key);
        return key ? [{ key, label: str(item.label) ?? key }] : [];
      }),
    },
  };
}

export function parseCallPage(body: unknown): CallPage {
  const raw = record(body);
  return {
    synthetic: raw.synthetic === true,
    total: num(raw.total),
    nextOffset: maybe(raw.next_offset),
    items: list(raw.items).map(callRow),
  };
}

/** Filters from the address (?range=&person=&team=&outcome=&language=). */
export function filtersFrom(
  params: Readonly<Record<string, string | string[] | undefined>>,
): Filters {
  const one = (name: string, limit = 160) => {
    const value = params[name];
    const text = Array.isArray(value) ? value[0] : value;
    return text && text.length <= limit ? text : null;
  };
  const range = one("range");
  const outcome = one("outcome");
  return {
    range: RANGES.some((item) => item.key === range)
      ? (range as RangeKey)
      : DEFAULT_FILTERS.range,
    person: one("person"),
    team: one("team"),
    outcome: OUTCOMES.some((item) => item.key === outcome)
      ? (outcome as OutcomeKey)
      : null,
    language: one("language", 32),
  };
}

/** The query string for these filters; the default range is left out. */
export function queryOf(filters: Filters, extra: Record<string, string> = {}) {
  const query = new URLSearchParams();
  if (filters.range !== DEFAULT_FILTERS.range)
    query.set("range", filters.range);
  for (const name of ["person", "team", "outcome", "language"] as const) {
    const value = filters[name];
    if (value) query.set(name, value);
  }
  for (const [name, value] of Object.entries(extra)) query.set(name, value);
  const text = query.toString();
  return text ? `?${text}` : "";
}

/** The page's address query: the filters, plus the view when not Overview. */
export const addressQuery = (filters: Filters, view: View) =>
  queryOf(filters, view === "overview" ? {} : { view });

export const activeFilterCount = (filters: Filters) =>
  [filters.person, filters.team, filters.outcome, filters.language].filter(
    Boolean,
  ).length;

/* ---------- Formatting ---------- */

const COUNT = new Intl.NumberFormat("en-IN");
const COMPACT = new Intl.NumberFormat("en-IN", {
  notation: "compact",
  maximumFractionDigits: 1,
});
export const count = (value: number) =>
  value >= 100_000 ? COMPACT.format(value) : COUNT.format(value);
export const percent = (share: number | null) =>
  share === null ? "—" : `${Math.round(share * 100)}%`;

export function rupees(value: number | null): string | null {
  if (value === null) return null;
  if (value >= 10_000_000) return `₹${(value / 10_000_000).toFixed(1)} Cr`;
  if (value >= 100_000) return `₹${(value / 100_000).toFixed(1)} L`;
  return `₹${COUNT.format(value)}`;
}

export function minutes(value: number): string {
  if (value < 60) return `${value} min`;
  const hours = value / 60;
  return hours >= 100
    ? `${count(Math.round(hours))} h`
    : `${hours.toFixed(1)} h`;
}

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});
const DAY_YEAR = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Asia/Kolkata",
});
const MONTH = new Intl.DateTimeFormat("en-IN", {
  month: "short",
  year: "2-digit",
  timeZone: "UTC",
});
const WEEK = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

export function dateLabel(iso: string | null, withYear = false): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return (withYear ? DAY_YEAR : DAY).format(date);
}

/** A trend bucket (an India-calendar date string) as its axis label. */
export function bucketLabel(at: string, unit: "week" | "month"): string {
  const date = new Date(`${at}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return at;
  return (unit === "month" ? MONTH : WEEK).format(date);
}

export function duration(ms: number | null): string {
  if (ms === null) return "—";
  const total = Math.round(ms / 1000);
  const minutesPart = Math.floor(total / 60);
  return minutesPart >= 60
    ? `${Math.floor(minutesPart / 60)} h ${minutesPart % 60} min`
    : `${minutesPart}:${String(total % 60).padStart(2, "0")}`;
}

/** Share of a group's skill moments that were observed (strong included). */
export function observedShare(cell: {
  observed: number;
  needsAttention: number;
}): number | null {
  const whole = cell.observed + cell.needsAttention;
  return whole ? cell.observed / whole : null;
}
