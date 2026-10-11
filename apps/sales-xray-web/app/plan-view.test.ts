import { expect, it } from "vitest";

import { planView } from "./plan-view";

it("asks for consent on a live quote and shows progress once accepted", () => {
  expect(planView({ accepted: false }, { run_state: "queued" })).toEqual({
    consent: true,
    showProgress: false,
  });
  expect(planView({ accepted: true }, { run_state: "working" })).toEqual({
    consent: false,
    showProgress: true,
  });
  // No plan yet (or an older server): the progress panel, never consent.
  expect(planView(null, null)).toEqual({ consent: false, showProgress: true });
});

it("shows Failed / Try again, not Ready to continue, for an expired quote", () => {
  expect(planView({ accepted: false }, { run_state: "failed" })).toEqual({
    consent: false,
    showProgress: true,
  });
  // Older servers send no run state: the quote still asks for consent.
  expect(planView({ accepted: false }, {})).toEqual({
    consent: true,
    showProgress: false,
  });
});
