import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DipakOverview } from "./dipak-overview";
import fixture from "../tests/fixtures/dipak-overview.json";
import { parseJobResponse } from "./report-contract";
import type {
  Finding,
  GuestReportPreview,
  SalesReport,
} from "./report-contract";

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
    "13",
    "14",
  ]);
  expect(
    container.querySelector('[data-summary-card="summary"]')?.textContent,
  ).toContain(value.verdict);
  expect(container.querySelectorAll("[data-chapter]")).toHaveLength(4);
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
  expect(
    container.querySelector('[data-review-point="13"]')?.textContent,
  ).toContain("no trend or improvement claim is inferred");
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
    overview.next_call_focus!.target,
    overview.practice!.success_condition,
    overview.final_assessment.assessment,
  ]) {
    expect(container.textContent).toContain(content);
  }
  expect(container.textContent).toContain(overview.ethics_notes[0].text);
  expect(container.textContent).toContain("Possible concern · inference");
  expect(container.textContent).toContain("Possible effect · inference");
  expect(
    container.querySelector('[data-review-point="10"]')?.textContent,
  ).toContain("No clear skill takeaway");
  expect(
    container.querySelector('[aria-label="Ethics observations"]'),
  ).not.toBeNull();
  expect(container.querySelector('[data-review-point="13"]')).not.toBeNull();
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

it("keeps source context behind an explicit disclosure", async () => {
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
  const details = container.querySelector<HTMLDetailsElement>(
    "[data-source-details]",
  );
  expect(details).not.toBeNull();
  expect(details?.open).toBe(false);
  expect(details?.textContent).toContain(value.overview!.diagnosis!.text);
  expect(details?.textContent).toContain(value.overview!.outcome!.text);
});

it("opens source context for print and restores its closed state", async () => {
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
  const details = container.querySelector<HTMLDetailsElement>(
    "[data-source-details]",
  )!;
  expect(details.open).toBe(false);
  await act(async () => window.dispatchEvent(new Event("beforeprint")));
  expect(details.open).toBe(true);
  await act(async () => window.dispatchEvent(new Event("afterprint")));
  expect(details.open).toBe(false);
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

it("keeps every chapter mounted while the review map opens one section", async () => {
  await render();
  const mapItems = [
    ...container.querySelectorAll<HTMLButtonElement>("[data-insight-number]"),
  ];
  expect(mapItems).toHaveLength(14);
  expect(
    container.querySelector('[data-chapter="start"]')?.hasAttribute("hidden"),
  ).toBe(true);
  expect(
    container.querySelector('[data-chapter="read"]')?.hasAttribute("hidden"),
  ).toBe(true);
  expect(container.querySelector('[data-review-point="09"]')).not.toBeNull();

  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[data-insight-number="05"]')
      ?.click(),
  );
  expect(
    container
      .querySelector<HTMLButtonElement>('[data-insight-number="05"]')
      ?.getAttribute("aria-current"),
  ).toBe("true");
  expect(
    container.querySelector('[data-chapter="start"]')?.hasAttribute("hidden"),
  ).toBe(true);
  expect(
    container.querySelector('[data-chapter="read"]')?.hasAttribute("hidden"),
  ).toBe(false);
  expect(container.querySelector("[data-back-to-overview]")).not.toBeNull();
  expect(container.querySelector('[data-review-point="01"]')).not.toBeNull();
  expect(container.querySelector('[data-review-point="14"]')).not.toBeNull();

  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
  expect(document.activeElement).toBe(
    container.querySelector('[data-review-point="05"]'),
  );

  await act(async () =>
    (
      container.querySelector("[data-back-to-overview]") as HTMLButtonElement
    ).click(),
  );
  expect(
    container.querySelector('[data-chapter="read"]')?.hasAttribute("hidden"),
  ).toBe(true);
  expect(document.activeElement).toBe(
    container.querySelector('[data-insight-number="05"]'),
  );
});

it("opens a bounded review dialog with point navigation and Escape recovery", async () => {
  await render();
  const point = container.querySelector<HTMLButtonElement>(
    '[data-insight-number="05"]',
  )!;
  await act(async () => point.click());
  expect(
    container.querySelector('[role="dialog"][aria-modal="true"]'),
  ).not.toBeNull();
  expect(
    container.querySelector('[aria-label="Close review point"]'),
  ).not.toBeNull();
  expect(container.querySelector('[data-review-point="05"]')).not.toBeNull();
  expect(container.textContent).toContain("Previous point");
  expect(container.textContent).toContain("Next point");
  await act(async () =>
    container.querySelector<HTMLButtonElement>("[data-review-next]")!.click(),
  );
  expect(
    container.querySelector('[aria-current="true"]')?.textContent,
  ).toContain("06");
  await act(async () =>
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })),
  );
  expect(container.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(point);
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
    '[data-review-point="01"] button[aria-label^="Play source moment"]',
  )!;
  await act(async () => button.click());
  expect(select).toHaveBeenCalledExactlyOnceWith(
    source,
    value.strengths[0].title,
  );
});

it("plays the first source moment from the compact overview action", async () => {
  const value = report();
  await render(value);
  const button = container.querySelector<HTMLButtonElement>(
    "[data-source-moment]",
  )!;
  await act(async () => button.click());
  expect(select).toHaveBeenCalledExactlyOnceWith(
    value.improvements[0].evidence[0],
    value.improvements[0].title,
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
  expect(container.querySelector("[data-skill-summary]")).toBeNull();
  expect(container.querySelector('[data-review-point="10"]')).not.toBeNull();
});

it("leads with supported qualitative skills and never renders a score", async () => {
  const value = report();
  value.dimensions = [
    {
      dimension_id: "discovery",
      label: "Discovery",
      status: "observed",
      observation: "You asked a clear question before presenting the offer.",
      citations: [{ doc: "Doc-1", sections: ["Discovery"] }],
    },
    {
      dimension_id: "closing",
      label: "Closing",
      status: "unknown",
      observation: "No supported observation was returned.",
      citations: [{ doc: "Doc-1", sections: ["Closing"] }],
    },
  ];
  await render(value);
  const summary = container.querySelector("[data-skill-summary]");
  expect(summary).not.toBeNull();
  expect(summary?.textContent).toContain("Discovery");
  expect(summary?.textContent).toContain(
    "You asked a clear question before presenting the offer.",
  );
  expect(summary?.textContent).not.toContain("Closing");
  expect(container.textContent).not.toMatch(/\b(?:score|radar|\d+%)\b/i);
  expect(container.querySelector('[data-review-point="10"]')).not.toBeNull();
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

it("shows real remaining counts and opens account access without fabricating blurred content", async () => {
  const value = report();
  value.strengths = value.strengths.slice(0, 1);
  value.improvements = value.improvements.slice(0, 2);
  const zero = { visible_count: 0, total_count: 0, hidden_count: 0 };
  value.preview = {
    version: "guest-findings-v1",
    sections: {
      strengths: { visible_count: 1, total_count: 2, hidden_count: 1 },
      improvements: { visible_count: 2, total_count: 3, hidden_count: 1 },
      missed_opportunities: {
        visible_count: 1,
        total_count: 1,
        hidden_count: 0,
      },
      objection_analysis: zero,
      closing_analysis: zero,
      golden_moments: zero,
      prospect_interpretations: zero,
      rewatch: zero,
      ethics_notes: zero,
    },
  } satisfies GuestReportPreview;
  const unlock = vi.fn();
  await act(async () =>
    root.render(
      <DipakOverview
        report={value}
        onSelectEvidence={select}
        onUnlock={unlock}
      />,
    ),
  );
  const cards = [
    ...container.querySelectorAll<HTMLElement>("[data-preview-section]"),
  ];
  expect(cards.map((card) => card.dataset.previewSection)).toEqual([
    "strengths",
    "improvements",
  ]);
  expect(
    cards.every((card) => card.textContent?.includes("1 more insight")),
  ).toBe(true);
  expect(
    cards.every((card) =>
      card.textContent?.includes(
        "Unlock remaining insights with a free account",
      ),
    ),
  ).toBe(true);
  expect(container.textContent).not.toContain("Keep this");
  expect(container.textContent).not.toContain("Check understanding");
  await act(async () =>
    cards[0].querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(unlock).toHaveBeenCalledOnce();
  expect(select).not.toHaveBeenCalled();
});

it("shows no unlock cards for complete accounts or single/empty guest sections", async () => {
  await render();
  expect(container.querySelector("[data-preview-section]")).toBeNull();
  expect(container.textContent).not.toContain("Unlock remaining insights");
});

it("renders retained objection and closing findings with their actual source controls", async () => {
  const value = report();
  value.objection_analysis = [finding("Clarify the concern", 1000)];
  value.closing_analysis = [finding("Agree a next step", 2000)];
  await render(value);
  const closing = container.querySelector<HTMLElement>(
    '[aria-label="Closing and next steps"]',
  )!;
  expect(closing.textContent).toContain("Agree a next step");
  await act(async () =>
    closing.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(select).toHaveBeenCalledWith(
    value.closing_analysis[0].evidence[0],
    "Agree a next step",
  );
});
