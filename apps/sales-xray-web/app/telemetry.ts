/**
 * Sales Xray product telemetry, schema telemetry/1 (owner, 11 Oct 04:50 IST).
 *
 * Typed events for what people do (sign in, upload, open a report, play a
 * clip…), sent in small batches to the platform's analytics path,
 * POST /v1/telemetry/events. Rules:
 * - Analytics only. Nothing here is, or becomes, progress, completion,
 *   payment, access or scoring state (AGENTS.md); the server stores these as
 *   disposable, consented analytics.
 * - No call content and nothing personal: no names, emails, transcripts,
 *   call titles, ids or free text. Payloads are short enums and numbers; the
 *   server rejects anything else. A report event's call goes in its own
 *   `call_id` field, never the payload; the server keeps only a keyed hash.
 * - Each event also says the page (its route template, ids left out), the
 *   device class and web or the Android app (owner, 22 Oct 2026: optimise on
 *   how people use the app).
 * - Fail closed and stay quiet: the server publishes the events it accepts
 *   (GET /v1/telemetry/taxonomy); events it does not list are dropped here,
 *   and a refused batch (no consent policy, no retention policy) switches
 *   telemetry off for the page. A failure never reaches the person.
 */

import { IN_APP_ATTRIBUTE } from "./in-app";

export const TELEMETRY_SCHEMA = "telemetry/1";

type Empty = Record<string, never>;

/** The Report's parts as xray-report/panels.tsx names them, and the call's other tabs. */
export type TelemetrySection =
  | "overview"
  | "analysis"
  | "outcome"
  | "prospect-information"
  | "coaching"
  | "transcript";

/** Brain 4.0's 18 skills, lower case ("D07" is sent as "d07"). */
export const SKILL_KEYS = [
  "d01",
  "d02",
  "d03",
  "d04",
  "d05",
  "d06",
  "d07",
  "d08",
  "d09",
  "d10",
  "d11",
  "d12",
  "d13",
  "d14",
  "d15",
  "d16",
  "d17",
  "d18",
] as const;
export type SkillKey = (typeof SKILL_KEYS)[number];

/** Which Report the call showed: the Brain 4.0 coaching score or the pointers. */
export type ReportLookName = "brain4" | "pointers";
export type ReadBand = "under_5s" | "5_30s" | "30_120s" | "over_120s";
export type SectionAction =
  | "expand"
  | "collapse"
  | "copy"
  | "clip"
  | "helpful"
  | "not_helpful";
/** The call's AI-on-calls level when the person tapped. */
export type AiLevel = "off" | "data_only" | "auto" | "full";
export type CallSurface = "call" | "report" | "lead" | "calls";
export type ReportSource =
  | "calls"
  | "lead"
  | "prospect"
  | "notification"
  | "link"
  | "upload"
  | "other";

/** The call a report event is about (its report's id); sent apart from the payload. */
type AboutCall = { call_id: string };

/** Every event and its payload. Add here first; the server lists what it takes. */
export type TelemetryEvents = {
  "sx.sign_in": { method: "password" | "email_code" | "google" };
  "sx.sign_out": Empty;
  "sx.upload_started": { size_band: SizeBand; format: AudioFormat };
  "sx.upload_finished": {
    outcome: "saved" | "interrupted" | "cancelled";
    seconds: number;
  };
  "sx.analysis_seen_done": { wait_band: WaitBand };
  "sx.report_opened": AboutCall & {
    view: ReportView;
    /** brief: the one-pass read; full: the full report. */
    level?: "brief" | "full";
    source?: ReportSource;
  };
  /** One section read; useSectionDwell (telemetry-dwell.ts) sends it. */
  "sx.section_read": AboutCall & {
    section: TelemetrySection;
    skill?: SkillKey;
    look?: ReportLookName;
    read_band: ReadBand;
    dwell_ms?: number;
  };
  "sx.section_action": AboutCall & {
    section: TelemetrySection;
    skill?: SkillKey;
    action: SectionAction;
  };
  "sx.on_demand_requested": AboutCall & {
    section: TelemetrySection;
    level: AiLevel;
  };
  /** "Get full report" for the whole call. */
  "sx.full_report_requested": AboutCall & {
    surface: CallSurface;
    level?: AiLevel;
  };
  "sx.reanalyse_requested": AboutCall & { surface: CallSurface };
  "sx.coaching_opened": { scope: "call" | "mine" | "team" };
  "sx.clip_played": { kind: "preview" | "full" };
  "sx.paywall_seen": { surface: string };
  "sx.paywall_clicked": { surface: string; action: string };
  "sx.mission_started": Empty;
  "sx.mission_completed": Empty;
  "sx.prospect_edited": { field: string };
  "sx.outcome_set": Partial<AboutCall> & { outcome: string };
  "sx.error_shown": { surface: string; code: string };
};

export type TelemetryEventName = keyof TelemetryEvents;

/** The event names, for the dashboards (Strike G) and the server taxonomy. */
export const TELEMETRY_EVENT_NAMES = [
  "sx.sign_in",
  "sx.sign_out",
  "sx.upload_started",
  "sx.upload_finished",
  "sx.analysis_seen_done",
  "sx.report_opened",
  "sx.section_read",
  "sx.section_action",
  "sx.on_demand_requested",
  "sx.full_report_requested",
  "sx.reanalyse_requested",
  "sx.coaching_opened",
  "sx.clip_played",
  "sx.paywall_seen",
  "sx.paywall_clicked",
  "sx.mission_started",
  "sx.mission_completed",
  "sx.prospect_edited",
  "sx.outcome_set",
  "sx.error_shown",
] as const satisfies readonly TelemetryEventName[];

export type SizeBand = "under_5mb" | "5_to_20mb" | "over_20mb";
export type AudioFormat = "mp3" | "wav" | "m4a" | "ogg" | "flac" | "other";
export type WaitBand =
  | "under_2m"
  | "2_to_5m"
  | "5_to_15m"
  | "over_15m"
  | "unknown";
export type ReportView =
  | "report"
  | "coaching"
  | "transcript"
  | "document"
  | "share";
export type DeviceClass = "phone" | "tablet" | "desktop";
export type AppKind = "web" | "android";

export const sizeBand = (bytes: number): SizeBand =>
  bytes < 5 * 1024 ** 2
    ? "under_5mb"
    : bytes <= 20 * 1024 ** 2
      ? "5_to_20mb"
      : "over_20mb";

export const audioFormat = (fileName: string): AudioFormat => {
  const extension = /\.([a-z0-9]+)$/i.exec(fileName)?.[1]?.toLowerCase();
  return extension === "mp3" ||
    extension === "wav" ||
    extension === "m4a" ||
    extension === "ogg" ||
    extension === "flac"
    ? extension
    : extension === "mpeg"
      ? "mp3"
      : "other";
};

export const waitBand = (milliseconds: number): WaitBand =>
  !Number.isFinite(milliseconds) || milliseconds < 0
    ? "unknown"
    : milliseconds < 120_000
      ? "under_2m"
      : milliseconds < 300_000
        ? "2_to_5m"
        : milliseconds < 900_000
          ? "5_to_15m"
          : "over_15m";

/** How long a section was read, in the bands the cost optimiser reads. */
export const readBand = (milliseconds: number): ReadBand =>
  milliseconds < 5_000
    ? "under_5s"
    : milliseconds < 30_000
      ? "5_30s"
      : milliseconds < 120_000
        ? "30_120s"
        : "over_120s";

/** Phone, tablet or computer, by the window's width in CSS pixels. */
export const deviceClass = (width: number): DeviceClass =>
  width < 600 ? "phone" : width < 1024 ? "tablet" : "desktop";

/** The server's route templates (ingest.py): ids become their names in brackets. */
const STATIC_ROUTES = new Set([
  "/",
  "/dashboard",
  "/analysis",
  "/analysis/new",
  "/analysis/calls",
  "/calls",
  "/leads",
  "/chats",
  "/coaching",
  "/prospects",
  "/organisation",
  "/organisation/insights",
  "/organisation/invites",
  "/settings",
  "/account",
  "/account/billing",
  "/billing",
  "/plans",
  "/apps",
  "/developers",
  "/review",
]);
const ROUTE_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/^\/analysis\/calls\/[^/]+$/, "/analysis/calls/[callId]"],
  [/^\/prospects\/[^/]+$/, "/prospects/[prospectId]"],
  [/^\/organisation\/people\/[^/]+$/, "/organisation/people/[personId]"],
  [/^\/settings\/[^/]+$/, "/settings/[section]"],
];

/** The page's route template, or null for a page the server does not list. */
export function routeTemplate(pathname: string): string | null {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  if (STATIC_ROUTES.has(path)) return path;
  return ROUTE_PATTERNS.find(([pattern]) => pattern.test(path))?.[1] ?? null;
}

const CALL_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** Payload keys and values the server accepts (and nothing that could carry a person). */
const KEY = /^[a-z][a-z0-9_]{0,48}$/;
const PERSONAL_KEY =
  /email|e[-_ ]?mail|phone|mobile|address|name|transcript|audio|recording|token|secret|password|ip|device.?id|cookie|prompt|answer|message|url/i;
const VALUE = /^[a-z0-9_.-]{0,64}$/;

/** True when a payload is short enums and finite numbers only. */
export function safePayload(payload: Record<string, unknown>): boolean {
  const entries = Object.entries(payload);
  if (entries.length > 8) return false;
  return entries.every(
    ([key, value]) =>
      KEY.test(key) &&
      !PERSONAL_KEY.test(key) &&
      ((typeof value === "number" &&
        Number.isFinite(value) &&
        Math.abs(value) < 1e9) ||
        typeof value === "boolean" ||
        (typeof value === "string" && VALUE.test(value))),
  );
}

type Queued = {
  event_id: string;
  event_name: string;
  event_version: "1.0";
  occurred_at: string;
  session_id: string | null;
  route: string | null;
  payload: Record<string, string | number | boolean>;
  call_id?: string;
};

const BATCH = 20;
const DELAY_MS = 2_000;

/** Where an event happened: the page's template, the device class and the app. */
export type EventContext = Readonly<{
  route: string | null;
  device: DeviceClass;
  app: AppKind;
}>;

type Sender = Readonly<{
  fetch: typeof fetch;
  now: () => Date;
  id: () => string;
  /** Read at each event; absent under test (no route, device or app). */
  context?: () => EventContext;
}>;

/**
 * One page's telemetry: a queue, the session it belongs to, and the
 * server's list of accepted events (read once).
 */
export class TelemetryClient {
  private queue: Queued[] = [];
  private session: string | null = null;
  private accepted: Promise<Set<string> | null> | null = null;
  /** The server's list once read (undefined until the read has ended). */
  private known: Set<string> | null | undefined = undefined;
  private off = false;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private seen = new Set<string>();

  constructor(
    private readonly sender: Sender,
    private readonly enabled: boolean,
  ) {}

  /** The signed-in AC session (events carry it; the server checks it). */
  setSession(sessionId: string | null) {
    if (sessionId !== this.session) {
      // Events from another session are never sent under this one.
      this.queue = this.queue.filter(
        (event) => event.session_id === null || event.session_id === sessionId,
      );
      for (const event of this.queue) event.session_id = sessionId;
    }
    this.session = sessionId;
    if (sessionId && this.queue.length) this.schedule();
  }

  track<N extends TelemetryEventName>(name: N, payload: TelemetryEvents[N]) {
    if (!this.enabled || this.off) return;
    // The call travels in its own field; the server swaps it for a keyed hash.
    const { call_id: callId, ...rest } = payload as Record<
      string,
      string | number | boolean | undefined
    >;
    const context = this.sender.context?.();
    const values: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(rest))
      if (value !== undefined) values[key] = value;
    if (context) {
      values.device = context.device;
      values.app = context.app;
    }
    if (!safePayload(values)) return;
    this.queue.push({
      event_id: this.sender.id(),
      event_name: name,
      event_version: "1.0",
      occurred_at: this.sender.now().toISOString(),
      session_id: this.session,
      route: context?.route ?? null,
      payload: values,
      ...(typeof callId === "string" && CALL_ID.test(callId)
        ? { call_id: callId.toLowerCase() }
        : {}),
    });
    if (this.queue.length > 200) this.queue.splice(0, this.queue.length - 200);
    this.schedule(this.queue.length >= BATCH ? 0 : DELAY_MS);
  }

  /** Once per page load for a key (a report opened, a paywall seen). */
  trackOnce<N extends TelemetryEventName>(
    key: string,
    name: N,
    payload: TelemetryEvents[N],
  ) {
    if (this.seen.has(key)) return;
    this.seen.add(key);
    this.track(name, payload);
  }

  private schedule(delay = DELAY_MS) {
    if (this.timer !== null || !this.session) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.flush();
    }, delay);
  }

  /** The events the server takes, or null (none: telemetry stays off). */
  private taxonomy() {
    this.accepted ??= this.sender
      .fetch("/v1/telemetry/taxonomy", {
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: { accept: "application/json" },
      })
      .then(async (response) => {
        if (!response.ok) return null;
        const body: unknown = await response.json();
        const events =
          body && typeof body === "object" && "events" in body
            ? (body as { events: unknown }).events
            : null;
        if (!Array.isArray(events)) return null;
        return new Set(
          events
            .map((item: unknown) =>
              item && typeof item === "object" && "event_name" in item
                ? String((item as { event_name: unknown }).event_name)
                : "",
            )
            .filter(Boolean),
        );
      })
      .catch(() => null)
      .then((events) => {
        this.known = events;
        return events;
      });
    return this.accepted;
  }

  /** Send what is queued for the current session; `keepalive` on page exit. */
  async flush(keepalive = false) {
    if (this.off || !this.session || !this.queue.length) return;
    // Leaving the page starts no read (the browser would cancel it): events
    // go out on exit only once the server's list is known.
    if (keepalive && this.known === undefined) return;
    const accepted = await this.taxonomy();
    if (!accepted) {
      this.off = true;
      this.queue = [];
      return;
    }
    const batch = this.queue
      .splice(0, BATCH)
      .filter(
        (event) =>
          event.session_id === this.session && accepted.has(event.event_name),
      );
    if (!batch.length) return;
    try {
      const response = await this.sender.fetch("/v1/telemetry/events", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        keepalive,
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({ events: batch }),
      });
      // Refused (no consent or retention policy yet, not signed in, a schema
      // the server does not take): stop for this page, quietly.
      if (!response.ok && response.status !== 429) {
        this.off = true;
        this.queue = [];
      }
    } catch {
      // Offline: these events are not worth a retry storm; drop them.
    }
    if (this.queue.length) this.schedule();
  }
}

const browser = typeof window !== "undefined";

/** This page: its route template, the window's device class, web or the app. */
function browserContext(): EventContext {
  return {
    route: routeTemplate(window.location.pathname),
    device: deviceClass(window.innerWidth),
    app: document.documentElement.hasAttribute(IN_APP_ATTRIBUTE)
      ? "android"
      : "web",
  };
}

/** The page's client (off on the server and under test). */
export const telemetry = new TelemetryClient(
  {
    fetch: (input, init) => fetch(input, init),
    now: () => new Date(),
    id: () =>
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : "00000000-0000-4000-8000-000000000000",
    context: browserContext,
  },
  browser && process.env.NODE_ENV !== "test",
);

if (browser)
  window.addEventListener("pagehide", () => void telemetry.flush(true));

export const track = <N extends TelemetryEventName>(
  name: N,
  payload: TelemetryEvents[N],
) => telemetry.track(name, payload);

export const trackOnce = <N extends TelemetryEventName>(
  key: string,
  name: N,
  payload: TelemetryEvents[N],
) => telemetry.trackOnce(key, name, payload);
