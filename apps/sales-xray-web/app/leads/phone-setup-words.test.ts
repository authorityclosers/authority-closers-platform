import { expect, it } from "vitest";

import {
  CHECK_LABELS,
  EXPLAINERS,
  checkLabel,
  explainerFor,
} from "./phone-setup-words";

// The Google Play build reads no call history (Play's call log policy): the
// screen before Android's question says what that build really reads.
it("says call history only in the download-link app", () => {
  expect(checkLabel("calls", "direct")).toBe("Calls and call history");
  expect(explainerFor("calls", "direct")).toBe(EXPLAINERS.calls);

  const play = explainerFor("calls", "play")!;
  expect(checkLabel("calls", "play")).toBe("Calls");
  expect(play.title).toBe("Calls");
  expect(play.reads).toContain("Not your call history or contacts.");
  expect(play.reads).toContain("call recordings");
  expect(`${play.why} ${play.sends}`).not.toMatch(/call history/i);
});

it("has no calls to log on the Play build's battery screen", () => {
  expect(explainerFor("battery", "direct")!.why).toContain("log your calls");
  expect(explainerFor("battery", "play")!.why).not.toContain("log your calls");
  expect(explainerFor("battery", "play")!.why).toContain("lead alerts");
});

it("keeps every other line the same on both builds", () => {
  for (const key of ["recordings", "notifications"] as const) {
    expect(explainerFor(key, "play")).toBe(EXPLAINERS[key]);
    expect(checkLabel(key, "play")).toBe(CHECK_LABELS[key]);
  }
});
