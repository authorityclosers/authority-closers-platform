// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import type { ReportDimension, ReportEvidence } from "./report-contract";
import { SalesSkills } from "./sales-skills";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const dimensions = fixture.report.dimensions as ReportDimension[];
const excerpt: ReportEvidence = {
  segment_id: "fictional-1",
  quote: "Can you tell me more about how you track payments today?",
  start_ms: 4_000,
  end_ms: 9_000,
};

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(
  items: (ReportDimension & { evidence?: ReportEvidence[] })[],
  onSelectEvidence?: (evidence: ReportEvidence) => void,
) {
  await act(async () =>
    root.render(
      <SalesSkills dimensions={items} onSelectEvidence={onSelectEvidence} />,
    ),
  );
}

it("shows all eight skills with a count of what the call showed, never a grade", async () => {
  await render(dimensions);
  const titles = [...container.querySelectorAll("h3")].map(
    (h) => h.textContent,
  );
  expect(titles).toEqual(dimensions.map((d) => d.label));
  const text = container.textContent ?? "";
  expect(text).toContain(
    `0 of ${dimensions.length} skills were seen in this call`,
  );
  expect(text).toContain("Draft observations, not scores.");
  expect(text).not.toMatch(/\d+\s*(%|\/\s*10|points?)\b/i);
  // Without a recording there is nothing to play.
  expect(container.querySelector('button[aria-label^="Play"]')).toBeNull();
});

it("leaves internal coaching references out of the reading view", async () => {
  await render(dimensions, vi.fn());
  // They stay in Raw data; a salesperson does not need them here.
  expect(container.textContent).not.toContain(dimensions[0].citations[0].doc);
  expect(container.textContent).not.toContain("Coaching sources");
});

it("plays the exact excerpt a skill cites and keeps statuses plain", async () => {
  const onSelectEvidence = vi.fn();
  const items = dimensions.map((d, index) =>
    index === 1
      ? {
          ...d,
          status: "observed",
          observation: "Asked about payments.",
          evidence: [excerpt, { ...excerpt, segment_id: "fictional-2" }],
        }
      : index === 2
        ? { ...d, status: "conflicted" }
        : d,
  );
  await render(items, onSelectEvidence);
  expect(container.textContent).toContain(excerpt.quote);
  expect(container.textContent).toContain(
    "1 of 8 skills were seen in this call",
  );
  expect(container.textContent).toContain("Mixed signs");
  const play = container.querySelector<HTMLButtonElement>(
    'button[aria-label^="Play source moment"]',
  )!;
  await act(async () => play.click());
  expect(onSelectEvidence).toHaveBeenCalledWith(excerpt);
  // Further clips wait behind one small control.
  const more = [...container.querySelectorAll("button")].find(
    (button) => button.textContent === "1 more clip",
  )!;
  await act(async () => more.click());
  expect(
    container.querySelectorAll('button[aria-label^="Play source moment"]'),
  ).toHaveLength(2);
});

it("says so when no skill was observed", async () => {
  await render([]);
  expect(container.textContent).toContain(
    "No skill observations were supplied for this call.",
  );
});
