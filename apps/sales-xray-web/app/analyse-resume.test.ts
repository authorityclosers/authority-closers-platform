import { afterEach, describe, expect, it } from "vitest";

import {
  forgetAnalyseClick,
  pendingAnalyseClick,
  readyToResume,
  rememberAnalyseClick,
} from "./analyse-resume";

afterEach(() => forgetAnalyseClick());

it("keeps one Analyse click for the same file intent and agreed policy", () => {
  rememberAnalyseClick("intent-1", "policy-a", 1_000);
  expect(pendingAnalyseClick("intent-1", 2_000)).toBe("policy-a");
  expect(pendingAnalyseClick("intent-2", 2_000)).toBeNull();
  expect(pendingAnalyseClick(null, 2_000)).toBeNull();
});

it("forgets the click once it continued, and after 15 minutes", () => {
  rememberAnalyseClick("intent-1", "policy-a", 0);
  forgetAnalyseClick();
  expect(pendingAnalyseClick("intent-1", 1)).toBeNull();
  rememberAnalyseClick("intent-1", "policy-a", 0);
  expect(pendingAnalyseClick("intent-1", 15 * 60_000 + 1)).toBeNull();
  expect(pendingAnalyseClick("intent-1", 1)).toBeNull();
});

it("never remembers a click without an agreed policy", () => {
  rememberAnalyseClick("intent-1", "", 0);
  expect(pendingAnalyseClick("intent-1", 1)).toBeNull();
});

describe("readyToResume", () => {
  const ready = {
    armed: true,
    consent: true,
    hasFile: true,
    busy: false,
    submitted: false,
    signedIn: true,
    accessStatus: "ready",
  };

  it("continues once everything is in place and the workspace is ready", () => {
    expect(readyToResume(ready)).toBe(true);
    expect(readyToResume({ ...ready, accessStatus: undefined })).toBe(true);
  });

  it("waits while the workspace reloads after Save (owner, 26 Oct 2026)", () => {
    expect(readyToResume({ ...ready, accessStatus: "loading" })).toBe(false);
    expect(readyToResume({ ...ready, accessStatus: "selecting" })).toBe(false);
  });

  it("never continues without the tick, the file, a session, or while busy", () => {
    expect(readyToResume({ ...ready, armed: false })).toBe(false);
    expect(readyToResume({ ...ready, consent: false })).toBe(false);
    expect(readyToResume({ ...ready, hasFile: false })).toBe(false);
    expect(readyToResume({ ...ready, busy: true })).toBe(false);
    expect(readyToResume({ ...ready, submitted: true })).toBe(false);
    expect(readyToResume({ ...ready, signedIn: false })).toBe(false);
  });
});
