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
 *   server rejects anything else.
 * - Fail closed and stay quiet: the server publishes the events it accepts
 *   (GET /v1/telemetry/taxonomy); events it does not list are dropped here,
 *   and a refused batch (no consent policy, no retention policy) switches
 *   telemetry off for the page. A failure never reaches the person.
 */

export const TELEMETRY_SCHEMA = "telemetry/1";

type Empty = Record<string, never>;

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
  "sx.report_opened": { view: ReportView };
  "sx.pillar_read": { pillar: string; read_ms: number };
  "sx.coaching_opened": { scope: "call" | "mine" | "team" };
  "sx.clip_played": { kind: "preview" | "full" };
  "sx.paywall_seen": { surface: string };
  "sx.paywall_clicked": { surface: string; action: string };
  "sx.mission_started": Empty;
  "sx.mission_completed": Empty;
  "sx.prospect_edited": { field: string };
  "sx.outcome_set": { outcome: string };
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
  "sx.pillar_read",
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
export type ReportView = "report" | "coaching" | "transcript" | "document";

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
  route: null;
  payload: Record<string, string | number | boolean>;
};

const BATCH = 20;
const DELAY_MS = 2_000;

type Sender = Readonly<{
  fetch: typeof fetch;
  now: () => Date;
  id: () => string;
}>;

/**
 * One page's telemetry: a queue, the session it belongs to, and the
 * server's list of accepted events (read once).
 */
export class TelemetryClient {
  private queue: Queued[] = [];
  private session: string | null = null;
  private accepted: Promise<Set<string> | null> | null = null;
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
    const values = payload as Record<string, string | number | boolean>;
    if (!safePayload(values)) return;
    this.queue.push({
      event_id: this.sender.id(),
      event_name: name,
      event_version: "1.0",
      occurred_at: this.sender.now().toISOString(),
      session_id: this.session,
      route: null,
      payload: { ...values },
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
      .catch(() => null);
    return this.accepted;
  }

  /** Send what is queued for the current session; `keepalive` on page exit. */
  async flush(keepalive = false) {
    if (this.off || !this.session || !this.queue.length) return;
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

/** The page's client (off on the server and under test). */
export const telemetry = new TelemetryClient(
  {
    fetch: (input, init) => fetch(input, init),
    now: () => new Date(),
    id: () =>
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : "00000000-0000-4000-8000-000000000000",
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
