import { expect, it } from "vitest";

import { parseRecorder } from "./native-phone";
import {
  CHECK_LABELS,
  EXPLAINERS,
  checkLabel,
  explainerFor,
  recorderGuide,
} from "./phone-setup-words";

it("names no maker when Google's Phone app is the only one, so a OnePlus Nord or a Vivo reads right", () => {
  // Orchestrator, 1 Nov 2026: a OnePlus Nord CE 2 seller (Google's Phone app)
  // was told OnePlus phones record calls.
  const google = parseRecorder({
    kind: "private",
    maker: "google",
    dialerLabel: "Phone by Google",
    recording: "private",
    folders: [],
  });
  const guide = recorderGuide(google, "oneplus");
  expect(guide.closed).toBe(true);
  expect(guide.lead).toContain("keeps call recordings inside itself");
  expect(guide.steps.join(" ")).not.toMatch(/OnePlus|Vivo|Samsung|Xiaomi/);
  expect(guide.steps).toContain(
    "Phone calls reach Sales X-Ray only from a Phone app that saves its recordings as files, not Google's.",
  );
});

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
