/** Talk time in the sellers' table stays on one line at 363 px (owner's OnePlus). */
import { expect, it } from "vitest";

import { talkShort } from "./team-floor";

it("writes talk time compactly", () => {
  expect(talkShort(0)).toBe("0m");
  expect(talkShort(7 * 60)).toBe("7m");
  expect(talkShort(71 * 60)).toBe("1h 11m");
  expect(talkShort(120 * 60)).toBe("2h 0m");
});
