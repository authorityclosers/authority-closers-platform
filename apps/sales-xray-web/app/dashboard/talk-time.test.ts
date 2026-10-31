import { expect, it } from "vitest";

import { talkOrDash } from "./talk-time";

const minutes = (seconds: number) => `${Math.round(seconds / 60)} min`;

it("shows the phone's talk time, and a dash when only time away is known", () => {
  expect(talkOrDash(180, 60, minutes)).toBe("3 min");
  expect(talkOrDash(0, 60, minutes)).toBe("—");
  expect(talkOrDash(0, 0, minutes)).toBe("0 min");
  expect(talkOrDash(0, undefined, minutes)).toBe("0 min");
});
