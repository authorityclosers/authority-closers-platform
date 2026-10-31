/**
 * "Captured for you" in the advanced reporter (owner, 31 Oct 2026): what the
 * team needs to see the problem again, gathered on the device as the editor
 * opens. The screen, the app's release, the device and its network, the last
 * fifty app steps (names from fixed lists, never what was typed), recent
 * problems, slow or failed calls to the server with their request references,
 * and how fast the page was. Nothing personal: routes have their ids taken
 * out, messages are scrubbed (scrub.ts), and the server scrubs it all again.
 */

import { recentSteps, type TrailStep } from "../telemetry";
import { reportContext, type ReportContext } from "./device";
import { recentErrors, type RecentError } from "./recent-errors";
import { scrubRoute } from "./scrub";

export type CallTiming = Readonly<{
  method?: string;
  path: string;
  ms?: number;
  status?: number;
  reference?: string;
  failed: boolean;
}>;

export type Speed = Readonly<{
  /** First byte, page ready and fully loaded, from the start of this page. */
  first_byte_ms?: number;
  ready_ms?: number;
  loaded_ms?: number;
  /** Largest paint and how much the layout jumped (web vitals). */
  largest_paint_ms?: number;
  layout_shift?: number;
  memory_mb?: number;
  page_age_s: number;
}>;

export type Captured = Readonly<{
  route: string;
  context: ReportContext;
  trail: readonly TrailStep[];
  errors: readonly RecentError[];
  calls: readonly CallTiming[];
  speed: Speed;
}>;

const SLOW_MS = 1000;
const MAX_CALLS = 15;

const round = (value: number) => Math.max(0, Math.round(value));

function lastEntries(type: string): Promise<PerformanceEntry[]> {
  return new Promise((resolve) => {
    if (typeof PerformanceObserver === "undefined") return resolve([]);
    const seen: PerformanceEntry[] = [];
    try {
      const watch = new PerformanceObserver((list) => {
        seen.push(...list.getEntries());
      });
      watch.observe({ type, buffered: true } as PerformanceObserverInit);
      window.setTimeout(() => {
        watch.disconnect();
        resolve(seen);
      }, 0);
    } catch {
      resolve([]);
    }
  });
}

async function speed(): Promise<Speed> {
  const [navigation] = performance.getEntriesByType(
    "navigation",
  ) as PerformanceNavigationTiming[];
  const [paints, shifts] = await Promise.all([
    lastEntries("largest-contentful-paint"),
    lastEntries("layout-shift"),
  ]);
  const largest = paints[paints.length - 1];
  const shift = (
    shifts as Array<
      PerformanceEntry & { value?: number; hadRecentInput?: boolean }
    >
  )
    .filter((entry) => !entry.hadRecentInput)
    .reduce((sum, entry) => sum + (entry.value ?? 0), 0);
  const memory = (
    performance as Performance & { memory?: { usedJSHeapSize?: number } }
  ).memory?.usedJSHeapSize;
  return {
    ...(navigation
      ? {
          first_byte_ms: round(navigation.responseStart),
          ready_ms: round(navigation.domContentLoadedEventEnd),
          ...(navigation.loadEventEnd
            ? { loaded_ms: round(navigation.loadEventEnd) }
            : {}),
        }
      : {}),
    ...(largest ? { largest_paint_ms: round(largest.startTime) } : {}),
    ...(shifts.length ? { layout_shift: Math.round(shift * 1000) / 1000 } : {}),
    ...(typeof memory === "number"
      ? { memory_mb: Math.round(memory / 1048576) }
      : {}),
    page_age_s: round(performance.now() / 1000),
  };
}

/** Calls to our server that failed (from recent problems) or took a second or more. */
export function callTimings(errors: readonly RecentError[]): CallTiming[] {
  const failed: CallTiming[] = errors
    .filter((error) => error.kind === "http" && error.path)
    .map((error) => ({
      ...(error.method ? { method: error.method } : {}),
      path: error.path!,
      ...(typeof error.status === "number" ? { status: error.status } : {}),
      ...(error.reference ? { reference: error.reference } : {}),
      failed: true,
    }));
  const entries =
    typeof performance.getEntriesByType === "function"
      ? (performance.getEntriesByType("resource") as Array<
          PerformanceResourceTiming & { responseStatus?: number }
        >)
      : [];
  const slow: CallTiming[] = [];
  for (const entry of entries) {
    if (entry.duration < SLOW_MS) continue;
    let url: URL;
    try {
      url = new URL(entry.name, window.location.href);
    } catch {
      continue;
    }
    if (
      url.origin !== window.location.origin ||
      !url.pathname.startsWith("/v1/")
    )
      continue;
    slow.push({
      path: scrubRoute(url.pathname, 200),
      ms: round(entry.duration),
      ...(entry.responseStatus ? { status: entry.responseStatus } : {}),
      failed: false,
    });
  }
  return [...failed, ...slow].slice(-MAX_CALLS);
}

export async function captureTelemetry(route: string): Promise<Captured> {
  const errors = recentErrors();
  const [context, timing] = await Promise.all([reportContext(), speed()]);
  return {
    route,
    context,
    trail: recentSteps(),
    errors,
    calls: callTimings(errors),
    speed: timing,
  };
}

// ---------- Steps to reproduce, in words ----------

const SCREENS: Record<string, string> = {
  home: "Home",
  dashboard: "Home",
  analysis: "Calls",
  new_call: "New analysis",
  calls_list: "Calls",
  calls: "Calls",
  report: "a call report",
  leads: "Leads",
  lead: "a lead",
  chats: "Chats",
  coaching: "Coaching",
  prospects: "Prospects",
  prospect: "a prospect",
  organisation: "Organisation",
  org_insights: "Insights",
  org_invites: "Invites",
  org_person: "a person's page",
  settings: "Settings",
  settings_section: "a Settings page",
  account: "Account",
  billing: "Billing",
  plans: "Plans",
  apps: "Apps",
  developers: "Developers",
  review: "Review",
  welcome: "Welcome",
};

const KINDS: Record<string, string> = {
  new: "New",
  not_connected: "Not connected",
  follow_up: "Follow-up",
  interested: "Interested",
  won: "Won",
  lost: "Lost",
  junk: "Junk",
};

const WORDS: Record<string, string> = {
  "sx.sign_in": "Sign in",
  "sx.sign_out": "Sign out",
  "sx.phone_call": "Call a lead",
  "sx.upload_started": "Start uploading a call",
  "sx.upload_finished": "Finish uploading a call",
  "sx.report_opened": "Open a call report",
  "sx.coaching_opened": "Open coaching",
  "sx.clip_played": "Play a clip",
  "sx.outcome_set": "Set a call's outcome",
  "sx.prospect_edited": "Edit a prospect",
  "sx.error_shown": "See an error message",
  "sx.board_drag": "Drag a lead on the board",
  "sx.full_report_requested": "Ask for the full report",
  "sx.reanalyse_requested": "Ask to analyse a call again",
  "sx.paywall_seen": "See the plans",
};

// Timings, frames and device states: not steps a person takes.
const QUIET =
  /^sx\.(scroll_depth|route_timing|api_timing|api_slow|action_timing|web_vital|app_frames|app_start|app_launch|app_exit|device_state|device_profile|network_state|permission_snapshot|permission_prompt|writes_waiting|screen_hidden|flow|section_read|tap_issue|lead_open_to_action|lead_suggestion|js_error|shake|analysis_seen_done|section_action|on_demand_requested|mission_started|mission_completed|feature_used|paywall_clicked)$/;

const words = (value: string) => {
  const text = value.replace(/^sx\./, "").replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** One trail step as something a person did, or null for a quiet one. */
export function stepWords(step: TrailStep): string | null {
  const detail = step.detail ?? {};
  const where = detail.screen ? SCREENS[detail.screen] : undefined;
  switch (step.event) {
    case "sx.screen_viewed":
      return `Open ${where ?? "a screen"}`;
    case "sx.tap":
      return `Tap a ${detail.target && detail.target !== "other" ? detail.target : "control"}${where ? ` on ${where}` : ""}`;
    case "sx.lead_stage_moved":
      return `Move a lead to ${(detail.to_kind && KINDS[detail.to_kind]) ?? "another stage"}${detail.via ? ` (${words(detail.via).toLowerCase()})` : ""}`;
    default:
      if (WORDS[step.event]) return WORDS[step.event]!;
      if (QUIET.test(step.event) || !step.event.startsWith("sx.")) return null;
      return words(step.event);
  }
}

/** The last steps that led here, repeats folded ("Tap a row on Leads, 3 times"). */
export function stepsFrom(trail: readonly TrailStep[], limit = 10): string[] {
  const out: Array<{ text: string; times: number }> = [];
  for (const step of trail) {
    const text = stepWords(step);
    if (!text) continue;
    const last = out[out.length - 1];
    if (last?.text === text) last.times += 1;
    else out.push({ text, times: 1 });
  }
  return out
    .slice(-limit)
    .map(({ text, times }) => (times > 1 ? `${text}, ${times} times` : text));
}
