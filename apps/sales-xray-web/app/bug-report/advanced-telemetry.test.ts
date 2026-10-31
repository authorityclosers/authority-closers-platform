import { expect, it } from "vitest";

import type { TrailStep } from "../telemetry";
import { callTimings, stepWords, stepsFrom } from "./advanced-telemetry";

const at = "2026-10-31T04:30:00.000Z";

it("turns the app's trail into the steps a person took, repeats folded", () => {
  const trail: TrailStep[] = [
    { event: "sx.screen_viewed", at, detail: { screen: "leads" } },
    { event: "sx.api_timing", at },
    { event: "sx.tap", at, detail: { target: "row", screen: "leads" } },
    { event: "sx.screen_viewed", at, detail: { screen: "lead" } },
    {
      event: "sx.lead_stage_moved",
      at,
      detail: { via: "sheet", to_kind: "interested" },
    },
    { event: "sx.tap", at, detail: { target: "button", screen: "lead" } },
    { event: "sx.tap", at, detail: { target: "button", screen: "lead" } },
    { event: "sx.error_shown", at },
  ];
  expect(stepsFrom(trail)).toEqual([
    "Open Leads",
    "Tap a row on Leads",
    "Open a lead",
    "Move a lead to Interested (sheet)",
    "Tap a button on a lead, 2 times",
    "See an error message",
  ]);
  expect(stepsFrom(trail, 2)).toEqual([
    "Tap a button on a lead, 2 times",
    "See an error message",
  ]);
  // Not the app's own event: not a step.
  expect(stepWords({ event: "bug_report_opened", at })).toBeNull();
  expect(stepWords({ event: "sx.web_vital", at })).toBeNull();
});

it("lists failed calls from recent problems, with their request references", () => {
  const calls = callTimings([
    {
      at,
      kind: "http",
      status: 500,
      method: "POST",
      path: "/v1/lead-desk/leads/:id/stage",
      reference: "req_1234",
    },
    { at, kind: "console", message: "boom" },
  ]);
  expect(calls[0]).toEqual({
    method: "POST",
    path: "/v1/lead-desk/leads/:id/stage",
    status: 500,
    reference: "req_1234",
    failed: true,
  });
  expect(calls.filter((call) => call.failed)).toHaveLength(1);
});
