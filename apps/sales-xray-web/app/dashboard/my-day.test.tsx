import { expect, it } from "vitest";

import { becauseLine } from "./my-day-client";

// Home is Dipak's six blocks (handoff, 31 Oct 2026): what used to be tested
// here through Home (targets, next up, the team pool) is no longer on it;
// seller-home.test.tsx covers Home.
it("words why a lead is there, biggest reason first", () => {
  expect(becauseLine(["promised a call back", "2 h overdue"])).toBe(
    "Promised a call back · 2 h overdue",
  );
  expect(becauseLine([])).toBe("");
});
