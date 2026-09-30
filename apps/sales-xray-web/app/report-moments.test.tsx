// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  envelope,
  recordingId,
  submissionId,
  transcript as rawTranscript,
} from "../tests/acquisition-fixture";
import {
  parseAcquisitionReport,
  parseTranscript,
  type ReportEvidence,
  type SalesReport,
} from "./report-contract";
import {
  countReportMoments,
  ReportMoments,
  timelineMoments,
} from "./report-moments";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const transcript = parseTranscript(rawTranscript, envelope.source_sha256);
function suppliedReport() {
  return parseAcquisitionReport(
    envelope,
    { submissionId, recordingId },
    transcript,
  ).report;
}
function emptyReport(): SalesReport {
  const report = suppliedReport();
  delete report.overview;
  return {
    ...report,
    strengths: [],
    improvements: [],
    missed_opportunities: [],
    objection_analysis: [],
    closing_analysis: [],
  };
}
function excerpt(index: number): ReportEvidence {
  return {
    segment_id: `synthetic-${index}`,
    quote: `Exact supplied phrase ${index}`,
    start_ms: index * 1_000 + 123,
    end_ms: index * 1_000 + 987,
  };
}
function mixed(): SalesReport {
  return {
    ...emptyReport(),
    strengths: [
      {
        title: "Asked about numbers",
        explanation: "Good discovery",
        evidence: [excerpt(8), excerpt(9)],
      },
    ],
    improvements: [
      {
        title: "Pause after explaining",
        explanation: "Long monologue",
        evidence: [excerpt(3)],
      },
    ],
    missed_opportunities: [
      {
        title: "Missed the pain",
        explanation: "Did not follow up",
        evidence: [excerpt(5)],
      },
    ],
    objection_analysis: [
      {
        title: "Price worry",
        explanation: "Handled briefly",
        evidence: [excerpt(1)],
      },
    ],
    closing_analysis: [
      {
        title: "Next step set",
        explanation: "Agreed a follow-up",
        evidence: [excerpt(12)],
      },
    ],
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}")));
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function render(report: SalesReport, onSelectEvidence = vi.fn()) {
  await act(async () =>
    root.render(
      <ReportMoments report={report} onSelectEvidence={onSelectEvidence} />,
    ),
  );
  return onSelectEvidence;
}
const cards = () =>
  [...container.querySelectorAll<HTMLElement>("[data-moment]")].map(
    (item) => item.querySelector("h4")?.textContent,
  );
const pressed = (label: string) =>
  [
    ...container.querySelectorAll<HTMLButtonElement>('[role="group"] button'),
  ].find((button) => button.textContent?.startsWith(label))!;

it("puts one moment per finding on a single timeline in call order", () => {
  const moments = timelineMoments(mixed());
  expect(moments.map((m) => [m.kind, m.title])).toEqual([
    ["objection", "Price worry"],
    ["change", "Pause after explaining"],
    ["missed", "Missed the pain"],
    ["good", "Asked about numbers"],
    ["closing", "Next step set"],
  ]);
  // Both clips stay with their finding.
  expect(moments[3].evidence).toHaveLength(2);
});

it("marks rewatch picks on the finding that cites the same clip, never inventing one", () => {
  const report = suppliedReport();
  const moments = timelineMoments(report);
  for (const note of report.overview!.rewatch) {
    const clip = note.evidence[0];
    const holder = moments.find((moment) =>
      moment.evidence.some(
        (item) =>
          item.segment_id === clip.segment_id &&
          item.start_ms === clip.start_ms &&
          item.end_ms === clip.end_ms,
      ),
    );
    expect(holder?.listen).toBeDefined();
  }
  // Every moment comes from a finding or a rewatch note in the report.
  const titles = new Set(
    [
      ...report.strengths,
      ...report.improvements,
      ...report.missed_opportunities,
      ...report.objection_analysis,
      ...report.closing_analysis,
    ]
      .map((f) => f.title)
      .concat(report.overview!.rewatch.map((r) => r.text)),
  );
  expect(moments.every((moment) => titles.has(moment.title))).toBe(true);
});

it("shows each moment with its label, words and a play control for the exact clip", async () => {
  const onSelectEvidence = await render(mixed());
  expect(cards()).toEqual([
    "Price worry",
    "Pause after explaining",
    "Missed the pain",
    "Asked about numbers",
    "Next step set",
  ]);
  expect(container.textContent).toContain("Exact supplied phrase 3");
  const play = container.querySelector<HTMLButtonElement>(
    '[data-moment="improvement:0"] button[aria-label^="Play"]',
  )!;
  await act(async () => play.click());
  expect(onSelectEvidence).toHaveBeenCalledWith(
    excerpt(3),
    "Pause after explaining",
  );
  // The second clip of a finding waits behind a disclosure.
  expect(container.textContent).toContain("1 more clip for this moment");
});

it("filters by kind and jumps from the call map", async () => {
  await render(mixed());
  await act(async () => pressed("To change").click());
  expect(cards()).toEqual(["Pause after explaining"]);
  await act(async () => pressed("All").click());
  expect(cards()).toHaveLength(5);
  const scroll = vi.fn();
  HTMLElement.prototype.scrollIntoView = scroll;
  const pin = container.querySelector<HTMLButtonElement>(
    'button[aria-label^="Closing at"]',
  )!;
  await act(async () => {
    pin.click();
    await new Promise((resolve) => requestAnimationFrame(resolve));
  });
  expect(
    container
      .querySelector('[data-moment="closing:0"]')
      ?.hasAttribute("data-flash"),
  ).toBe(true);
  expect(scroll).toHaveBeenCalled();
});

it("says so when the report points to no moment, and keeps guest counts", async () => {
  const counts = (hidden: number) => ({
    visible_count: 0,
    total_count: hidden,
    hidden_count: hidden,
  });
  await render({
    ...emptyReport(),
    preview: {
      version: "guest-findings-v1",
      sections: {
        strengths: counts(1),
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
  });
  expect(container.textContent).toContain(
    "This report did not point to any moment in the call.",
  );
  expect(container.textContent).toContain(
    "3 more moments are saved for your account.",
  );
  expect(container.querySelector('button[aria-label^="Play"]')).toBeNull();
});

it("exports a pure count of the replay dataset, excluding missing excerpts", () => {
  const detailed = suppliedReport();
  const uniqueRanges = new Set(
    detailed.overview!.rewatch.flatMap((moment) =>
      moment.evidence.map(
        ({ segment_id, start_ms, end_ms }) =>
          `${segment_id}:${start_ms}:${end_ms}`,
      ),
    ),
  );
  expect(countReportMoments(detailed)).toBe(uniqueRanges.size);
  const report = {
    ...mixed(),
    improvements: [
      {
        title: "Unlinked finding",
        explanation: "No excerpt attached",
        evidence: [],
      },
    ],
  };
  const before = JSON.stringify(report);
  expect(countReportMoments(report)).toBe(5);
  expect(JSON.stringify(report)).toBe(before);
  expect(countReportMoments(emptyReport())).toBe(0);
});

it("keeps distinct source segments and clock ranges separate when phrases repeat", () => {
  const original = excerpt(1);
  const report = {
    ...emptyReport(),
    strengths: [
      {
        title: "Repeated phrase",
        explanation: "Each source occurrence matters",
        evidence: [
          original,
          { ...original, segment_id: "different-segment" },
          { ...original, start_ms: 1_200 },
          { ...original, end_ms: 1_900 },
        ],
      },
    ],
  };
  expect(countReportMoments(report)).toBe(4);
});
