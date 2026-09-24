import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { SyntheticReportPreview } from "./synthetic-report-preview";
import { syntheticEvidence } from "./synthetic-report";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

function button(label: string) {
  const found = [...container.querySelectorAll("button")].find(
    (item) =>
      item.getAttribute("aria-label") === label ||
      item.textContent?.trim() === label,
  );
  if (!found) throw new Error(`Missing button: ${label}`);
  return found;
}

it("labels the synthetic report, exposes exact evidence through the real skill reader, and never invents a score or audio", async () => {
  await act(async () => root.render(<SyntheticReportPreview />));
  expect(
    container.querySelector("[data-report-modes]")?.getAttribute("data-view"),
  ).toBe("reading");
  expect(
    [
      ...container.querySelectorAll<HTMLElement>("[data-report-mode-section]"),
    ].every((section) => !section.hidden),
  ).toBe(true);
  expect(container.textContent).toContain("Synthetic display only");
  expect(container.textContent).toContain(
    "No recording, account, analysis, or provider call exists here.",
  );
  expect(container.textContent).toContain("Draft observations, not scores.");
  expect(container.querySelector("audio")).toBeNull();
  expect(container.textContent).not.toMatch(
    /\b\d+\s*%|performance score|conversion rate/i,
  );

  await act(async () => button("Tabbed view").click());
  await act(async () => button("Open notes: Human Connection & Trust").click());
  const dialog = container.querySelector('[role="dialog"]');
  expect(dialog?.textContent).toContain(syntheticEvidence.respect.quote);
  expect(dialog?.textContent).toContain("00:31.000–00:35.000");
  await act(async () =>
    button("Listen to Human Connection & Trust excerpt at 00:31.000").click(),
  );
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    syntheticEvidence.respect.quote,
  );
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "No audio exists in this display fixture.",
  );
});

it("keeps the no-next-action outcome explicit in the production next-call plan and selects its source", async () => {
  await act(async () => root.render(<SyntheticReportPreview />));
  await act(async () => button("Tabbed view").click());
  await act(async () => button("Next-call plan").click());
  const outcome = container.querySelector('[aria-label="Call outcome"]');
  expect(outcome?.textContent).toContain(
    "No sale was agreed. The buyer declined a next step",
  );
  await act(async () => button("Listen to call outcome at 00:26.000").click());
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    syntheticEvidence.boundary.quote,
  );
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "Call outcome",
  );
});
