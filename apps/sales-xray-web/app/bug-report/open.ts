/**
 * Opening the bug reporter from anywhere (owner, 23 Oct 2026: "bug catcher
 * for everyone"). The You menu, the command bar and an error corner card's
 * Report button all fire one window event; the reporter mounted in the app
 * frame listens for it. Outside the frame (sign-in, fixtures) nothing listens,
 * so error cards only offer Report while a reporter is mounted.
 */

import { useSyncExternalStore } from "react";

export const REPORT_PROBLEM_EVENT = "sales-xray:report-problem";

/**
 * Ctrl B (⌘B on a Mac) reports a problem from any screen, a menu or sheet open
 * too (owner, 25 Oct 2026: "a proper shortcut for pc"). Listened for before
 * anything else on the page, so a menu that keeps its keys cannot swallow it.
 */
export function installReportShortcut(): () => void {
  const onKeyDown = (event: KeyboardEvent) => {
    if (
      !(event.ctrlKey || event.metaKey) ||
      event.shiftKey ||
      event.altKey ||
      event.key.toLowerCase() !== "b"
    )
      return;
    event.preventDefault();
    openBugReport();
  };
  window.addEventListener("keydown", onKeyDown, true);
  return () => window.removeEventListener("keydown", onKeyDown, true);
}

/** What the person was looking at when they chose Report on an error card. */
export type ReportAbout = Readonly<{ title: string; reference?: string }>;

let waiting: { about: ReportAbout | null; at: number } | null = null;
/** A report asked for longer ago than this is not opened late. */
const WAIT_MS = 10_000;

export function openBugReport(about?: ReportAbout): void {
  // The frame loads the reporter once the page is quiet (shell/quiet.ts): a
  // report asked for before that waits, and the frame loads it at once.
  if (mounted === 0) {
    waiting = { about: about ?? null, at: Date.now() };
    listeners.forEach((listener) => listener());
  }
  window.dispatchEvent(
    new CustomEvent<ReportAbout | null>(REPORT_PROBLEM_EVENT, {
      detail: about ?? null,
    }),
  );
}

let mounted = 0;
const listeners = new Set<() => void>();

/** The reporter calls this while it is on screen; the return undoes it. */
export function reporterMounted(): () => void {
  mounted += 1;
  listeners.forEach((listener) => listener());
  return () => {
    mounted -= 1;
    listeners.forEach((listener) => listener());
  };
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The report asked for before the reporter loaded; the reporter takes it as it mounts. */
export function takeWaitingReport(): { about: ReportAbout | null } | null {
  const taken = waiting;
  waiting = null;
  return taken && Date.now() - taken.at < WAIT_MS
    ? { about: taken.about }
    : null;
}

/** True while a report waits for the reporter to load. */
export function useReportWaiting(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => waiting !== null,
    () => false,
  );
}

/** True while a reporter can open (the person is signed in, in the app). */
export function useReporterAvailable(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => mounted > 0,
    () => false,
  );
}
