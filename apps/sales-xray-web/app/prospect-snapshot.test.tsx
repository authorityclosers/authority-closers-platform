import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import fixture from "../tests/fixtures/dipak-overview.json";
import {
  parseJobResponse,
  type GuestReportPreview,
  type ReportEvidence,
  type SalesReport,
} from "./report-contract";
import { ProspectSnapshot } from "./prospect-snapshot";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
const selected = vi.fn<(evidence: ReportEvidence, title: string) => void>();
const binding = {
  sourceSha256: fixture.transcript.source_sha256,
  durationMs: fixture.transcript.duration_ms,
  transcript: fixture.transcript,
};

function parsedReport(
  source: unknown = structuredClone(fixture.report),
): SalesReport {
  return parseJobResponse(
    {
      id: "prospect-snapshot-test",
      state: "completed",
      message: "Ready",
      report: source,
    },
    binding,
  ).report!;
}

function previewWithProspectCounts(
  visibleCount: number,
  totalCount: number,
): GuestReportPreview {
  const none = { visible_count: 0, total_count: 0, hidden_count: 0 };
  return {
    version: "guest-findings-v1",
    sections: {
      strengths: none,
      improvements: none,
      missed_opportunities: none,
      objection_analysis: none,
      closing_analysis: none,
      golden_moments: none,
      prospect_interpretations: {
        visible_count: visibleCount,
        total_count: totalCount,
        hidden_count: totalCount - visibleCount,
      },
      rewatch: none,
      ethics_notes: none,
    },
  };
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  selected.mockClear();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(report: SalesReport, onUnlock?: () => void) {
  await act(async () =>
    root.render(
      <ProspectSnapshot
        report={report}
        onSelectEvidence={selected}
        onUnlock={onUnlock}
      />,
    ),
  );
}

it("separates the report observation, exact source words, and hypothesis", async () => {
  const report = parsedReport();
  const interpretation = report.overview!.prospect_interpretations[0];
  await render(report);

  const card = container.querySelector<HTMLElement>(
    "[data-prospect-index='0']",
  )!;
  expect(
    card.querySelector('[data-prospect-part="source"]')?.textContent,
  ).toContain(interpretation.source.text);
  expect(
    card.querySelector('[data-prospect-part="verbatim"]')?.textContent,
  ).toContain(interpretation.source.evidence[0].quote);
  const hypothesis = card.querySelector('[data-prospect-part="hypothesis"]')!;
  expect(hypothesis.textContent).toContain("Hypothesis · not a fact");
  expect(hypothesis.textContent).toContain(interpretation.possible_concern);
  expect(hypothesis.textContent).not.toContain(
    interpretation.source.evidence[0].quote,
  );

  const evidence = interpretation.source.evidence[0];
  const play = card.querySelector<HTMLButtonElement>(
    '[aria-label="Play source moment, 00:01.000 to 00:02.200"]',
  )!;
  await act(async () => play.click());
  expect(selected).toHaveBeenCalledWith(evidence, "Prospect signal 1");
});

it("keeps guest preview counts and never renders withheld interpretations", async () => {
  const report = parsedReport();
  report.preview = previewWithProspectCounts(
    report.overview!.prospect_interpretations.length,
    report.overview!.prospect_interpretations.length + 2,
  );
  const unlock = vi.fn();
  await render(report, unlock);

  const lock = container.querySelector<HTMLElement>(
    '[data-preview-section="prospect_interpretations"]',
  )!;
  expect(lock.dataset.visibleCount).toBe("1");
  expect(lock.dataset.totalCount).toBe("3");
  expect(lock.textContent).toContain("2 more prospect interpretations");
  expect(lock.textContent).toContain(
    "Unlock remaining interpretations with a free account",
  );
  expect(container.textContent).not.toContain("Hidden interpretation content");

  const continueFree = [...container.querySelectorAll("button")].find(
    (button) => button.textContent?.includes("Continue free"),
  )!;
  await act(async () => continueFree.click());
  expect(unlock).toHaveBeenCalledOnce();
  expect(selected).not.toHaveBeenCalled();
});

it.each(["legacy report without overview", "overview with no interpretations"])(
  "shows honest missing-data copy for %s",
  async (kind) => {
    const source = structuredClone(fixture.report) as Record<string, unknown>;
    if (kind === "legacy report without overview") delete source.overview;
    else {
      const overview = source.overview as Record<string, unknown>;
      overview.prospect_interpretations = [];
    }
    await render(parsedReport(source));

    expect(container.querySelector("[data-prospect-empty]")).not.toBeNull();
    expect(container.textContent).toContain(
      "No separate prospect interpretation",
    );
    expect(container.textContent).toContain(
      "Missing information does not establish",
    );
    expect(container.querySelector("[data-preview-section]")).toBeNull();
    expect(selected).not.toHaveBeenCalled();
  },
);

it("keeps complete account reports free of guest locks", async () => {
  await render(parsedReport());
  expect(container.querySelector("[data-preview-section]")).toBeNull();
  expect(container.textContent).not.toContain(
    "Unlock remaining interpretations",
  );
});
