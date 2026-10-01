import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { SyntheticReportPreview } from "./synthetic-report-preview";
import { syntheticEvidence } from "./synthetic-report";
import fixture from "../../../tests/fixtures/call-map-v1.json";
import { formatTranscriptTime } from "../../report-transcript";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  window.history.replaceState(null, "", "/");
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
  expect(container.textContent).toContain("Who talked most: Buyer (60%)");
  expect(container.textContent).not.toMatch(
    /performance score|conversion rate/i,
  );
  const withoutCallNumbers = container.cloneNode(true) as HTMLDivElement;
  withoutCallNumbers.querySelector('[aria-label="Call numbers"]')?.remove();
  withoutCallNumbers.querySelector("[data-call-map-fixture]")?.remove();
  expect(withoutCallNumbers.textContent).not.toMatch(/\b\d+\s*%/);

  await act(async () => button("Tabbed view").click());
  await act(async () => button("Sales skills").click());
  const skills = container.querySelector('[data-report-mode-section="skills"]');
  expect(skills?.hasAttribute("hidden")).toBe(false);
  expect(skills?.textContent).toContain(syntheticEvidence.respect.quote);
  expect(skills?.textContent).toContain("00:31–00:35");
  // Skills read inline: no notes dialog, one play control per excerpt.
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  await act(async () =>
    skills!
      .querySelector<HTMLButtonElement>(
        'button[aria-label="Play source moment, 00:31 to 00:35"]',
      )!
      .click(),
  );
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    syntheticEvidence.respect.quote,
  );
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "No audio exists in this display fixture.",
  );
});

it("adds a parsed call-map fixture and resolves every source control to its own dialogue", async () => {
  await act(async () => root.render(<SyntheticReportPreview />));
  await act(async () => button("Tabbed view").click());
  await act(async () => button("Call-map fixture").click());
  const panel = container.querySelector(
    '[data-report-mode-section="call-map-fixture"]',
  )!;
  expect(panel.hasAttribute("hidden")).toBe(false);
  expect(panel.textContent).toContain("Fictional call-map fixture");
  expect(panel.textContent).toContain(fixture.call_map.verdict_line);
  for (const heading of [
    "Timeline phases",
    "Outcome & Next steps",
    "Signals",
    "Customer pains",
    "Pitch items",
    "Money mentions",
    "Claims",
    "Qualification",
    "Time promise & Overrun",
  ]) {
    expect(panel.textContent).toContain(heading);
  }
  expect(panel.textContent).toContain("follow_up");
  expect(panel.textContent).toContain("dated_call");
  for (const items of [
    fixture.call_map.signals,
    fixture.call_map.pains,
    fixture.call_map.pitch_items,
    fixture.call_map.claims,
  ]) {
    for (const item of items) expect(panel.textContent).toContain(item.text);
  }
  expect(panel.textContent).toContain("180 credits per month");
  expect(panel.textContent).toContain("120 credits");
  for (const gap of fixture.call_map.qualification_gaps)
    expect(panel.textContent).toContain(gap);
  for (const confirmed of fixture.call_map.qualification_confirmed)
    expect(panel.textContent).toContain(confirmed.item);
  expect(panel.textContent).toContain("Time promised10:00");
  expect(panel.textContent).toContain("Time used00:43");
  expect(panel.textContent).toContain("No overrun");
  const source = panel.querySelector('[aria-label="Call-map fixture source"]')!;
  const visited = new Set<string>();
  for (const control of panel.querySelectorAll<HTMLButtonElement>("button")) {
    const timestamp = control
      .getAttribute("aria-label")!
      .match(/\d{2}:\d{2}/)![0];
    const segment = fixture.segments.find(
      (s) => formatTranscriptTime(s.start_ms) === timestamp,
    )!;
    expect(segment).toBeDefined();
    await act(async () => control.click());
    expect(source.textContent).toContain(segment.id);
    expect(source.textContent).toContain(segment.text);
    expect(source.textContent).toContain(`Selected ${timestamp}`);
    visited.add(segment.id);
  }
  expect([...visited].sort()).toEqual([
    "s1",
    "s2",
    "s4",
    "s5",
    "s6",
    "s7",
    "s8",
  ]);
  expect(source.textContent).not.toContain(syntheticEvidence.respect.quote);
  expect(panel.querySelector("audio")).toBeNull();
  await act(async () => button("Overview").click());
  expect(
    container
      .querySelector('[data-report-mode-section="overview"]')
      ?.hasAttribute("hidden"),
  ).toBe(false);
});

it("keeps the no-next-action outcome explicit in the production next-call plan and selects its source", async () => {
  await act(async () => root.render(<SyntheticReportPreview />));
  await act(async () => button("Tabbed view").click());
  await act(async () => button("Next-call plan").click());
  const outcome = container.querySelector('[aria-label="Call outcome"]');
  expect(outcome?.textContent).toContain(
    "No sale was agreed. The buyer declined a next step",
  );
  await act(async () => button("Listen to call outcome at 00:26").click());
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    syntheticEvidence.boundary.quote,
  );
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "Call outcome",
  );
});
