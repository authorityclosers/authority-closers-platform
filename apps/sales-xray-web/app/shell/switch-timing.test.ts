import { afterEach, expect, it, vi } from "vitest";

import {
  cancelSwitch,
  finishSwitch,
  markSwitchFeedback,
  markSwitchStart,
  switchTimes,
} from "./switch-timing";

afterEach(() => {
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
});

it("times a switch from the tap to its first answer and to a usable screen", () => {
  const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
  markSwitchStart("org-two", 1_000);
  markSwitchFeedback(1_016);
  markSwitchFeedback(1_500); // only the first answer counts
  // Another workspace came up: not this switch, which stays to be finished.
  expect(finishSwitch("org-one", 2_000)).toBeNull();
  expect(finishSwitch("org-two", 2_400)).toEqual({
    at: 1_000,
    feedback: 16,
    usable: 1_400,
  });
  expect(finishSwitch("org-two", 2_500)).toBeNull(); // recorded once
  expect(switchTimes()).toEqual([{ at: 1_000, feedback: 16, usable: 1_400 }]);
  expect(info).toHaveBeenCalledWith(
    "[sx-switch] tap to feedback 16 ms, tap to usable 1400 ms",
  );
});

it("forgets a switch that failed or never finished, and keeps the last twenty", () => {
  vi.spyOn(console, "info").mockImplementation(() => undefined);
  markSwitchStart("org-two", 1_000);
  cancelSwitch();
  expect(finishSwitch("org-two", 1_200)).toBeNull();
  markSwitchStart("org-two", 1_000);
  expect(finishSwitch("org-two", 62_000)).toBeNull();
  expect(switchTimes()).toEqual([]);
  for (let i = 0; i < 25; i++) {
    markSwitchStart("org-two", i * 10_000);
    finishSwitch("org-two", i * 10_000 + 900);
  }
  expect(switchTimes()).toHaveLength(20);
  expect(switchTimes()[0]?.at).toBe(50_000);
});
