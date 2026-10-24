"use client";

/**
 * Automatic performance and usage telemetry (owner, 24 Oct 2026: "Build full
 * performance and usage telemetry"). Mounted once in the root layout; every
 * event goes through telemetry.ts, so nothing leaves the page unless the
 * server lists it for this person (on unless they or their workspace turned it
 * off in Settings, Privacy). What it measures:
 *
 * - Screens and the flow between them (sx.screen_viewed, with time on the last).
 * - Tap to response for key actions (sx.action_timing): from the tap to the
 *   screen settling (no change for 150 ms, at most 10 s), and the browser's own
 *   input-to-paint time for that tap. The action is the element's
 *   `data-sx-action`, or what it plainly is: a lead or call row, a Call link,
 *   a tab, a navigation link, a button that opens a sheet.
 * - Web Vitals (LCP, INP, CLS, FCP, TTFB) and the app's start.
 * - Script errors: their class and a fingerprint of where they were thrown,
 *   never the message.
 * - API calls slower than 1.5 s or failed, with every id taken out of the path.
 * - Rage taps (three in a second on one spot) and dead taps (a tap on
 *   something that looks tappable and changes nothing).
 * - Features named with `data-sx-feature`.
 *
 * Never text, names, numbers or ids from the page.
 */
import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";
import { useEffect, useRef } from "react";

import { drainPhoneTelemetry, tellPhoneTelemetry } from "./leads/native-phone";
import {
  screenOf,
  telemetry,
  track,
  type ErrorClass,
  type Screen,
  type TapTarget,
  type TelemetryEventName,
  type TelemetryEvents,
  type TimedAction,
} from "./telemetry";

const QUIET_MS = 150;
const MAX_ACTION_MS = 10_000;
const NO_CHANGE_MS = 1_000;
const SLOW_API_MS = 1_500;
const MAX_ERRORS = 10;
const MAX_SLOW_APIS = 30;

const here = (): Screen =>
  typeof window === "undefined"
    ? "other"
    : screenOf(window.location.pathname, window.location.search);

const ms = (value: number) => Math.max(0, Math.round(value));

/** This page load's navigation timing, where the browser has one. */
function navigationEntry(): PerformanceNavigationTiming | undefined {
  try {
    return performance.getEntriesByType?.("navigation")[0] as
      | PerformanceNavigationTiming
      | undefined;
  } catch {
    return undefined;
  }
}

/** The key action a tap starts, or null for a tap that isn't one. */
export function actionOf(target: Element | null): TimedAction | null {
  if (!target) return null;
  const explicit = target
    .closest("[data-sx-action]")
    ?.getAttribute("data-sx-action");
  if (explicit)
    return ACTIONS.has(explicit) ? (explicit as TimedAction) : "other";
  if (target.closest('a[href^="tel:"]')) return "call_start";
  if (target.closest('[role="tab"]')) return "tab_switch";
  if (target.closest('[aria-haspopup="dialog"]')) return "sheet_open";
  if (target.closest("[data-call-row], a[href^='/analysis/calls/']"))
    return "report_open";
  if (target.closest("[data-lead-row]")) {
    // A button inside a lead row (call, message) is its own action.
    const button = target.closest("button, a");
    const label = button?.getAttribute("aria-label")?.toLowerCase() ?? "";
    if (button && /^call\b/.test(label)) return "call_start";
    if (button && button.closest("[data-lead-row]") !== button) return null;
    return "lead_open";
  }
  if (target.closest("nav a[href]")) return "nav_switch";
  return null;
}

const ACTIONS = new Set<string>([
  "lead_open",
  "call_start",
  "tab_switch",
  "outcome_save",
  "report_open",
  "nav_switch",
  "sheet_open",
  "search",
  "save",
  "send",
  "filter",
  "back",
  "other",
]);

const INTERACTIVE =
  'a[href], button, input, select, textarea, label, summary, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [role="option"], [role="switch"], [role="checkbox"], [tabindex], [data-sx-action]';

/** What kind of thing was tapped, never what it said. */
export function targetOf(target: Element): TapTarget {
  if (target.closest('[role="tab"]')) return "tab";
  if (target.closest("button, [role='button']")) return "button";
  if (target.closest("a[href], [role='link']")) return "link";
  if (target.closest("input, select, textarea")) return "input";
  if (target.closest("[data-lead-row], [data-call-row], li, tr")) return "row";
  if (target.closest("svg")) return "icon";
  if (target.closest("img, picture")) return "image";
  if (target.closest("article, [data-card]")) return "card";
  return target.textContent?.trim() ? "text" : "other";
}

/**
 * An API path with every id taken out ("/v1/leads/<uuid>/calls" becomes
 * "v1_leads_id_calls"): only plain lower-case words and the API version stay;
 * anything else (ids, numbers, emails, capitals) becomes "id".
 */
export function endpointOf(path: string): string {
  const parts = path
    .split(/[?#]/)[0]
    .split("/")
    .filter(Boolean)
    .slice(0, 6)
    .map((part) =>
      /^v\d+$/.test(part)
        ? part
        : /^[a-z][a-z_-]{0,23}$/.test(part)
          ? part.replace(/-/g, "_")
          : "id",
    );
  return (parts.join("_").replace(/_+/g, "_") || "root").slice(0, 48);
}

const ERROR_CLASSES = new Set<string>([
  "typeerror",
  "referenceerror",
  "rangeerror",
  "syntaxerror",
  "chunkloaderror",
  "aborterror",
  "networkerror",
  "securityerror",
  "notallowederror",
  "quotaexceedederror",
  "error",
]);

/** FNV-1a, 32 bits, as 8 hex characters. */
export function fingerprint(text: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

/** An error's class, where it was thrown (a fingerprint) and whose code threw it. */
export function errorFacts(
  error: unknown,
  origin: string,
): {
  error: ErrorClass;
  where: string;
  source: "app" | "vendor" | "extension" | "unknown";
} {
  const name = error instanceof Error ? error.name.toLowerCase() : "error";
  const errorClass = (ERROR_CLASSES.has(name) ? name : "other") as ErrorClass;
  const stack = error instanceof Error ? (error.stack ?? "") : "";
  // The first frame with a file: its file name and line, no query or host.
  const frame =
    /((?:https?|chrome-extension|moz-extension):\/\/[^\s)]+?):(\d+):(\d+)/.exec(
      stack,
    );
  const file = frame?.[1] ?? "";
  const source = !file
    ? "unknown"
    : /^(chrome|moz)-extension:/.test(file)
      ? "extension"
      : file.startsWith(origin)
        ? "app"
        : "vendor";
  const base = file.split("?")[0].split("/").pop() ?? "";
  return {
    error: errorClass,
    where: fingerprint(`${errorClass}|${base}:${frame?.[2] ?? ""}`),
    source,
  };
}

/** The Android app's own events the page sends for it (app 1.0.25+). */
const PHONE_EVENTS = new Set<string>([
  "sx.app_launch",
  "sx.app_frames",
  "sx.app_exit",
  "sx.device_profile",
  "sx.device_state",
  "sx.network_state",
  "sx.permission_snapshot",
]);

/**
 * The phone app's side of the switch: tell it whether this person is recorded,
 * then send what it collected. Null (nothing told, nothing sent) until the
 * server has answered for someone signed in.
 */
export async function syncPhone(): Promise<boolean | null> {
  const on = await telemetry.collecting();
  if (on === null) return null;
  await tellPhoneTelemetry(on);
  if (!on) return false;
  for (const event of await drainPhoneTelemetry())
    if (PHONE_EVENTS.has(event.name)) {
      const name = event.name as TelemetryEventName;
      // The server checks every value against the event's definition.
      track(name, event.fields as unknown as TelemetryEvents[typeof name]);
    }
  return true;
}

type Timing = {
  action: TimedAction;
  start: number;
  last: number | null;
  screen: Screen;
  quiet: ReturnType<typeof setTimeout> | null;
  cap: ReturnType<typeof setTimeout>;
  observer: MutationObserver;
};

/** The last screen shown and whether the last navigation was Back. */
type PageState = {
  screen: { name: Screen; since: number } | null;
  backed: boolean;
};
type Page = { current: PageState };

function showScreen(page: Page, pathname: string | null) {
  if (!pathname || !telemetry.active()) return;
  const now = performance.now();
  const name = screenOf(pathname, window.location.search);
  const previous = page.current.screen;
  if (previous?.name === name) return;
  const navigation = navigationEntry();
  track("sx.screen_viewed", {
    screen: name,
    from: previous?.name ?? "none",
    nav: !previous
      ? navigation?.type === "reload"
        ? "reload"
        : "first"
      : page.current.backed
        ? "back"
        : "push",
    ...(previous ? { stay_ms: ms(now - previous.since) } : {}),
  });
  page.current.backed = false;
  page.current.screen = { name, since: now };
}

function listenAll(page: Page, cleanups: Array<() => void>) {
  const listen = <K extends keyof WindowEventMap>(
    kind: K,
    handler: (event: WindowEventMap[K]) => void,
    options?: AddEventListenerOptions,
  ) => {
    window.addEventListener(kind, handler, options);
    cleanups.push(() => window.removeEventListener(kind, handler, options));
  };

  listen("popstate", () => {
    page.current.backed = true;
  });

  // The phone app: once the server has answered for someone signed in (the
  // session arrives a moment after the first paint), and on every return.
  let phoneTimer: ReturnType<typeof setTimeout> | null = null;
  const phone = (attempt = 0) => {
    if (phoneTimer) clearTimeout(phoneTimer);
    phoneTimer = null;
    void syncPhone()
      .then((result) => {
        if (result === null && attempt < 4)
          phoneTimer = setTimeout(() => phone(attempt + 1), 3_000);
      })
      .catch(() => {
        // The phone app or the server didn't answer: next return.
      });
  };
  phone();
  const onVisible = () => {
    if (document.visibilityState === "visible") phone();
  };
  document.addEventListener("visibilitychange", onVisible);
  cleanups.push(() => {
    document.removeEventListener("visibilitychange", onVisible);
    if (phoneTimer) clearTimeout(phoneTimer);
  });

  // The app's start: page open to the first screen working (this effect).
  try {
    const navigation = navigationEntry();
    let warm = false;
    try {
      warm = sessionStorage.getItem("sx-started") === "1";
      sessionStorage.setItem("sx-started", "1");
    } catch {
      // Private windows can refuse storage: count it as a cold start.
    }
    const type = navigation?.type;
    track("sx.app_start", {
      start: warm ? "warm" : "cold",
      ms: ms(performance.now()),
      ...(type === "navigate" ||
      type === "reload" ||
      type === "back_forward" ||
      type === "prerender"
        ? { nav_type: type }
        : {}),
      screen: here(),
    });
  } catch {
    // No performance timeline: nothing to say about the start.
  }

  // Script errors, at most ten a page, each place once.
  const errorsSeen = new Set<string>();
  const reportError = (kind: "error" | "rejection", error: unknown) => {
    if (!telemetry.active() || errorsSeen.size >= MAX_ERRORS) return;
    const facts = errorFacts(error, window.location.origin);
    if (errorsSeen.has(facts.where)) return;
    errorsSeen.add(facts.where);
    const chunk =
      facts.error === "chunkloaderror" ||
      (error instanceof Error && /loading chunk/i.test(error.message));
    track("sx.js_error", {
      kind: chunk ? "chunk" : kind,
      ...facts,
      screen: here(),
    });
  };
  listen("error", (event) => reportError("error", event.error));
  listen("unhandledrejection", (event) =>
    reportError("rejection", event.reason),
  );

  // Slow or failed API calls, from the browser's own timings.
  let slowApis = 0;
  const lastSlow = new Map<string, number>();
  if (typeof PerformanceObserver !== "undefined") {
    try {
      const resources = new PerformanceObserver((list) => {
        if (!telemetry.active()) return;
        for (const entry of list.getEntries() as PerformanceResourceTiming[]) {
          if (
            entry.initiatorType !== "fetch" &&
            entry.initiatorType !== "xmlhttprequest"
          )
            continue;
          let url: URL;
          try {
            url = new URL(entry.name);
          } catch {
            continue;
          }
          if (
            url.origin !== window.location.origin ||
            !url.pathname.startsWith("/v1/") ||
            url.pathname.startsWith("/v1/telemetry/")
          )
            continue;
          const code =
            (entry as PerformanceResourceTiming & { responseStatus?: number })
              .responseStatus ?? 0;
          if (entry.duration < SLOW_API_MS && code < 500) continue;
          const endpoint = endpointOf(url.pathname);
          const at = performance.now();
          if (
            slowApis >= MAX_SLOW_APIS ||
            at - (lastSlow.get(endpoint) ?? -Infinity) < 30_000
          )
            continue;
          slowApis += 1;
          lastSlow.set(endpoint, at);
          track("sx.api_slow", {
            endpoint,
            status:
              code >= 500
                ? "5xx"
                : code >= 400
                  ? "4xx"
                  : code >= 300
                    ? "3xx"
                    : code >= 200
                      ? "2xx"
                      : "unknown",
            ms: ms(entry.duration),
            screen: here(),
          });
        }
      });
      resources.observe({ type: "resource", buffered: true });
      cleanups.push(() => resources.disconnect());
    } catch {
      // An old browser without resource timing.
    }
  }

  // The browser's input-to-paint time for recent taps (Event Timing).
  const paints: Array<{ start: number; duration: number }> = [];
  if (typeof PerformanceObserver !== "undefined") {
    try {
      const events = new PerformanceObserver((list) => {
        for (const entry of list.getEntries())
          paints.push({ start: entry.startTime, duration: entry.duration });
        if (paints.length > 40) paints.splice(0, paints.length - 40);
      });
      events.observe({
        type: "event",
        buffered: true,
        durationThreshold: 16,
      } as PerformanceObserverInit);
      cleanups.push(() => events.disconnect());
    } catch {
      // Event Timing is Chrome and Android WebView only.
    }
  }
  const paintFor = (start: number) => {
    const near = paints.filter((item) => Math.abs(item.start - start) < 100);
    return near.length
      ? ms(Math.max(...near.map((item) => item.duration)))
      : null;
  };

  // Tap to response for key actions.
  let timing: Timing | null = null;
  const finish = (result: "settled" | "timeout" | "no_change") => {
    const current = timing;
    if (!current) return;
    timing = null;
    current.observer.disconnect();
    if (current.quiet) clearTimeout(current.quiet);
    clearTimeout(current.cap);
    const end =
      result === "settled" && current.last !== null
        ? current.last
        : performance.now();
    const paint = paintFor(current.start);
    track("sx.action_timing", {
      action: current.action,
      ms: ms(Math.min(end - current.start, MAX_ACTION_MS)),
      result,
      ...(paint !== null ? { paint_ms: paint } : {}),
      screen: current.screen,
    });
  };
  const begin = (action: TimedAction, start: number) => {
    if (timing) finish(timing.last !== null ? "settled" : "no_change");
    const observer = new MutationObserver(() => {
      const current = timing;
      if (!current) return;
      current.last = performance.now();
      if (current.quiet) clearTimeout(current.quiet);
      current.quiet = setTimeout(() => finish("settled"), QUIET_MS);
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
    timing = {
      action,
      start,
      last: null,
      screen: here(),
      quiet: setTimeout(() => {
        if (timing && timing.last === null) finish("no_change");
      }, NO_CHANGE_MS),
      cap: setTimeout(() => finish("timeout"), MAX_ACTION_MS),
      observer,
    };
  };
  const onPointer = (event: PointerEvent) => {
    if (!telemetry.active() || !(event.target instanceof Element)) return;
    const action = actionOf(event.target);
    if (!action) return;
    // The tap's own time (it counts the input delay slow phones add), unless
    // the browser gives one off the page's clock.
    const now = performance.now();
    const stamp = event.timeStamp;
    begin(
      action,
      stamp > 0 && stamp <= now && now - stamp < 5_000 ? stamp : now,
    );
  };
  document.addEventListener("pointerdown", onPointer, {
    capture: true,
    passive: true,
  });
  cleanups.push(() =>
    document.removeEventListener("pointerdown", onPointer, { capture: true }),
  );

  // Rage taps, dead taps and named features.
  let taps: Array<{ at: number; x: number; y: number }> = [];
  const onClick = (event: MouseEvent) => {
    if (!telemetry.active() || !(event.target instanceof Element)) return;
    const target = event.target;
    const feature = target
      .closest("[data-sx-feature]")
      ?.getAttribute("data-sx-feature");
    if (feature && /^[a-z][a-z0-9_]{0,47}$/.test(feature))
      track("sx.feature_used", { feature, screen: here() });
    const at = performance.now();
    taps = [
      ...taps.filter(
        (tap) =>
          at - tap.at < 1_000 &&
          Math.hypot(tap.x - event.clientX, tap.y - event.clientY) < 24,
      ),
      { at, x: event.clientX, y: event.clientY },
    ];
    if (taps.length >= 3) {
      taps = [];
      const action = actionOf(target);
      track("sx.tap_issue", {
        kind: "rage",
        target: targetOf(target),
        ...(action ? { action } : {}),
        screen: here(),
      });
      return;
    }
    // A dead tap: it looks tappable, isn't, and nothing changes.
    if (
      target.closest(INTERACTIVE) ||
      getComputedStyle(target).cursor !== "pointer"
    )
      return;
    const path = window.location.href;
    let changed = false;
    const observer = new MutationObserver(() => {
      changed = true;
    });
    observer.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
    setTimeout(() => {
      observer.disconnect();
      if (!changed && window.location.href === path)
        track("sx.tap_issue", {
          kind: "dead",
          target: targetOf(target),
          screen: here(),
        });
    }, 700);
  };
  document.addEventListener("click", onClick, { capture: true, passive: true });
  cleanups.push(() =>
    document.removeEventListener("click", onClick, { capture: true }),
  );

  cleanups.unshift(() => finish("settled"));
}

export function TelemetryAuto() {
  const pathname = usePathname();
  const page = useRef<PageState>({ screen: null, backed: false });

  useReportWebVitals((metric) => {
    try {
      if (!telemetry.active()) return;
      const name = metric.name.toLowerCase();
      if (!["lcp", "inp", "cls", "fcp", "ttfb"].includes(name)) return;
      track("sx.web_vital", {
        metric: name as "lcp" | "inp" | "cls" | "fcp" | "ttfb",
        value: ms(name === "cls" ? metric.value * 1000 : metric.value),
        rating: metric.rating.replace("-", "_") as
          | "good"
          | "needs_improvement"
          | "poor",
        screen: here(),
      });
    } catch {
      // Nothing to record.
    }
  });

  // Screens and the flow between them. Telemetry never breaks a page: any
  // failure here is swallowed.
  useEffect(() => {
    try {
      showScreen(page, pathname);
    } catch {
      // Nothing to record.
    }
  }, [pathname]);

  // Everything that listens for the whole page's life.
  useEffect(() => {
    const cleanups: Array<() => void> = [];
    try {
      listenAll(page, cleanups);
    } catch {
      // A browser missing something: record less, never break the page.
    }
    return () => {
      for (const cleanup of cleanups) {
        try {
          cleanup();
        } catch {
          // Already gone.
        }
      }
    };
  }, []);

  return null;
}
