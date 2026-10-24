/**
 * Admin → Sellers → What happened (owner, 24 Oct 2026: "finding out what went
 * wrong for a seller is too hard"): the normalizers and words for
 * GET /v1/admin/sellers?email= and GET /v1/admin/sellers/{id}/timeline.
 * Counts, times and states only. Pure.
 */
import { read } from "../lib/read";

// The default first: QueryTabs gives the first tab no parameter.
export const DAYS = ["14", "7", "30"] as const;
export type Days = (typeof DAYS)[number];
export const DAY_WORDS: Record<Days, string> = {
  "7": "7 days",
  "14": "14 days",
  "30": "30 days",
};
export const daysFrom = (value: string | undefined): Days =>
  DAYS.find((days) => days === value) ?? "14";

export const sellerPath = (personId: string) => `/sellers/${personId}`;

export type Tone = "good" | "warn" | "bad" | "neutral";
export type Flag = { tone: "bad" | "warn"; words: string };
export type Moment = { at: string; time: string; words: string };
export type ServerDay = {
  callsApp: number;
  callsLogged: number;
  connected: number;
  testCalls: number;
  results: number;
  notes: number;
  stageMoves: number;
};
export type PhoneDay = {
  callsStarted: number;
  resultsSaved: number;
  stageMovesSaved: number;
  waiting: number;
  refused: number;
  oldestWaitingMin: number;
  errors: number;
  errorCodes: string[];
  scriptErrors: number;
  slowTaps: number;
  slowRequests: number;
  slowScreens: string[];
  crashes: number;
};
export type Day = {
  day: string;
  label: string;
  server: ServerDay;
  phone: PhoneDay | null;
  signIns: number;
  signOuts: number;
  workspaces: string[];
  versions: string[];
  installs: string[];
  flags: Flag[];
  moments: Moment[];
};
export type Workspace = {
  id: string;
  name: string;
  kind: string;
  role: string;
  status: string;
  joinedAt: string | null;
  endedAt: string | null;
  analytics: "on" | "off" | "sandbox";
  signIns: number;
  lastOpenedAt: string | null;
};
export type Device = {
  app: string;
  device: string;
  version: string | null;
  versions: string[];
  model: string | null;
  maker: string | null;
  store: string | null;
  android: number | null;
  lastSeenAt: string | null;
};
export type PhoneEntry = {
  workspace: string | null;
  install: string | null;
  appVersion: string | null;
  family: string | null;
  reportedAt: string | null;
  syncedAt: string | null;
};
export type Install = {
  install: string;
  firstCallAt: string | null;
  lastCallAt: string | null;
  calls: number;
};
export type Timeline = {
  person: {
    id: string;
    name: string | null;
    email: string | null;
    status: string;
    createdAt: string | null;
  };
  days: Days;
  summary: { tone: Tone; words: string };
  totals: {
    callsApp: number;
    callsLogged: number;
    results: number;
    notes: number;
    stageMoves: number;
    resultsSaved: number;
    stageMovesSaved: number;
    crashes: number;
    errors: number;
    daysWithGaps: number;
  };
  workspaces: Workspace[];
  devices: Device[];
  phones: PhoneEntry[];
  installs: Install[];
  consent: { termsVersion: string | null; termsAt: string | null };
  timeline: Day[];
  truncated: string[];
};

const TONES: readonly Tone[] = ["good", "warn", "bad", "neutral"];
const count = (value: unknown) => read.number(value);

function normalizeDay(raw: unknown): Day {
  const row = read.object(raw);
  const server = read.object(row.server);
  const phone = row.phone === null ? null : read.object(row.phone);
  return {
    day: read.string(row.day),
    label: read.string(row.label, read.string(row.day)),
    server: {
      callsApp: count(server.calls_app),
      callsLogged: count(server.calls_logged),
      connected: count(server.connected),
      testCalls: count(server.test_calls),
      results: count(server.results),
      notes: count(server.notes),
      stageMoves: count(server.stage_moves),
    },
    phone: phone
      ? {
          callsStarted: count(phone.calls_started),
          resultsSaved: count(phone.results_saved),
          stageMovesSaved: count(phone.stage_moves_saved),
          waiting: count(phone.waiting),
          refused: count(phone.refused),
          oldestWaitingMin: count(phone.oldest_waiting_min),
          errors: count(phone.errors),
          errorCodes: read.strings(phone.error_codes),
          scriptErrors: count(phone.script_errors),
          slowTaps: count(phone.slow_taps),
          slowRequests: count(phone.slow_requests),
          slowScreens: read.strings(phone.slow_screens),
          crashes: count(phone.crashes),
        }
      : null,
    signIns: count(row.sign_ins),
    signOuts: count(row.sign_outs),
    workspaces: read.strings(row.workspaces),
    versions: read.strings(row.versions),
    installs: read.strings(row.installs),
    flags: read.array(row.flags).map((item) => {
      const flag = read.object(item);
      return {
        tone: flag.tone === "bad" ? "bad" : "warn",
        words: read.string(flag.words),
      };
    }),
    moments: read.array(row.moments).map((item) => {
      const moment = read.object(item);
      return {
        at: read.string(moment.at),
        time: read.string(moment.time),
        words: read.string(moment.words),
      };
    }),
  };
}

export function normalizeTimeline(raw: unknown): Timeline {
  const body = read.object(raw);
  const person = read.object(body.person);
  const window = read.object(body.window);
  const summary = read.object(body.summary);
  const totals = read.object(body.totals);
  const consent = read.object(body.consent);
  const tone = TONES.find((item) => item === summary.tone) ?? "neutral";
  return {
    person: {
      id: read.string(person.id),
      name: read.optionalString(person.name),
      email: read.optionalString(person.email),
      status: read.string(person.status, "active"),
      createdAt: read.optionalString(person.created_at),
    },
    days: daysFrom(String(read.number(window.days, 14))),
    summary: { tone, words: read.string(summary.words) },
    totals: {
      callsApp: count(totals.calls_app),
      callsLogged: count(totals.calls_logged),
      results: count(totals.results),
      notes: count(totals.notes),
      stageMoves: count(totals.stage_moves),
      resultsSaved: count(totals.results_saved),
      stageMovesSaved: count(totals.stage_moves_saved),
      crashes: count(totals.crashes),
      errors: count(totals.errors),
      daysWithGaps: count(totals.days_with_gaps),
    },
    workspaces: read.array(body.workspaces).map((item) => {
      const row = read.object(item);
      const analytics =
        row.analytics === "off" || row.analytics === "sandbox"
          ? row.analytics
          : "on";
      return {
        id: read.string(row.id),
        name: read.string(row.name, "Workspace"),
        kind: read.string(row.kind, "other"),
        role: read.string(row.role),
        status: read.string(row.status),
        joinedAt: read.optionalString(row.joined_at),
        endedAt: read.optionalString(row.ended_at),
        analytics,
        signIns: count(row.sign_ins),
        lastOpenedAt: read.optionalString(row.last_opened_at),
      };
    }),
    devices: read.array(body.devices).map((item) => {
      const row = read.object(item);
      return {
        app: read.string(row.app, "web"),
        device: read.string(row.device, "unknown"),
        version: read.optionalString(row.version),
        versions: read.strings(row.versions),
        model: read.optionalString(row.model),
        maker: read.optionalString(row.maker),
        store: read.optionalString(row.store),
        android: read.optionalNumber(row.android),
        lastSeenAt: read.optionalString(row.last_seen_at),
      };
    }),
    phones: read.array(body.phones).map((item) => {
      const row = read.object(item);
      return {
        workspace: read.optionalString(row.workspace),
        install: read.optionalString(row.install),
        appVersion: read.optionalString(row.app_version),
        family: read.optionalString(row.family),
        reportedAt: read.optionalString(row.reported_at),
        syncedAt: read.optionalString(row.synced_at),
      };
    }),
    installs: read.array(body.installs).map((item) => {
      const row = read.object(item);
      return {
        install: read.string(row.install),
        firstCallAt: read.optionalString(row.first_call_at),
        lastCallAt: read.optionalString(row.last_call_at),
        calls: count(row.calls),
      };
    }),
    consent: {
      termsVersion: read.optionalString(consent.terms_version),
      termsAt: read.optionalString(consent.terms_at),
    },
    timeline: read.array(body.days).map(normalizeDay),
    truncated: read.strings(body.truncated),
  };
}

/** The person an email lookup found, or null. */
export function normalizeFound(
  raw: unknown,
): { id: string; name: string | null; email: string | null } | null {
  const person = read.object(read.object(raw).person);
  const id = read.optionalString(person.id);
  return id
    ? {
        id,
        name: read.optionalString(person.name),
        email: read.optionalString(person.email),
      }
    : null;
}

export const KIND_WORDS: Record<string, string> = {
  personal: "Personal",
  organisation: "Organisation",
  sandbox: "Sandbox",
  operations: "AC operations",
  other: "Workspace",
};

export const ANALYTICS_WORDS: Record<Workspace["analytics"], string> = {
  on: "Usage analytics on",
  off: "Usage analytics off",
  sandbox: "Sandbox: never recorded",
};

const plural = (value: number, one: string, many = `${one}s`) =>
  `${value.toLocaleString("en-IN")} ${value === 1 ? one : many}`;

/** "Android app · phone" or "Browser · desktop". */
export const deviceName = (device: Device) =>
  `${device.app === "android" ? "Android app" : "Browser"} · ${device.device}`;

/** What reached the server that day, in one line. */
export function serverLine(server: ServerDay): string {
  const parts = [
    plural(server.callsApp, "call") + " placed in the app",
    plural(server.callsLogged, "call") +
      " logged by the phone" +
      (server.callsLogged ? ` (${server.connected} connected)` : ""),
    plural(server.results, "result"),
    plural(server.notes, "note"),
    plural(server.stageMoves, "stage move"),
  ];
  if (server.testCalls) parts.push(plural(server.testCalls, "test call"));
  return parts.join(" · ");
}

/** What the phone reported doing that day, in one line. */
export function phoneLine(phone: PhoneDay | null): string {
  if (!phone) return "No usage data from the phone";
  const parts = [
    plural(phone.callsStarted, "call") + " started",
    plural(phone.resultsSaved, "result") + " saved",
    plural(phone.stageMovesSaved, "stage move") + " saved",
  ];
  if (phone.waiting) parts.push(`${phone.waiting} waiting to send`);
  if (phone.refused) parts.push(`${phone.refused} refused`);
  if (phone.errors) parts.push(plural(phone.errors, "error") + " shown");
  if (phone.scriptErrors)
    parts.push(plural(phone.scriptErrors, "script error"));
  if (phone.slowTaps) parts.push(plural(phone.slowTaps, "slow tap"));
  if (phone.slowRequests)
    parts.push(plural(phone.slowRequests, "slow or failed request"));
  if (phone.slowScreens.length)
    parts.push(`slow to load: ${phone.slowScreens.join(", ")}`);
  if (phone.crashes) parts.push(plural(phone.crashes, "crash", "crashes"));
  return parts.join(" · ");
}

/** The window's totals, in one line under the summary. */
export function totalsLine(timeline: Timeline): string {
  const { totals } = timeline;
  return [
    `In ${DAY_WORDS[timeline.days]}: ${plural(totals.callsApp, "call")} placed in the app`,
    `${plural(totals.callsLogged, "call")} logged by the phone`,
    plural(totals.results, "result"),
    plural(totals.notes, "note"),
    plural(totals.stageMoves, "stage move"),
    plural(totals.daysWithGaps, "day") + " with gaps",
  ].join(" · ");
}
