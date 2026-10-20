// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { needsWorkShare, normalizeAnalysis, rangeDays } from "./analysis-data";
import { AnalysisPanels } from "./analysis-panels";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const DATA = normalizeAnalysis({
  window: { days: 30 },
  calls_analysed: 17,
  calls_scored: 12,
  said: {
    objections: [{ text: "Price is too high", calls: 4 }],
    questions: [{ text: "Can visits be tracked?", calls: 3 }],
    pains: [],
    goals: [{ text: "More site visits", calls: 2 }],
  },
  commitments: { next_step: 9, follow_up: 6 },
  readings: { interest: [{ text: "High", calls: 8 }], urgency: [] },
  skills: [
    {
      label: "Purpose & Agenda Setting",
      calls: 12,
      average: 45,
      needs_work_share: 0.75,
    },
    {
      label: "Active Listening",
      calls: 12,
      average: 80,
      needs_work_share: 0.1,
    },
  ],
});

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("reads the window and maps the company view's range to days", () => {
  expect(DATA.days).toBe(30);
  expect(DATA.commitments).toEqual({ next_step: 9, follow_up: 6 });
  expect(rangeDays("30d")).toBe(30);
  expect(rangeDays("12m")).toBe(365);
  expect(rangeDays("all")).toBe(365);
  expect(rangeDays("90d")).toBe(90);
  expect(rangeDays("900d")).toBe(365);
});

it("shows what buyers said, commitments and skill scores weakest first", async () => {
  await act(async () => root.render(<AnalysisPanels data={DATA} />));
  const text = host.textContent ?? "";
  expect(text).toContain("17 calls the engine read");
  expect(text).toContain("Price is too high4 calls");
  expect(text).toContain("Can visits be tracked?3 calls");
  expect(text).toContain("None found"); // no pains in this window
  expect(text).toContain("Next step agreed9");
  expect(text).toContain("Prospect promised0");
  expect(text).toContain("InterestHigh 8");
  const skills = [...host.querySelectorAll("tbody tr")].map(
    (row) => row.textContent,
  );
  expect(skills[0]).toContain("Purpose & Agenda Setting");
  expect(skills[0]).toContain("75%");
  expect(skills[1]).toContain("Active Listening");
});

it("leaves the skill scores out when the company view already shows them", async () => {
  await act(async () =>
    root.render(<AnalysisPanels data={DATA} skillsShown />),
  );
  expect(host.textContent).not.toContain("Skill scores");
  expect(host.textContent).toContain("Commitments and readings");
  expect(host.querySelectorAll("tbody tr")).toHaveLength(0);
});

it("weighs the needs-work share by the calls each skill was scored on", () => {
  expect(needsWorkShare(DATA.skills)).toBeCloseTo(0.425);
  expect(
    needsWorkShare([
      { label: "A", calls: 3, average: 40, needsWorkShare: 1 },
      { label: "B", calls: 1, average: 90, needsWorkShare: 0 },
    ]),
  ).toBe(0.75);
  expect(needsWorkShare([])).toBeNull();
});
