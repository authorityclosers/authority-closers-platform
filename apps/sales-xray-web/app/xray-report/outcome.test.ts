import { expect, it } from "vitest";

import { callNextDate } from "./outcome";

const step = (date: string | null) => ({
  text: "Call back with the proposal",
  date,
  owner: null,
  source: null,
});

it("shows the call's own next step date, as said, when the analysis has none (3 Nov 2026 regression, R6)", () => {
  expect(
    callNextDate({
      date: null,
      nextSteps: [step(null), step("Saturday 11 AM")],
    }),
  ).toBe("Saturday 11 AM");
  expect(
    callNextDate({ date: "12 Nov", nextSteps: [step("Saturday 11 AM")] }),
  ).toBe("12 Nov");
  expect(callNextDate({ date: null, nextSteps: [step(null)] })).toBeNull();
  expect(callNextDate({ date: null, nextSteps: [] })).toBeNull();
});
