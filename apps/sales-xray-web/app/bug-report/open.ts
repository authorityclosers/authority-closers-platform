/**
 * Opening the bug reporter from anywhere (owner, 23 Oct 2026: "bug catcher
 * for everyone"). The You menu, the command bar and an error corner card's
 * Report button all fire one window event; the reporter mounted in the app
 * frame listens for it. Outside the frame (sign-in, fixtures) nothing listens,
 * so error cards only offer Report while a reporter is mounted.
 */

import { useSyncExternalStore } from "react";

export const REPORT_PROBLEM_EVENT = "sales-xray:report-problem";

/** What the person was looking at when they chose Report on an error card. */
export type ReportAbout = Readonly<{ title: string; reference?: string }>;

export function openBugReport(about?: ReportAbout): void {
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

/** True while a reporter can open (the person is signed in, in the app). */
export function useReporterAvailable(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => mounted > 0,
    () => false,
  );
}
