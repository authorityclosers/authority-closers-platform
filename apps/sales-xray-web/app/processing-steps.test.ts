import { expect, it } from "vitest";

import {
  formatElapsed,
  livePlanFromProgress,
  projectSteps,
  readLivePlan,
  serverStartedAt,
  serverStepDuration,
  stepIndexForStage,
} from "./processing-steps";

const plan = (stage: string | null, state = "active", reportReady = false) => ({
  stage,
  state,
  reportReady,
});

it("maps the plan's stage to the three steps", () => {
  expect(
    ["C0", "C1", "C2", "C3", "C4", "C5", "C6"].map(stepIndexForStage),
  ).toEqual([0, 0, 0, 1, 1, 2, 2]);
  expect(stepIndexForStage(null)).toBeNull();
  expect(stepIndexForStage("C9")).toBeNull();
});

it("reads only the plan fields it needs; anything odd is unknown", () => {
  expect(
    readLivePlan({ state: "active", current_stage: "C3", report_ready: false }),
  ).toEqual(plan("C3"));
  expect(readLivePlan({ state: "active", current_stage: "C42" })).toEqual(
    plan(null),
  );
  expect(readLivePlan({ current_stage: "C3" })).toBeNull();
  expect(readLivePlan(null)).toBeNull();
});

it("moves the steps with the plan: done, now, waiting", () => {
  const steps = (p: ReturnType<typeof plan> | null, extra = {}) =>
    projectSteps({
      plan: p,
      rows: [],
      attention: false,
      hasReport: false,
      ...extra,
    });
  expect(steps(plan("C1"))).toEqual(["active", "waiting", "waiting"]);
  expect(steps(plan("C4"))).toEqual(["done", "active", "waiting"]);
  expect(steps(plan("C6"))).toEqual(["done", "done", "active"]);
  expect(steps(plan("C5", "held"))).toEqual(["done", "done", "attention"]);
  expect(steps(plan("C5", "completed"))).toEqual(["done", "done", "done"]);
  expect(steps(plan("C5", "active", true))).toEqual(["done", "done", "done"]);
  expect(steps(plan("C3"), { attention: true })).toEqual([
    "done",
    "attention",
    "waiting",
  ]);
});

it("falls back to the task rows when there is no plan", () => {
  expect(
    projectSteps({
      plan: null,
      rows: [
        { stage: "C2", state: "completed" },
        { stage: "C4", state: "running" },
        { stage: "C5", state: null },
      ],
      attention: false,
      hasReport: false,
    }),
  ).toEqual(["done", "active", "waiting"]);
  // A later step that started means the earlier one is behind it.
  expect(
    projectSteps({
      plan: null,
      rows: [{ stage: "C5", state: "running" }],
      attention: false,
      hasReport: false,
    }),
  ).toEqual(["done", "done", "active"]);
  expect(
    projectSteps({
      plan: null,
      rows: [
        { stage: "C2", state: "completed" },
        { stage: "C4", state: "uncertain" },
      ],
      attention: true,
      hasReport: false,
    }),
  ).toEqual(["done", "attention", "waiting"]);
});

it("formats measured durations plainly", () => {
  expect(formatElapsed(48_000)).toBe("0:48");
  expect(formatElapsed(125_400)).toBe("2:05");
  expect(formatElapsed(3_730_000)).toBe("1:02:10");
  expect(formatElapsed(-5)).toBe("0:00");
});

const row = (
  stage: string,
  started: string | null,
  finished: string | null,
) => ({
  stage,
  state: finished ? "completed" : "running",
  started_at: started ? `2026-10-10T12:${started}Z` : null,
  finished_at: finished ? `2026-10-10T12:${finished}Z` : null,
});

it("times each step by the server's clock, only when both ends were recorded", () => {
  const rows = [
    row("C0", null, "00:05"),
    row("C1", "00:05", "00:20"),
    row("C2", "00:20", "01:25"),
    // C3 records no start; C4 starts and finishes.
    row("C3", null, "01:30"),
    row("C4", "01:30", "02:40"),
    row("C5", "02:40", null),
  ];
  expect(serverStepDuration(rows, 0)).toBe(80_000); // 00:05 to 01:25
  expect(serverStepDuration(rows, 1)).toBe(70_000); // 01:30 to 02:40
  expect(serverStepDuration(rows, 2)).toBeNull(); // not finished
  expect(serverStepDuration(undefined, 0)).toBeNull();
  expect(serverStartedAt(rows)).toBe(Date.parse("2026-10-10T12:00:05Z"));
  expect(serverStartedAt([row("C0", null, null)])).toBeNull();
});

it("reads the live stage from the progress read on newer servers only", () => {
  const base = {
    state: "active",
    local_state: "completed",
    failure_code: null,
    has_report: false,
    automatic_progression: true,
    stages: [],
  };
  expect(livePlanFromProgress(base)).toBeNull();
  expect(livePlanFromProgress({ ...base, current_stage: "C4" })).toEqual({
    state: "active",
    stage: "C4",
    reportReady: false,
  });
  expect(
    livePlanFromProgress({
      ...base,
      current_stage: "C3",
      run_state: "failed",
    })?.state,
  ).toBe("failed");
  expect(
    livePlanFromProgress({
      ...base,
      current_stage: "C6",
      terminal_state: "done",
    })?.reportReady,
  ).toBe(true);
});
