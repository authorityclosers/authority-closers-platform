import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DipakOverview } from "./dipak-overview";
import fixture from "../tests/fixtures/dipak-overview.json";
import { parseJobResponse } from "./report-contract";
import type { Finding, SalesReport } from "./report-contract";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let container: HTMLDivElement;
const select = vi.fn();
function finding(title: string, start: number): Finding {
  return {
    title,
    explanation: `Saved explanation for ${title}`,
    evidence: [
      {
        segment_id: `s${start}`,
        start_ms: start,
        end_ms: start + 900,
        quote: "कल follow-up करूया — <script>not executable</script>",
      },
    ],
  };
}
function report(): SalesReport {
  return {
    summary: "A saved call summary.",
    strengths: [finding("Repeat this", 1000), finding("Keep this", 2000)],
    missed_opportunities: [finding("Explore this", 3000)],
    improvements: [
      finding("Ask before presenting", 4000),
      finding("Confirm the time", 5000),
      finding("Check understanding", 6000),
    ],
    objection_analysis: [],
    closing_analysis: [],
    verdict: "One source-reviewed next action.",
    review_status: "draft_not_dipak_adjudicated",
    source_label: "Synthetic",
    source_sha256: "00".repeat(32),
    transcript_revision: "synthetic-r1",
    dimensions: [
      {
        dimension_id: "discovery",
        label: "Discovery",
        status: "insufficient_evidence",
        observation: "No approved assessment yet.",
        citations: [{ doc: "Doc-1", sections: ["Discovery"] }],
      },
    ],
    report_sections: [],
  };
}
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  select.mockClear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
async function render(value = report()) {
  await act(async () =>
    root.render(<DipakOverview report={value} onSelectEvidence={select} />),
  );
}

it("presents the supplied priorities and one focus without generating scores, estimates or history", async () => {
  const value = report();
  await render(value);
  expect(
    [...container.querySelectorAll("[data-review-point]")].map((node) =>
      node.getAttribute("data-review-point"),
    ),
  ).toEqual([
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "10",
    "11",
    "12",
    "14",
  ]);
  expect(
    container.querySelector('[data-review-point="11"] h4')?.textContent,
  ).toBe(value.improvements[0].title);
  expect(
    container.querySelector('[data-review-point="12"]')?.textContent,
  ).toContain("no separately assessed drill");
  expect(container.textContent).toContain(
    "Insufficient data for a reliable estimate.",
  );
  expect(container.textContent).toContain(
    "A first breakpoint and its cause-and-effect sequence have not been established",
  );
  expect(container.textContent).not.toMatch(
    /XX|per 100|PASS|CONCERN|FAIL|\+\d+%|Overall Score/,
  );
  expect(container.querySelector('[data-review-point="13"]')).toBeNull();
  for (const anchor of container.querySelectorAll<HTMLAnchorElement>("nav a")) {
    expect(document.getElementById(anchor.hash.slice(1))).not.toBeNull();
  }
});

it("presents each distinct detailed field, its uncertainty and its stored next-call target", async () => {
  const value = parseJobResponse(
    {
      id: "synthetic-run",
      state: "completed",
      message: "Ready",
      report: fixture.report,
    },
    {
      sourceSha256: fixture.transcript.source_sha256,
      durationMs: fixture.transcript.duration_ms,
      transcript: fixture.transcript,
    },
  ).report!;
  await render(value);
  const overview = value.overview!;
  for (const content of [
    overview.diagnosis!.text,
    overview.outcome!.text,
    overview.strength_details[0].why_it_matters,
    overview.improvement_details[0].replacement_behavior,
    overview.golden_moments[0].why_effective,
    overview.missed_details[0].follow_up,
    overview.prospect_interpretations[0].possible_concern,
    overview.conversation_change!.possible_effect,
    overview.ethics_notes[0].text,
    overview.next_call_focus!.target,
    overview.practice!.success_condition,
    overview.final_assessment.assessment,
  ]) {
    expect(container.textContent).toContain(content);
  }
  expect(container.textContent).toContain("Possible concern · inference");
  expect(container.textContent).toContain("Possible effect · inference");
  expect(container.querySelector('[data-review-point="13"]')).toBeNull();
  const clips = container.querySelectorAll<HTMLButtonElement>(
    '[data-review-point="08"] button',
  );
  expect(clips).toHaveLength(2);
  await act(async () => clips[1].click());
  expect(select).toHaveBeenCalledWith(
    overview.rewatch[1].evidence[0],
    overview.rewatch[1].text,
  );
});

it("does not relabel unselected strengths as assessed golden moments", async () => {
  const value = parseJobResponse(
    {
      id: "synthetic-run",
      state: "completed",
      message: "Ready",
      report: fixture.report,
    },
    {
      sourceSha256: fixture.transcript.source_sha256,
      durationMs: fixture.transcript.duration_ms,
      transcript: fixture.transcript,
    },
  ).report!;
  value.overview!.golden_moments = [];
  value.overview!.rewatch = [];
  await render(value);
  expect(
    container.querySelector('[data-review-point="05"] blockquote'),
  ).toBeNull();
  expect(container.querySelector('[data-review-point="08"] button')).toBeNull();
});

it("shows the impact limitations for the third detailed priority too", async () => {
  const source = structuredClone(fixture.report);
  source.improvements = Array.from({ length: 3 }, (_, index) => ({
    ...structuredClone(source.improvements[0]),
    title: `Priority ${index + 1}`,
  }));
  source.overview.improvement_details = Array.from(
    { length: 3 },
    (_, index) => ({
      ...structuredClone(source.overview.improvement_details[0]),
      finding_index: index,
      business_impact: {
        status: "insufficient_data",
        missing_inputs: [`Missing history for priority ${index + 1}`],
      },
    }),
  );
  const value = parseJobResponse(
    {
      id: "synthetic-run",
      state: "completed",
      message: "Ready",
      report: source,
    },
    {
      sourceSha256: fixture.transcript.source_sha256,
      durationMs: fixture.transcript.duration_ms,
      transcript: fixture.transcript,
    },
  ).report!;
  await render(value);
  const third = container.querySelector('[data-review-point="04"]');
  expect(third?.textContent).toContain(
    "Insufficient data for a reliable estimate.",
  );
  expect(third?.textContent).toContain("Missing history for priority 3");
});

it("replays literal mixed-script evidence with its exact source span and no HTML execution", async () => {
  const value = report();
  await render(value);
  const source = value.strengths[0].evidence[0];
  expect(container.querySelector("blockquote span")?.textContent).toBe(
    source.quote,
  );
  expect(container.querySelector("script")).toBeNull();
  const button = container.querySelector<HTMLButtonElement>(
    'button[aria-label^="Play source moment"]',
  )!;
  await act(async () => button.click());
  expect(select).toHaveBeenCalledExactlyOnceWith(
    source,
    value.strengths[0].title,
  );
});

it("curates at most one clip per category without duplicating a source span", async () => {
  const value = report();
  value.missed_opportunities[0].evidence = value.improvements[0].evidence;
  value.missed_opportunities.push(finding("Another missed moment", 7000));
  await render(value);
  const buttons = [
    ...container.querySelectorAll<HTMLButtonElement>(
      '[data-review-point="08"] button',
    ),
  ];
  expect(buttons).toHaveLength(3);
  for (const button of buttons) await act(async () => button.click());
  expect(select.mock.calls.map(([e]) => e.start_ms)).toEqual([
    4000, 7000, 1000,
  ]);
  expect(value.improvements[0].evidence[0].start_ms).toBe(4000);
});

it("does not pad an empty report with template examples or invented improvements", async () => {
  const value = {
    ...report(),
    strengths: [],
    improvements: [],
    missed_opportunities: [],
    dimensions: [],
  };
  await render(value);
  expect(container.querySelector('[data-review-point="02"]')).toBeNull();
  expect(container.querySelector('[data-review-point="08"] button')).toBeNull();
  expect(
    container.querySelector('[data-review-point="11"]')?.textContent,
  ).toContain("has not been identified");
  expect(container.querySelector('[data-review-point="12"] ol')).toBeNull();
  expect(container.textContent).not.toContain("I need to think");
});

it("prints every review point and nested quote then restores both disclosure states", async () => {
  await render();
  const folds = [
    ...container.querySelectorAll<HTMLDetailsElement>("[data-review-fold]"),
  ];
  const evidence = [
    ...container.querySelectorAll<HTMLDetailsElement>(
      ".studio-finding-evidence",
    ),
  ];
  folds[0].open = true;
  evidence[0].open = true;
  await act(async () => window.dispatchEvent(new Event("beforeprint")));
  await act(async () => window.dispatchEvent(new Event("beforeprint")));
  expect([...folds, ...evidence].every((detail) => detail.open)).toBe(true);
  await act(async () => window.dispatchEvent(new Event("afterprint")));
  expect(folds.filter((detail) => detail.open)).toEqual([folds[0]]);
  expect(evidence.filter((detail) => detail.open)).toEqual([evidence[0]]);
});
