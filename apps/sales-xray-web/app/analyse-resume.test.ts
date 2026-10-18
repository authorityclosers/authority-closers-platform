import { afterEach, expect, it } from "vitest";

import {
  forgetAnalyseClick,
  pendingAnalyseClick,
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
