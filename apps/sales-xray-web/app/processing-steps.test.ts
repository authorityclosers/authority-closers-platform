import { expect, it } from "vitest";

import {
  formatElapsed,
  projectSteps,
  readLivePlan,
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
