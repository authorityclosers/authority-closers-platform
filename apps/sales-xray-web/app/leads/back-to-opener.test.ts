import {
  afterEach,
  beforeEach,
  expect,
  it,
  vi,
  type MockInstance,
} from "vitest";

import { backToOpener } from "./back-to-opener";

// Redmi QA R2 (10 Nov 2026): a call opened from Calls, and the lead's Back
// landed on Leads. Leads takes one more step back, to the page that opened it.
let back: MockInstance<() => void>;
beforeEach(() => {
  vi.useFakeTimers();
  back = vi.spyOn(window.history, "back").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

it("steps back once more when the phone's Back has already closed the lead", () => {
  window.history.replaceState(null, "", "/leads");
  backToOpener();
  vi.advanceTimersByTime(0);
  expect(back).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(2_000);
  expect(back).toHaveBeenCalledTimes(1);
});

it("waits for the arrow's own step back, then steps back once more", () => {
  window.history.replaceState(null, "", "/leads?lead=lead-1");
  backToOpener();
  vi.advanceTimersByTime(0);
  expect(back).not.toHaveBeenCalled();
  window.history.replaceState(null, "", "/leads");
  window.dispatchEvent(new PopStateEvent("popstate"));
  vi.advanceTimersByTime(0);
  expect(back).toHaveBeenCalledTimes(1);
});

it("stays when the lead's step never went", () => {
  window.history.replaceState(null, "", "/leads?lead=lead-1");
  backToOpener();
  vi.advanceTimersByTime(2_000);
  expect(back).not.toHaveBeenCalled();
});
