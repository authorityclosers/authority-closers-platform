// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import fixture from "../tests/fixtures/dipak-overview.json";
import { NextCallPlan } from "./next-call-plan";
import type { SalesReport, Transcript } from "./report-contract";
import { saveSpeakerProfiles } from "./speaker-profiles";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const report = fixture.report as SalesReport;
const overview = report.overview!;

beforeEach(() => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}")));
  localStorage.clear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

const text = () => container.textContent?.replace(/\s+/g, " ") ?? "";

it("leads with one move, then keep, change with words to try first, and care notes", async () => {
  await act(async () =>
    root.render(<NextCallPlan report={report} onSelectEvidence={vi.fn()} />),
  );
  const all = text();
  const order = [
    overview.next_call_focus!.behavior,
    overview.next_call_focus!.target,
    overview.practice!.instructions,
    report.strengths[0].explanation,
    overview.strength_details[0].why_it_matters,
    // The action to try leads; the reason follows.
    overview.improvement_details[0].replacement_behavior,
    overview.improvement_details[0].why_it_matters,
    overview.ethics_notes[0].text,
  ].map((value) => all.indexOf(value.replace(/\s+/g, " ")));
  expect(order.every((at) => at >= 0)).toBe(true);
  expect([...order].sort((a, b) => a - b)).toEqual(order);
  // The report's missing inputs are named; no impact figure is invented.
  expect(all).toContain("Comparable conversion history, Lead volume");
  // No fake progress and no practice recorder.
  expect(all).not.toMatch(/progress|streak|score/i);
  expect(
    container.querySelector("input, textarea, [data-recorder]"),
  ).toBeNull();
});

it("plays the exact supplied evidence", async () => {
  const onSelectEvidence = vi.fn();
  await act(async () =>
    root.render(
      <NextCallPlan report={report} onSelectEvidence={onSelectEvidence} />,
    ),
  );
  const evidence = report.strengths[0].evidence[0];
  const play = [...container.querySelectorAll("button")].find((button) =>
    button.getAttribute("aria-label")?.startsWith("Play"),
  )!;
  await act(async () => play.click());
  expect(onSelectEvidence).toHaveBeenCalledWith(
    evidence,
    report.strengths[0].title,
  );
  expect(text()).toContain(evidence.quote.replace(/\s+/g, " "));
});

it("says what is missing instead of inventing coaching or playback", async () => {
  const bare: SalesReport = {
    ...report,
    overview: undefined,
    strengths: [],
    improvements: [],
    closing_analysis: [],
  };
  await act(async () =>
    root.render(<NextCallPlan report={bare} onSelectEvidence={vi.fn()} />),
  );
  expect(text()).toContain("This report did not set a next-call focus.");
  expect(text()).toContain("No strength was recorded for this call.");
  expect(text()).toContain("No change was suggested for this call.");
  expect(text()).not.toContain("Handle with care");
  expect(
    [...container.querySelectorAll("button")].some((button) =>
      button.getAttribute("aria-label")?.startsWith("Play"),
    ),
  ).toBe(false);
});

it("shows only counts for findings a guest has not unlocked", async () => {
  const counts = (hidden: number) => ({
    visible_count: 0,
    total_count: hidden,
    hidden_count: hidden,
  });
  const guest: SalesReport = {
    ...report,
    improvements: [],
    preview: {
      version: "guest-findings-v1",
      sections: {
        strengths: counts(0),
        improvements: counts(2),
        missed_opportunities: counts(0),
        objection_analysis: counts(0),
        closing_analysis: counts(0),
        golden_moments: counts(0),
        prospect_interpretations: counts(0),
        rewatch: counts(0),
        ethics_notes: counts(0),
      },
    },
  };
  const onUnlock = vi.fn();
  await act(async () =>
    root.render(
      <NextCallPlan
        report={guest}
        onSelectEvidence={vi.fn()}
        onUnlock={onUnlock}
      />,
    ),
  );
  expect(text()).toContain("2 more changes are saved for your account.");
  expect(text()).not.toContain(report.improvements[0].title);
  const unlock = [...container.querySelectorAll("button")].find(
    (button) => button.textContent === "Unlock with a free account",
  )!;
  await act(async () => unlock.click());
  expect(onUnlock).toHaveBeenCalled();
});

it("lists the salesperson's promises once roles are known, with a tick", async () => {
  const transcript: Transcript = {
    source_sha256: "0".repeat(64),
    revision: "fictional-r1",
    timebase_id: "1ms",
    duration_ms: 60_000,
    segments: [
      {
        id: "a",
        speaker_id: "alex",
        start_ms: 0,
        end_ms: 5_000,
        text: "I'll send the brochure today.",
      },
      {
        id: "b",
        speaker_id: "sam",
        start_ms: 5_000,
        end_ms: 9_000,
        text: "Okay, thanks.",
      },
    ],
  };
  saveSpeakerProfiles("fictional-plan", {
    alex: { name: "Alex", role: "salesperson", icon: null },
    sam: { name: "Sam", role: "prospect", icon: null },
  });
  await act(async () =>
    root.render(
      <NextCallPlan
        report={report}
        onSelectEvidence={vi.fn()}
        callId="fictional-plan"
        transcript={transcript}
      />,
    ),
  );
  expect(text()).toContain("I'll send the brochure today.");
  const tick = container.querySelector<HTMLButtonElement>(
    'button[aria-label="Mark as done"]',
  )!;
  await act(async () => tick.click());
  expect(
    container.querySelector('button[aria-label="Mark as not done"]'),
  ).not.toBeNull();
});
