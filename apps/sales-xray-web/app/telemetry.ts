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

/** How someone signed in: a password, an email code or a provider. */
export type SignInMethod =
  | "password"
  | "email_code"
  | "google"
  | "apple"
  | "facebook"
  | "pulse";

/** Every event and its payload. Add here first; the server lists what it takes. */
export type TelemetryEvents = {
  "sx.sign_in": { method: SignInMethod };
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
  // Performance and usage (owner, 24 Oct 2026); telemetry-auto.tsx sends these.
  "sx.screen_viewed": {
    screen: Screen;
    from?: Screen | "none";
    nav: "first" | "push" | "back" | "reload";
    stay_ms?: number;
    /** How long the screen before was on view (a call in the dialer doesn't count). */
    seen_ms?: number;
  };
  /** The page went to the background or closed: the screen and how long it was seen. */
  "sx.screen_hidden": {
    screen: Screen;
    kind: "background" | "exit";
    seen_ms?: number;
  };
  /** Tap to the screen settling, and the browser's own input-to-paint time. */
  "sx.action_timing": {
    action: TimedAction;
    ms: number;
    result: "settled" | "timeout" | "no_change";
    paint_ms?: number;
    screen?: Screen;
  };
  "sx.web_vital": {
    metric: "lcp" | "inp" | "cls" | "fcp" | "ttfb";
    value: number;
    rating?: "good" | "needs_improvement" | "poor";
    screen?: Screen;
  };
  "sx.app_start": {
    start: "cold" | "warm";
    ms: number;
    nav_type?: "navigate" | "reload" | "back_forward" | "prerender";
    screen?: Screen;
    /** The CPU test (cpuMs), and the phone's model on Android ("redmi-note-8-pro"). */
    cpu_ms?: number;
    model_label?: string;
  };
  /** Never the message: its class and a fingerprint of where it was thrown. */
  "sx.js_error": {
    kind: "error" | "rejection" | "react" | "chunk";
    error: ErrorClass;
    where?: string;
    source?: "app" | "vendor" | "extension" | "unknown";
    screen?: Screen;
  };
  "sx.api_slow": {
    endpoint: string;
    status: "2xx" | "3xx" | "4xx" | "5xx" | "network" | "unknown";
    ms: number;
    /** To the answer's first byte: the server's part, without the download. */
    wait_ms?: number;
    screen?: Screen;
  };
  "sx.tap_issue": {
    kind: "rage" | "dead";
    target: TapTarget;
    action?: TimedAction;
    screen?: Screen;
    /** Where on the screen: the viewport in 4 rows of 3 ("r1c1" to "r4c3"). */
    zone?: TapZone;
    /** The element as the code names it, never its words (telemetry-auto elementOf). */
    element?: string;
    /** A fingerprint of its place on the page. */
    where?: string;
  };
  "sx.feature_used": { feature: string; screen?: Screen };
  /** Shake to report: opened, or a near miss (two swings, not three); the
   * strongest swing in m/s² and the swings, to tune from real phones. */
  "sx.shake": { outcome: "opened" | "near"; peak: number; swings: number };
  /** Calling a lead (27 Oct 2026, leads/phone-call-steps.ts): a real call
   * start, a touch a glide would have lost, a touch on Call that placed no
   * call, and the phone app's hand-off steps. Codes and ms only. */
  "sx.phone_call": {
    step:
      | "started"
      | "rescued"
      | "touch_no_call"
      | "status"
      | "permits"
      | "bridge_ok"
      | "bridge_error"
      | "fallback_tel";
    via?: "touch" | "click";
    why?: "drag" | "moved" | "long" | "timeout" | "error";
    mode?: "dialer" | "direct" | "browser";
    ms?: number;
    screen?: Screen;
  };
  // Lead OS (24 Oct 2026): the pipeline board, stage sheet and lead sheet.
  /** One stage move; wait is from opening the stage sheet to Save. */
  "sx.lead_stage_moved": {
    via: "board" | "sheet" | "after_call" | "table" | "bulk" | "meeting";
    source?: "seller" | "ai_suggestion";
    from_kind?: LeadKind;
    to_kind: LeadKind;
    /** Required fields the move asked for, 0 to 4. */
    needs?: number;
    wait?: WaitBand;
    wait_ms?: number;
  };
  "sx.board_drag": { result: "moved" | "sheet" | "refused" | "undone" };
  /** From opening a lead to its first call, message or move. */
  "sx.lead_open_to_action": {
    wait: WaitBand;
    first?: "call" | "message" | "move";
    wait_ms?: number;
  };
  // The Android app's own signals (app 1.0.26): it collects them, the page sends
  // them (telemetry-auto.tsx drains the phone channel) under the same switch.
  "sx.app_launch": {
    start: "cold" | "warm";
    ms: number;
    pages?: "app" | "live";
  };
  "sx.app_frames": {
    frames: number;
    slow?: number;
    frozen?: number;
    p90_ms?: number;
  };
  "sx.app_exit": {
    reason:
      | "anr"
      | "crash"
      | "crash_native"
      | "low_memory"
      | "excessive_resource"
      | "killed_by_system"
      | "other";
    foreground?: "yes" | "no";
  };
  "sx.device_profile": {
    android?: number;
    maker?: string;
    model_label?: string;
    webview?: string;
    ram_tier?: "2" | "3" | "4" | "6" | "8" | "12plus";
    memory_class?: number;
    low_ram?: "yes" | "no";
    storage_free?: "lt1" | "1to4" | "4to16" | "16plus";
    app_version?: string;
    store?: "direct" | "play";
  };
  "sx.device_state": {
    battery_saver?: "yes" | "no";
    battery_unrestricted?: "yes" | "no";
    standby_bucket?:
      | "exempted"
      | "active"
      | "working_set"
      | "frequent"
      | "rare"
      | "restricted"
      | "unknown";
    notifications?: "on" | "off";
  };
  "sx.network_state": {
    transport?: "wifi" | "cellular" | "ethernet" | "vpn" | "other" | "none";
    metered?: "yes" | "no";
    validated?: "yes" | "no";
    down_tier?: "unknown" | "lt1" | "1to5" | "5to20" | "20plus";
    cell_gen?: "2g" | "3g" | "4g" | "5g" | "unknown";
  };
  "sx.permission_snapshot": Partial<
    Record<
      | "calls"
      | "rec_files"
      | "notifications"
      | "mic"
      | "all_files"
      | "folder"
      | "call_log",
      "granted" | "denied" | "not_in_build"
    >
  >;
  "sx.lead_suggestion": {
    action: "shown" | "accepted" | "changed" | "dismissed";
    from?: "call" | "chat" | "rule";
  };
  /** Changes this device holds unsent (sync/write-queue.ts): counts only. */
  "sx.writes_waiting": { waiting: number; refused: number; oldest_min: number };
  // Where people get stuck (owner, 25 Oct 2026); telemetry-flows.ts sends these.
  /** A journey of several steps: started, a step reached, Save refused, how it ended. */
  "sx.flow": {
    flow: FlowName;
    outcome: FlowOutcome;
    step?: FlowStep;
    via?: FlowVia;
    /** The step's place (0 first), the number of steps, what was left to do. */
    index?: number;
    steps?: number;
    left?: number;
    /** Since the flow started. */
    ms?: number;
  };
  /** One Android permission or settings screen asked for in phone setup. */
  "sx.permission_prompt": {
    permission: PromptPermission;
    outcome: "granted" | "denied" | "blocked" | "not_opened" | "unknown";
    via?: "prompt" | "settings";
    from?: "setup" | "fix";
    ms?: number;
  };
};

export type FlowName = "onboarding" | "phone_setup" | "add_lead" | "log_result";
export type FlowOutcome =
  | "start"
  | "step"
  | "blocked"
  | "done"
  | "skip"
  | "cancel"
  | "abandon"
  | "fail";
/** Every flow's steps (the server's FLOW_STEPS). */
export type FlowStep =
  | "start"
  | "name"
  | "business"
  | "team"
  | "first"
  | "calls"
  | "notifications"
  | "recordings"
  | "battery"
  | "autostart"
  | "call_log"
  | "recorder"
  | "form"
  | "duplicate"
  | "talk"
  | "reason"
  | "stage"
  | "next"
  | "save";
export type FlowVia =
  | "business"
  | "solo"
  | "join"
  | "all"
  | "fix"
  | "quick"
  | "sheet"
  | "after_call"
  | "lead";
export type PromptPermission =
  | "calls"
  | "notifications"
  | "rec_files"
  | "all_files"
  | "folder"
  | "battery"
  | "autostart"
  | "call_log"
  | "recorder";
export type TapZone = `r${1 | 2 | 3 | 4}c${1 | 2 | 3}`;

/** The app's screens (the server's SCREENS); routeTemplate's pages, a lead open on Leads. */
export type Screen =
  | "home"
  | "dashboard"
  | "analysis"
  | "new_call"
  | "calls_list"
  | "report"
  | "calls"
  | "leads"
  | "lead"
  | "chats"
  | "coaching"
  | "prospects"
  | "prospect"
  | "organisation"
  | "org_insights"
  | "org_invites"
  | "org_person"
  | "settings"
  | "settings_section"
  | "account"
  | "billing"
  | "plans"
  | "apps"
  | "developers"
  | "review"
  | "welcome"
  | "other";

/** Key actions whose tap-to-response time is measured (the server's ACTIONS). */
export type TimedAction =
  | "lead_open"
  | "call_start"
  | "tab_switch"
  | "outcome_save"
  | "report_open"
  | "nav_switch"
  | "sheet_open"
  | "search"
  | "save"
  | "send"
  | "filter"
  | "back"
  | "other";

export type TapTarget =
  | "button"
  | "link"
  | "tab"
  | "row"
  | "card"
  | "input"
  | "icon"
  | "text"
  | "image"
  | "other";

export type ErrorClass =
  | "typeerror"
  | "referenceerror"
  | "rangeerror"
  | "syntaxerror"
  | "chunkloaderror"
  | "aborterror"
  | "networkerror"
  | "securityerror"
  | "notallowederror"
  | "quotaexceedederror"
  | "error"
  | "other";

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
  "sx.screen_viewed",
  "sx.action_timing",
  "sx.web_vital",
  "sx.app_start",
  "sx.js_error",
  "sx.api_slow",
  "sx.tap_issue",
  "sx.feature_used",
  "sx.shake",
  "sx.phone_call",
  "sx.lead_stage_moved",
  "sx.board_drag",
  "sx.lead_open_to_action",
  "sx.lead_suggestion",
  "sx.app_launch",
  "sx.app_frames",
  "sx.app_exit",
  "sx.device_profile",
  "sx.device_state",
  "sx.network_state",
  "sx.permission_snapshot",
  "sx.writes_waiting",
  "sx.screen_hidden",
  "sx.flow",
  "sx.permission_prompt",
] as const satisfies readonly TelemetryEventName[];

export type SizeBand = "under_5mb" | "5_to_20mb" | "over_20mb";
export type AudioFormat = "mp3" | "wav" | "m4a" | "ogg" | "flac" | "other";
/** A lead's desk stage kind (Lead OS: Junk is the seventh). */
export type LeadKind =
  | "new"
  | "not_connected"
  | "follow_up"
  | "interested"
  | "won"
  | "lost"
  | "junk";
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
/** How capable the device is: its cores and memory as the browser reports them. */
export type DeviceTier = "low" | "mid" | "high" | "unknown";
export type NetworkSpeed = "slow_2g" | "2g" | "3g" | "4g" | "unknown";
export type NetworkLink =
  | "wifi"
  | "cellular"
  | "ethernet"
  | "offline"
  | "unknown";

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

/**
 * Low (2 GB or less, or 4 cores or fewer), high (8 GB and 8 cores or more) or
 * mid; unknown when the browser says neither (Safari and Firefox hide memory).
 */
export function deviceTier(
  cores: number | undefined,
  memoryGb: number | undefined,
): DeviceTier {
  const knownCores = typeof cores === "number" && cores > 0;
  const knownMemory = typeof memoryGb === "number" && memoryGb > 0;
  if (!knownCores && !knownMemory) return "unknown";
  if ((knownMemory && memoryGb <= 2) || (knownCores && cores <= 4))
    return "low";
  if (knownMemory && memoryGb >= 8 && knownCores && cores >= 8) return "high";
  return "mid";
}

/** A version or model label as the server takes it (ingest.py _LABEL_PATTERN). */
const LABEL = /^[a-z0-9][a-z0-9._-]{0,31}$/;

/** The CPU test's work: a thousand rows of JSON, like an API answer (made once). */
let cpuSample: string | null = null;
function cpuText(): string {
  if (cpuSample) return cpuSample;
  const rows: Array<Record<string, unknown>> = [];
  let seed = 7;
  for (let id = 0; id < 1_000; id += 1) {
    seed = (Math.imul(seed, 48_271) + 11) | 0;
    rows.push({
      id,
      stage: `s${(seed >>> 8) % 9}`,
      score: ((seed >>> 4) % 1_000) / 10,
      tags: ["a", "b", String(seed & 255)],
      open: (seed & 1) === 1,
    });
  }
  return (cpuSample = JSON.stringify(rows));
}

/**
 * The CPU test (owner, 27 Oct 2026: the app on the slowest phones): the best of
 * five passes of reading and writing the same JSON, in ms to a tenth. The
 * browser's native code does the work, so how far the JIT has warmed up doesn't
 * decide it; about 1 ms on a laptop.
 */
export function cpuMs(now: () => number = () => performance.now()): number {
  const text = cpuText();
  let best = Infinity;
  for (let run = 0; run < 5; run += 1) {
    const start = now();
    JSON.stringify(JSON.parse(text));
    best = Math.min(best, now() - start);
  }
  return Math.round(best * 10) / 10;
}

/**
 * The tier the CPU test measured: high under 3 ms, low from 6 ms (provisional,
 * 27 Oct 2026, about 2.5 and 5 times a laptop; the speed check's 4x and 6x
 * runs record the test, to set them from).
 */
export function cpuTier(milliseconds: number): DeviceTier {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "unknown";
  return milliseconds < 3 ? "high" : milliseconds < 6 ? "mid" : "low";
}

const CPU_KEY = "sx-cpu";
const CPU_MAX_AGE_MS = 7 * 24 * 3_600_000;

/** The device's last CPU test (kept a week), or null. */
export function readCpuMs(
  storage: Pick<Storage, "getItem"> | null,
  now: number,
): number | null {
  try {
    const kept = JSON.parse(storage?.getItem(CPU_KEY) ?? "null") as {
      ms?: unknown;
      at?: unknown;
    } | null;
    return kept &&
      typeof kept.ms === "number" &&
      kept.ms >= 0 &&
      kept.ms < 60_000 &&
      typeof kept.at === "number" &&
      now - kept.at >= 0 &&
      now - kept.at < CPU_MAX_AGE_MS
      ? kept.ms
      : null;
  } catch {
    return null;
  }
}

export function keepCpuMs(
  storage: Pick<Storage, "setItem"> | null,
  milliseconds: number,
  now: number,
) {
  try {
    storage?.setItem(CPU_KEY, JSON.stringify({ ms: milliseconds, at: now }));
  } catch {
    // Without storage the next page load runs the test again.
  }
}

/** A phone's model as a label ("redmi-note-8-pro"); null when hidden ("K"). */
export function modelLabel(raw: string | null | undefined): string | null {
  const label = (raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._]+/g, "-")
    .replace(/^[-.]+/, "")
    .slice(0, 32)
    .replace(/[-.]+$/, "");
  return label.length > 1 && LABEL.test(label) ? label : null;
}

/** The model in an Android user agent ("Linux; Android 12; Redmi Note 8 Pro Build/…; wv)"). */
export function userAgentModel(userAgent: string): string | null {
  return modelLabel(
    /\bAndroid [^;)]*;\s*([^;)]+?)(?:\s+Build\/[^;)]*)?\s*(?:;\s*wv\s*)?\)/.exec(
      userAgent,
    )?.[1],
  );
}

type HintedNavigator = Navigator & {
  userAgentData?: {
    getHighEntropyValues?: (hints: string[]) => Promise<{ model?: string }>;
  };
};

/** The phone's model on Android: the browser's hint, else its user agent; null elsewhere. */
export async function deviceModel(
  nav: HintedNavigator,
): Promise<string | null> {
  if (!/\bAndroid\b/.test(nav.userAgent)) return null;
  try {
    const hinted = modelLabel(
      (await nav.userAgentData?.getHighEntropyValues?.(["model"]))?.model,
    );
    if (hinted) return hinted;
  } catch {
    // The hint was refused: the user agent may still say.
  }
  return userAgentModel(nav.userAgent);
}

/** The web app's build: its commit's first 12 characters; null in development. */
export function releaseLabel(raw: string | undefined): string | null {
  const value = (raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/[0-9a-f]{40}/, (commit) => commit.slice(0, 12));
  return LABEL.test(value) ? value : null;
}

/** Inlined at build time from AC_RELEASE_ID (next.config.ts). */
const WEB_RELEASE = releaseLabel(process.env.NEXT_PUBLIC_AC_RELEASE_ID);

const SIGN_IN_KEY = "sx-sign-in";
const SIGN_IN_MAX_AGE_MS = 10 * 60_000;
const SIGN_IN_METHODS = new Set<string>([
  "password",
  "email_code",
  "google",
  "apple",
  "facebook",
  "pulse",
]);

/**
 * A sign-in just worked: sx.sign_in goes out when the app has the new session
 * (TelemetryClient.setSession), after the page reload many sign-ins end with.
 */
export function noteSignIn(
  method: SignInMethod,
  storage: Pick<Storage, "setItem"> | null = sessionStore(),
  now = Date.now(),
) {
  try {
    storage?.setItem(SIGN_IN_KEY, JSON.stringify({ method, at: now }));
  } catch {
    // Without storage the sign-in goes uncounted.
  }
}

/** The sign-in this tab noted in the last ten minutes, once. */
export function takeSignIn(
  storage: Pick<Storage, "getItem" | "removeItem"> | null = sessionStore(),
  now = Date.now(),
): SignInMethod | null {
  try {
    const raw = storage?.getItem(SIGN_IN_KEY);
    if (raw === null || raw === undefined) return null;
    storage?.removeItem(SIGN_IN_KEY);
    const kept = JSON.parse(raw) as { method?: unknown; at?: unknown } | null;
    return kept &&
      typeof kept.method === "string" &&
      SIGN_IN_METHODS.has(kept.method) &&
      typeof kept.at === "number" &&
      now - kept.at >= 0 &&
      now - kept.at < SIGN_IN_MAX_AGE_MS
      ? (kept.method as SignInMethod)
      : null;
  } catch {
    return null;
  }
}

function sessionStore(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function localStore(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** The network as the browser reports it (Chrome and Android WebView only). */
export function network(
  connection: { effectiveType?: string; type?: string } | undefined,
  online: boolean,
): { net: NetworkSpeed; link: NetworkLink } {
  const speed = connection?.effectiveType;
  const net: NetworkSpeed =
    speed === "slow-2g"
      ? "slow_2g"
      : speed === "2g" || speed === "3g" || speed === "4g"
        ? speed
        : "unknown";
  const type = connection?.type;
  const link: NetworkLink = !online
    ? "offline"
    : type === "wifi" || type === "cellular" || type === "ethernet"
      ? type
      : "unknown";
  return { net, link };
}

/** The phone app's version from its user agent ("SalesXrayApp/0.3.88"). */
export function appVersion(userAgent: string): string | null {
  const version = /\bSalesXrayApp\/([0-9][0-9a-z.-]{0,30})/i.exec(
    userAgent,
  )?.[1];
  return version ? version.toLowerCase() : null;
}

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
  "/welcome",
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

const SCREENS: Record<string, Screen> = {
  "/": "home",
  "/dashboard": "dashboard",
  "/analysis": "analysis",
  "/analysis/new": "new_call",
  "/analysis/calls": "calls_list",
  "/analysis/calls/[callId]": "report",
  "/calls": "calls",
  "/leads": "leads",
  "/chats": "chats",
  "/coaching": "coaching",
  "/prospects": "prospects",
  "/prospects/[prospectId]": "prospect",
  "/organisation": "organisation",
  "/organisation/insights": "org_insights",
  "/organisation/invites": "org_invites",
  "/organisation/people/[personId]": "org_person",
  "/settings": "settings",
  "/settings/[section]": "settings_section",
  "/account": "account",
  "/account/billing": "billing",
  "/billing": "billing",
  "/plans": "plans",
  "/apps": "apps",
  "/developers": "developers",
  "/review": "review",
  "/welcome": "welcome",
};

/** The screen a page is (the server's SCREENS); a lead open on Leads is "lead". */
export function screenOf(pathname: string, search = ""): Screen {
  const template = routeTemplate(pathname);
  const screen = (template && SCREENS[template]) || "other";
  return screen === "leads" && /[?&]lead=/.test(search) ? "lead" : screen;
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
  // An event's own keys and where it ran (device, tier, network, link, app, version):
  // the phone's daily profile is the largest, at 15.
  if (entries.length > 16) return false;
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
  tier?: DeviceTier;
  net?: NetworkSpeed;
  link?: NetworkLink;
  appVersion?: string | null;
}>;

type Sender = Readonly<{
  fetch: typeof fetch;
  now: () => Date;
  id: () => string;
  /** Read at each event; absent under test (no route, device or app). */
  context?: () => EventContext;
  /** The sign-in noted before the session arrived (takeSignIn), once. */
  signIn?: () => SignInMethod | null;
}>;

/** One step for a bug report's trail: the event's name, when, and the route template. */
export type TrailStep = Readonly<{ event: string; at: string; route?: string }>;
const TRAIL: TrailStep[] = [];
const TRAIL_SIZE = 20;

/** The last twenty app steps, oldest first, for a bug report (demo P0, 26 Oct 2026). */
export function recentSteps(): readonly TrailStep[] {
  return [...TRAIL];
}

function keepStep(step: TrailStep) {
  TRAIL.push(step);
  if (TRAIL.length > TRAIL_SIZE) TRAIL.splice(0, TRAIL.length - TRAIL_SIZE);
}

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
    const method = sessionId ? this.sender.signIn?.() : null;
    if (method) this.track("sx.sign_in", { method });
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
      if (context.tier) values.tier = context.tier;
      if (context.net) values.net = context.net;
      if (context.link) values.link = context.link;
      if (context.appVersion) values.app_version = context.appVersion;
    }
    if (!safePayload(values)) return;
    const occurredAt = this.sender.now().toISOString();
    keepStep({
      event: name,
      at: occurredAt,
      ...(context?.route ? { route: context.route } : {}),
    });
    this.queue.push({
      event_id: this.sender.id(),
      event_name: name,
      event_version: "1.0",
      occurred_at: occurredAt,
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

  /**
   * False once the server has said it records nothing for this person (they or
   * their workspace turned usage analytics off): automatic capture stops.
   */
  active(): boolean {
    return (
      this.enabled &&
      !this.off &&
      (this.known === undefined || !!this.known?.size)
    );
  }

  /**
   * Whether the server records this person's events (it lists them), or null
   * while that is unknown: nobody signed in yet, or the server didn't answer.
   * Only the server's answer decides it, never a dropped connection.
   */
  async collecting(): Promise<boolean | null> {
    if (!this.enabled || !this.session) return null;
    // A read that failed is tried again (the phone app waits for an answer).
    if (this.known === null) this.accepted = null;
    const accepted = await this.taxonomy();
    return accepted ? accepted.size > 0 : null;
  }

  /** Read the server's list again (after a switch in Settings, Privacy). */
  refresh() {
    this.accepted = null;
    this.known = undefined;
    this.off = false;
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

type BrowserNavigator = Navigator & {
  deviceMemory?: number;
  connection?: { effectiveType?: string; type?: string };
};

/** This device's CPU test: this page's, else the last one kept (undefined until read). */
let deviceCpu: number | null | undefined;

/** Run the CPU test (once a page, when the app is idle) and keep it for the tier. */
export function measureCpu(): number {
  deviceCpu = cpuMs();
  keepCpuMs(localStore(), deviceCpu, Date.now());
  return deviceCpu;
}

/**
 * This page: its route, the device's class and tier, the network, web or the
 * app, and its version (the phone app's, or the web build's). The tier is the
 * CPU test's once this device has run it; until then, the guess from cores and
 * memory (every phone says 8 and 8, so "high").
 */
function browserContext(): EventContext {
  const nav = navigator as BrowserNavigator;
  const app = document.documentElement.hasAttribute(IN_APP_ATTRIBUTE)
    ? "android"
    : "web";
  if (deviceCpu === undefined) deviceCpu = readCpuMs(localStore(), Date.now());
  return {
    route: routeTemplate(window.location.pathname),
    device: deviceClass(window.innerWidth),
    app,
    tier:
      deviceCpu === null
        ? deviceTier(nav.hardwareConcurrency, nav.deviceMemory)
        : cpuTier(deviceCpu),
    ...network(nav.connection, nav.onLine !== false),
    appVersion:
      appVersion(nav.userAgent) ?? (app === "web" ? WEB_RELEASE : null),
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
    signIn: () => takeSignIn(),
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

// Tap-to-response timing started by code, not by a touch (telemetry-auto.tsx
// registers it): a Call press is timed from the moment a call really starts.
let actionTimer: ((action: TimedAction) => void) | null = null;

export function setActionTimer(
  timer: ((action: TimedAction) => void) | null,
): void {
  actionTimer = timer;
}

/** Starts timing `action` now, as a tap on it would. */
export function timeAction(action: TimedAction): void {
  actionTimer?.(action);
}
