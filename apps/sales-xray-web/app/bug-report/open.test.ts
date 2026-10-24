import { afterEach, expect, it, vi } from "vitest";

import {
  REPORT_PROBLEM_EVENT,
  openBugReport,
  reporterMounted,
  takeWaitingReport,
} from "./open";

afterEach(() => {
  takeWaitingReport();
});

// The frame loads the reporter once the page is quiet (shell/quiet.ts).
it("keeps a report asked for before the reporter loads, for the reporter to take", () => {
  const heard = vi.fn();
  window.addEventListener(REPORT_PROBLEM_EVENT, heard);
  openBugReport({ title: "Calls didn't refresh" });
  expect(heard).toHaveBeenCalledTimes(1);
  expect(takeWaitingReport()).toEqual({
    about: { title: "Calls didn't refresh" },
  });
  expect(takeWaitingReport()).toBeNull();
  window.removeEventListener(REPORT_PROBLEM_EVENT, heard);
});

it("doesn't open a report asked for long ago", () => {
  vi.useFakeTimers();
  openBugReport();
  vi.advanceTimersByTime(11_000);
  expect(takeWaitingReport()).toBeNull();
  vi.useRealTimers();
});

it("opens a loaded reporter at once", () => {
  const heard = vi.fn();
  window.addEventListener(REPORT_PROBLEM_EVENT, heard);
  const unmount = reporterMounted();
  openBugReport();
  expect(heard).toHaveBeenCalledTimes(1);
  expect(takeWaitingReport()).toBeNull();
  unmount();
  window.removeEventListener(REPORT_PROBLEM_EVENT, heard);
});
