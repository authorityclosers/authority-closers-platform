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

it("opens the reporter on Ctrl B or Cmd B from anywhere, and on nothing else", async () => {
  const { installReportShortcut } = await import("./open");
  const heard = vi.fn();
  window.addEventListener(REPORT_PROBLEM_EVENT, heard);
  const remove = installReportShortcut();
  const press = (init: KeyboardEventInit) => {
    const event = new KeyboardEvent("keydown", { cancelable: true, ...init });
    document.body.dispatchEvent(event);
    return event.defaultPrevented;
  };
  expect(press({ key: "b", ctrlKey: true })).toBe(true);
  expect(press({ key: "B", metaKey: true })).toBe(true);
  expect(press({ key: "b" })).toBe(false);
  expect(press({ key: "b", ctrlKey: true, shiftKey: true })).toBe(false);
  expect(press({ key: "k", ctrlKey: true })).toBe(false);
  expect(heard).toHaveBeenCalledTimes(2);
  remove();
  press({ key: "b", ctrlKey: true });
  expect(heard).toHaveBeenCalledTimes(2);
  window.removeEventListener(REPORT_PROBLEM_EVENT, heard);
});
