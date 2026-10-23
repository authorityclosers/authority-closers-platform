import { expect, it } from "vitest";

import { CALL_LIMIT_MINUTES, CALL_LIMIT_SECONDS } from "./call-limit";

// One call-length limit everywhere (owner, 23 Oct 2026: "120 minutes everywhere").
it("is one limit of 120 minutes", () => {
  expect(CALL_LIMIT_MINUTES).toBe(120);
  expect(CALL_LIMIT_SECONDS).toBe(7200);
});
