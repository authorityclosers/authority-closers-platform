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
const tabs = () => [
  ...container.querySelectorAll<HTMLButtonElement>('[role="tab"]'),
];
const panel = () => container.querySelector<HTMLElement>('[role="tabpanel"]')!;

it("lists every skill, shows one at a time, and counts what the call showed", async () => {
  await render(dimensions);
  expect(tabs().map((tab) => tab.textContent)).toEqual(
    dimensions.map((d) => d.label),
  );
  expect(tabs()[0].getAttribute("aria-selected")).toBe("true");
  expect(panel().querySelector("h3")?.textContent).toBe(dimensions[0].label);
  const text = container.textContent ?? "";
  expect(text).toContain(
    `0 of ${dimensions.length} skills were seen in this call`,
  );
  expect(text).toContain("Draft observations, not scores.");
  expect(text).not.toMatch(/\d+\s*(%|\/\s*10|points?)\b/i);
  // Without a recording there is nothing to play.
  expect(container.querySelector('button[aria-label^="Play"]')).toBeNull();
});

it("leaves internal coaching references out", async () => {
  await render(dimensions, vi.fn());
  expect(container.textContent).not.toContain(dimensions[0].citations[0].doc);
  expect(container.textContent).not.toContain("Coaching sources");
});

it("moves between skills by click, arrow keys and next/previous, and plays exact clips", async () => {
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
  expect(container.textContent).toContain(
    "1 of 8 skills were seen in this call",
  );
  await act(async () => tabs()[1].click());
  expect(panel().querySelector("h3")?.textContent).toBe(items[1].label);
  expect(panel().textContent).toContain(
    "Seen in this call · 2 clips from the call",
  );
  expect(panel().textContent).toContain(excerpt.quote);
  const play = panel().querySelector<HTMLButtonElement>(
    'button[aria-label^="Play source moment"]',
  )!;
  await act(async () => play.click());
  expect(onSelectEvidence).toHaveBeenCalledWith(excerpt);

  await act(async () =>
    tabs()[1].dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
    ),
  );
  expect(tabs()[2].getAttribute("aria-selected")).toBe("true");
  expect(panel().textContent).toContain("Mixed signs");
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('button[aria-label="Previous skill"]')!
      .click(),
  );
  expect(tabs()[1].getAttribute("aria-selected")).toBe("true");
});

it("says so when no skill was observed", async () => {
  await render([]);
  expect(container.textContent).toContain(
    "No skill observations were supplied for this call.",
  );
});
