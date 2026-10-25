/**
 * The weekly friction report's data (owner, 25 Oct 2026: "automatically find where users
 * stop, which screen they get stuck on, where they try to tap, and why"), read from
 * /v1/admin/telemetry/friction. Counts, timings and code names only: no person, workspace
 * or call is named, and fewer than three people come as "<3".
 */
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
/** A count of people: a number, or "<3" when it could single someone out. */
export type People = number | "<3";
const people = (value: unknown): People =>
  value === "<3" ? "<3" : count(value);

export type FrictionFinding = {
  rank: number;
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
  peopleBefore: number | null;
  isNew: boolean;
  owner: string;
  question: string;
};
export type FlowStepRow = {
  step: string;
  label: string;
  reached: number;
  reachedShare: number | null;
  quit: number;
  blocked: number;
};
export type FlowSummary = {
  flow: string;
  label: string;
  started: number;
  people: People;
  done: number;
  skipped: number;
  cancelled: number;
  abandoned: number;
  noEnd: number;
  failed: number;
  doneShare: number | null;
  quitShare: number | null;
  doneP50: number | null;
  doneP90: number | null;
  steps: FlowStepRow[];
  worstStep: string | null;
};
export type PromptRow = {
  permission: string;
  label: string;
  asked: number;
  people: People;
  granted: number;
  denied: number;
  blocked: number;
  notOpened: number;
  grantedShare: number | null;
  answerP50: number | null;
  core: boolean;
};
export type ScreenRow = {
  screen: string;
  label: string;
  views: number;
  people: People;
  seenP50: number | null;
  seenP90: number | null;
  quickBackShare: number | null;
  exitShare: number | null;
  ragePer100: number | null;
  deadPer100: number | null;
  unresponsive: number;
  loops: number;
  frictionPer100: number | null;
};
export type Switching = {
  peopleInSeveral: People;
  switches: number;
  switchPeople: People;
  bounces: number;
  bouncePeople: People;
  pingPongPeople: People;
  earlySwitches: number;
  earlyPeople: People;
  directions: Array<[string, number]>;
  menuOpens: number;
  menuLeft: number;
};
export type Friction = {
  available: boolean;
  environment: string;
  week: string;
  since: string;
  until: string;
  complete: boolean;
  truncated: boolean;
  coverage: {
    events: number;
    people: People;
    visits: number;
    days: number;
    flowEvents: number;
    promptEvents: number;
    apps: Array<[string, number]>;
  };
  findings: FrictionFinding[];
  more: number;
  gone: Array<{ key: string; title: string; peopleBefore: number }>;
  flows: FlowSummary[];
  permissions: PromptRow[];
  workspaces: Switching;
  screens: ScreenRow[];
  loops: Array<{ labels: string[]; count: number; people: People }>;
};

const EVIDENCE_WORDS: Record<string, string> = {
  taps: "taps",
  element: "element",
  target: "on a",
  zones: "where on screen",
  views: "screen views",
  no_change: "taps with no change",
  share: "share",
  quick_backs: "quick backs",
  within_ms: "within",
  loops: "loops",
  started: "started",
  reached: "reached this step",
  stopped_here: "stopped here",
  finished: "finished",
  refused: "Save refused",
  asked: "asked",
  denied: "denied",
  blocked: "blocked",
  granted_share: "granted",
  bounces: "bounces",
  switches: "switches",
  ping_pong_people: "ping-pong people",
  early_switches: "switches within a minute",
  directions: "from → to",
  shown: "times shown",
};
const ZONE_WORDS: Record<string, string> = {
  r1: "top",
  r2: "upper middle",
  r3: "lower middle",
  r4: "bottom",
  c1: "left",
  c2: "centre",
  c3: "right",
};

/** "r1c3" as "top right". */
export const zoneWords = (zone: string): string => {
  const found = /^(r[1-4])(c[1-3])$/.exec(zone);
  return found ? `${ZONE_WORDS[found[1]]} ${ZONE_WORDS[found[2]]}` : zone;
};

function evidence(value: unknown): Array<[string, string]> {
  return Object.entries(object(value)).flatMap(([key, item]) => {
    if (item === null || item === undefined || item === "") return [];
    const label = EVIDENCE_WORDS[key] ?? key.replace(/_/g, " ");
    if (Array.isArray(item))
      return item.length
        ? [
            [
              label,
              item
                .map((part) =>
                  key === "zones" ? zoneWords(String(part)) : String(part),
                )
                .join(", "),
            ],
          ]
        : [];
    if (typeof item === "number")
      return [
        [
          label,
          key === "within_ms"
            ? `${Math.round(item / 1000)} s`
            : key.endsWith("share") && item <= 1
              ? `${Math.round(item * 100)}%`
              : String(item),
        ],
      ];
    if (typeof item === "object")
      return [
        [
          label,
          Object.entries(item as Json)
            .map(
              ([part, number]) => `${part.replace(/_/g, " ")} ${count(number)}`,
            )
            .join(", "),
        ],
      ];
    return [[label, String(item).slice(0, 80)]];
  }) as Array<[string, string]>;
}

const pairs = (value: unknown): Array<[string, number]> =>
  Object.entries(object(value)).map(([key, item]) => [key, count(item)]);

export function normalizeFriction(raw: unknown): Friction {
  const body = object(raw);
  const coverage = object(body.coverage);
  const switching = object(body.workspaces);
  return {
    available: body.schema === "ac.sales-xray.telemetry-friction/1",
    environment: text(body.environment),
    week: text(body.week),
    since: text(body.since),
    until: text(body.until),
    complete: body.complete === true,
    truncated: body.truncated === true,
    coverage: {
      events: count(coverage.events),
      people: people(coverage.people),
      visits: count(coverage.visits),
      days: count(coverage.days),
      flowEvents: count(coverage.flow_events),
      promptEvents: count(coverage.prompt_events),
      apps: pairs(coverage.apps),
    },
    findings: list(body.findings).map((item, index) => {
      const row = object(item);
      return {
        rank: count(row.rank) || index + 1,
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
        peopleBefore: maybe(row.people_before),
        isNew: row.new === true,
        owner: text(row.owner),
        question: text(row.question),
      };
    }),
    more: count(body.more),
    gone: list(body.gone).map((item) => {
      const row = object(item);
      return {
        key: text(row.key),
        title: text(row.title),
        peopleBefore: count(row.people_before),
      };
    }),
    flows: list(body.flows).map((item) => {
      const row = object(item);
      return {
        flow: text(row.flow),
        label: text(row.label),
        started: count(row.started),
        people: people(row.people),
        done: count(row.done),
        skipped: count(row.skipped),
        cancelled: count(row.cancelled),
        abandoned: count(row.abandoned),
        noEnd: count(row.no_end),
        failed: count(row.failed),
        doneShare: maybe(row.done_share),
        quitShare: maybe(row.quit_share),
        doneP50: maybe(row.done_p50_ms),
        doneP90: maybe(row.done_p90_ms),
        steps: list(row.steps).map((part) => {
          const step = object(part);
          return {
            step: text(step.step),
            label: text(step.label),
            reached: count(step.reached),
            reachedShare: maybe(step.reached_share),
            quit: count(step.quit),
            blocked: count(step.blocked),
          };
        }),
        worstStep: typeof row.worst_step === "string" ? row.worst_step : null,
      };
    }),
    permissions: list(body.permissions).map((item) => {
      const row = object(item);
      return {
        permission: text(row.permission),
        label: text(row.label),
        asked: count(row.asked),
        people: people(row.people),
        granted: count(row.granted),
        denied: count(row.denied),
        blocked: count(row.blocked),
        notOpened: count(row.not_opened),
        grantedShare: maybe(row.granted_share),
        answerP50: maybe(row.answer_p50_ms),
        core: row.core === true,
      };
    }),
    workspaces: {
      peopleInSeveral: people(switching.people_in_several),
      switches: count(switching.switches),
      switchPeople: people(switching.switch_people),
      bounces: count(switching.bounces),
      bouncePeople: people(switching.bounce_people),
      pingPongPeople: people(switching.ping_pong_people),
      earlySwitches: count(switching.early_switches),
      earlyPeople: people(switching.early_people),
      directions: pairs(switching.directions),
      menuOpens: count(switching.menu_opens),
      menuLeft: count(switching.menu_left),
    },
    screens: list(body.screens).map((item) => {
      const row = object(item);
      return {
        screen: text(row.screen),
        label: text(row.label),
        views: count(row.views),
        people: people(row.people),
        seenP50: maybe(row.seen_p50_ms),
        seenP90: maybe(row.seen_p90_ms),
        quickBackShare: maybe(row.quick_back_share),
        exitShare: maybe(row.exit_share),
        ragePer100: maybe(row.rage_per_100),
        deadPer100: maybe(row.dead_per_100),
        unresponsive: count(row.unresponsive),
        loops: count(row.loops),
        frictionPer100: maybe(row.friction_per_100),
      };
    }),
    loops: list(body.loops).map((item) => {
      const row = object(item);
      return {
        labels: list(row.labels).map((label) => text(label)),
        count: count(row.count),
        people: people(row.people),
      };
    }),
  };
}

const WEEK = /^\d{4}-\d{2}-\d{2}$/;

/** The week asked for (any day; the API takes its Monday), or the last full week. */
export function frictionQuery(params: { week?: string }): {
  week: string | null;
  path: string;
  markdown: string;
} {
  const week = params.week && WEEK.test(params.week) ? params.week : null;
  const query = week ? `?week=${week}` : "";
  return {
    week,
    path: `/v1/admin/telemetry/friction${query}`,
    markdown: `/v1/admin/telemetry/friction${query ? `${query}&` : "?"}format=markdown`,
  };
}

/** Mondays to offer: this week so far and the five before it, as YYYY-MM-DD (India). */
export function recentWeeks(now: Date, count = 6): string[] {
  const india = new Date(now.getTime() + 330 * 60_000);
  const day = (india.getUTCDay() + 6) % 7;
  const monday = Date.UTC(
    india.getUTCFullYear(),
    india.getUTCMonth(),
    india.getUTCDate() - day,
  );
  return Array.from({ length: count }, (_, index) =>
    new Date(monday - index * 7 * 86_400_000).toISOString().slice(0, 10),
  );
}

/** "19 Oct" from "2026-10-19". */
export const weekWords = (week: string): string => {
  if (!WEEK.test(week)) return week;
  const [year, month, day] = week.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
};

export const peopleWords = (value: People): string =>
  value === "<3"
    ? "fewer than 3 people"
    : `${value} ${value === 1 ? "person" : "people"}`;

export const DIRECTION_WORDS: Record<string, string> = {
  personal_to_organisation: "Personal → an organisation",
  organisation_to_personal: "An organisation → Personal",
  organisation_to_organisation: "Organisation → another",
  operations_to_organisation: "Operations → an organisation",
  organisation_to_operations: "An organisation → Operations",
  workspace_to_workspace: "Workspace → another",
};
