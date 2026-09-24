import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../tests/fixtures/dipak-overview.json";
import { NextCallPlan } from "./next-call-plan";
import { ReportReadingProvider } from "./report-reading-context";
import type { SalesReport } from "./report-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
const report = fixture.report as SalesReport;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
function button(text: string) {
  const found = [
    ...container.querySelectorAll<HTMLButtonElement>("button"),
  ].find(
    (item) =>
      item.getAttribute("aria-label") === text ||
      item.textContent?.replace(/\s+/g, " ").trim() === text,
  );
  if (!found) throw new Error(`Missing ${text}`);
  return found;
}
it("shows source-backed keep, change and practice without fake progress or a practice recorder", async () => {
  await act(async () =>
    root.render(<NextCallPlan report={report} onSelectEvidence={vi.fn()} />),
  );
  expect(container.textContent).toContain(report.strengths[0].explanation);
  expect(container.textContent).toContain(
    report.overview!.next_call_focus!.behavior,
  );
  expect(container.textContent).toContain(
    report.overview!.practice!.instructions,
  );
  expect(
    container.querySelector('[aria-label="Call outcome"]')?.textContent,
  ).toContain(report.overview!.outcome!.text);
  expect(container.querySelector('input[type="checkbox"]')).toBeNull();
  expect(container.textContent).not.toContain("Start practice");
  await act(async () => button("Change").click());
  expect(
    container.querySelector('article[data-active="true"]')?.textContent,
  ).toContain("Change first");
});
it("plays exact supplied evidence and exposes all full notes in a bounded reader", async () => {
  const select = vi.fn();
  await act(async () =>
    root.render(<NextCallPlan report={report} onSelectEvidence={select} />),
  );
  const evidence = report.improvements[0].evidence[0];
  const outcomeEvidence = report.overview!.outcome!.evidence[0];
  await act(async () => button(`Listen to call outcome at 00:03.500`).click());
  expect(select).toHaveBeenCalledWith(outcomeEvidence, "Call outcome");
  select.mockClear();
  await act(async () =>
    button(
      `Play source moment, ${evidence.start_ms} to ${evidence.end_ms}`,
    ).click(),
  );
  expect(select).toHaveBeenCalledWith(evidence, report.improvements[0].title);
  const opener = button("Read full notes : Change first");
  opener.focus();
  await act(async () => opener.click());
  const dialog = container.querySelector('[role="dialog"]')!;
  expect(dialog.textContent).toContain(
    report.overview!.next_call_focus!.target,
  );
  expect(dialog.textContent).toContain(evidence.quote);
  await act(async () => button("Next").click());
  expect(dialog.textContent).toContain(
    report.overview!.practice!.success_condition,
  );
  expect(button("Next").disabled).toBe(true);
  await act(async () => button("Close plan notes").click());
  expect(document.activeElement).toBe(opener);
});
it("does not invent coaching or playback when source fields are absent", async () => {
  const empty = {
    ...report,
    strengths: [],
    improvements: [],
    overview: undefined,
    preview: undefined,
  };
  await act(async () =>
    root.render(<NextCallPlan report={empty} onSelectEvidence={vi.fn()} />),
  );
  expect(container.textContent).toContain("No supported strength was supplied");
  expect(container.textContent).toContain(
    "No supported improvement was supplied",
  );
  expect(container.textContent).toContain(
    "No practice instructions were supplied",
  );
  expect(container.textContent).toContain(
    "No timed source moment was supplied",
  );
  expect(container.querySelector('[aria-label="Call outcome"]')).toBeNull();
  expect(
    container.querySelector('[aria-label^="Play source moment"]'),
  ).toBeNull();
});

it("renders every plan section and source in reading mode while retaining evidence seeking", async () => {
  const select = vi.fn();
  await act(async () =>
    root.render(
      <ReportReadingProvider reading>
        <NextCallPlan report={report} onSelectEvidence={select} />
      </ReportReadingProvider>,
    ),
  );
  expect(container.querySelectorAll("article")).toHaveLength(3);
  expect(
    container.querySelectorAll('article[data-active="true"]'),
  ).toHaveLength(1);
  expect(container.textContent).toContain(
    report.overview!.next_call_focus!.target,
  );
  expect(container.textContent).toContain(
    report.overview!.practice!.success_condition,
  );
  expect(container.querySelectorAll("button[hidden]")).toHaveLength(3);
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  const evidence = report.improvements[0].evidence[0];
  expect(container.textContent).toContain(evidence.quote);
  await act(async () =>
    button(
      `Play source moment, ${evidence.start_ms} to ${evidence.end_ms}`,
    ).click(),
  );
  expect(select).toHaveBeenCalledWith(evidence, report.improvements[0].title);
});
