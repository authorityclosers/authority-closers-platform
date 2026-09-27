import { expect, it } from "vitest";
import type { Progress } from "./acquisition-client";
import { projectProcessing } from "./processing-state";

const baseline: Progress = {
  state: "active",
  local_state: "completed",
  failure_code: null,
  has_report: false,
  automatic_progression: true,
  stages: [
    { stage: "C2", state: "completed" },
    { stage: "C4", state: "running" },
  ],
};

it("does not promote a completed C4 chunk or its superseded uncertain attempt to a final result", () => {
  const partial = {
    ...baseline,
    stages: [
      ...baseline.stages,
      { stage: "C4", state: "uncertain" },
      { stage: "C4", state: "completed" },
    ],
  };
  const view = projectProcessing(partial, false);
  expect(view.rows[1].label).toBe("Work saved");
  expect(view.attention).toBe(false);
  expect(view.title).toBe("Waiting for the next stage");
  expect(view.savedEvidence).toBe(true);
  expect(view.rows[2].label).toBe("Not started");
});
it("does not call queued work running", () => {
  const view = projectProcessing(
    { ...baseline, stages: [{ stage: "C2", state: "queued" }] },
    false,
  );
  expect(view.title).toBe("Waiting to start transcript");
  expect(view.rows[0].label).toBe("Queued");
});
it("conservatively projects unknown server states", () => {
  expect(
    projectProcessing({ ...baseline, state: "future-state" }, false).title,
  ).toBe("Checking analysis status");
  expect(
    projectProcessing(
      { ...baseline, stages: [{ stage: "C4", state: "future-state" }] },
      false,
    ).rows[1].label,
  ).toBe("Status needs checking");
});
it("distinguishes a published report awaiting validated retrieval from display readiness", () => {
  const view = projectProcessing(
    { ...baseline, state: "completed", has_report: true },
    false,
  );
  expect(view.title).toBe("Opening your report");
  expect(view.attention).toBe(false);
  expect(view).not.toHaveProperty("reportReady");
});
it("does not advance a two-hour wait or mutate repeated server facts", () => {
  const original = structuredClone(baseline);
  const initial = projectProcessing(baseline, false);
  for (let poll = 0; poll < 2400; poll++)
    expect(projectProcessing(structuredClone(baseline), false)).toEqual(
      initial,
    );
  expect(baseline).toEqual(original);
  expect(JSON.stringify(initial)).not.toMatch(/percent|eta|remaining_seconds/);
});
it("keeps held and failed states ahead of approval or normal active wording", () => {
  expect(projectProcessing({ ...baseline, state: "held" }, true).title).toBe(
    "Analysis paused",
  );
  expect(
    projectProcessing({ ...baseline, local_state: "failed" }, true).title,
  ).toBe("Your call needs attention");
  expect(
    projectProcessing(
      { ...baseline, stages: [{ stage: "C2", state: "uncertain" }] },
      false,
    ).savedTranscript,
  ).toBe(false);
});
