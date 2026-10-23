import { expect, it } from "vitest";

import {
  CALL_LIMIT_MINUTES,
  CALL_LIMIT_SECONDS,
  callLimitMinutes,
} from "./call-limit";

// One call-length limit everywhere (owner, 23 Oct 2026); 60 minutes for now.
it("is one limit, and a plan's card never promises more than it", () => {
  expect(CALL_LIMIT_MINUTES).toBe(60);
  expect(CALL_LIMIT_SECONDS).toBe(3600);
  expect(callLimitMinutes(90)).toBe(60);
  expect(callLimitMinutes(120)).toBe(60);
  expect(callLimitMinutes(45)).toBe(45);
  expect(callLimitMinutes(null)).toBe(60);
});
