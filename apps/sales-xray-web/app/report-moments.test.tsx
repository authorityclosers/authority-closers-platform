import { act, type ReactNode } from "react";
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
import { countReportMoments, ReportMoments } from "./report-moments";
import { ReportTranscript } from "./report-transcript";

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
function historicalReport(): SalesReport {
  const report = suppliedReport();
  delete report.overview;
  return report;
}
function emptyReport(): SalesReport {
  return {
    ...historicalReport(),
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
function manyMoments(): SalesReport {
  return {
    ...emptyReport(),
    strengths: [
      {
        title: "First supplied finding",
        explanation: "First supplied explanation",
        evidence: [8, 3, 7, 1, 6].map(excerpt),
      },
      {
        title: "Second supplied finding",
        explanation: "Second supplied explanation",
        evidence: [4, 2, 5, 0].map(excerpt),
      },
    ],
  };
}
async function render(
  report: SalesReport,
  onSelectEvidence = vi.fn<(evidence: ReportEvidence, title: string) => void>(),
  transcriptSlot?: ReactNode,
) {
  await act(async () =>
    root.render(
      <ReportMoments
        report={report}
        onSelectEvidence={onSelectEvidence}
        transcriptSlot={transcriptSlot}
      />,
    ),
  );
  return onSelectEvidence;
}
function screen() {
  return container.querySelector("[data-report-moments] > div")!;
}
function focused() {
  return screen().querySelector<HTMLElement>("[data-focused-moment]")!;
}
function button(label: string, scope: ParentNode = screen()) {
  const found = [...scope.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) =>
      (node.getAttribute("aria-label") ?? node.textContent?.trim()) === label,
  );
  expect(found, label).toBeDefined();
  return found!;
}
async function click(label: string, scope: ParentNode = screen()) {
  await act(async () => button(label, scope).click());
}
function dialog() {
  return container.querySelector<HTMLDialogElement>("dialog[open]")!;
}
async function filter(kind: string) {
  await act(async () => {
    const select = screen().querySelector<HTMLSelectElement>(
      'select[aria-label="Moment source"]',
    )!;
    select.value = kind;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

it("uses validated rewatch notes in report order with the exact quote, purpose and callback", async () => {
  const report = suppliedReport();
  const first = report.overview!.rewatch[0];
  const second = report.overview!.rewatch[1];
  const onSelect = await render(report);
  expect(screen().querySelectorAll("[data-moment-id]")).toHaveLength(
    report.overview!.rewatch.length,
  );
  expect(focused().querySelector("h3")?.textContent).toBe(first.text);
  expect(focused().querySelector("blockquote p")?.textContent).toBe(
    first.evidence[0].quote,
  );
  expect(focused().textContent).toContain("Rewatch · Must watch");
  expect(focused().textContent).toContain("00:01.000 – 00:02.200");
  expect(screen().textContent).not.toMatch(
    /Discovery|What happened|Why it matters/,
  );
  await click("Listen");
  expect(onSelect).toHaveBeenLastCalledWith(first.evidence[0], first.text);
  expect(onSelect.mock.calls[0][0]).toBe(first.evidence[0]);
  await click("Next moment");
  expect(focused().querySelector("h3")?.textContent).toBe(second.text);
  await click("Listen");
  expect(onSelect).toHaveBeenLastCalledWith(second.evidence[0], second.text);
});

it("falls back to historical findings without sorting, merging or inventing topic assessments", async () => {
  const report = {
    ...emptyReport(),
    strengths: [
      {
        title: "Supplied strength",
        explanation: "Strength explanation",
        evidence: [excerpt(9), excerpt(1)],
      },
    ],
    improvements: [
      {
        title: "Supplied improvement",
        explanation: "Improvement explanation",
        evidence: [excerpt(7)],
      },
    ],
    missed_opportunities: [
      {
        title: "Supplied missed opportunity",
        explanation: "Missed explanation",
        evidence: [excerpt(2)],
      },
    ],
    objection_analysis: [
      {
        title: "Supplied objection analysis",
        explanation: "Objection explanation",
        evidence: [excerpt(6)],
      },
    ],
    closing_analysis: [
      {
        title: "Supplied closing analysis",
        explanation: "Closing explanation",
        evidence: [excerpt(3)],
      },
    ],
  };
  const onSelect = await render(report);
  const expected = [
    ...report.strengths,
    ...report.improvements,
    ...report.missed_opportunities,
    ...report.objection_analysis,
    ...report.closing_analysis,
  ].flatMap((finding) =>
    finding.evidence.map((evidence) => ({ finding, evidence })),
  );
  for (const [index, { finding, evidence }] of expected.entries()) {
    expect(focused().querySelector("h3")?.textContent).toBe(finding.title);
    expect(focused().textContent).toContain(finding.explanation);
    expect(focused().querySelector("blockquote p")?.textContent).toBe(
      evidence.quote,
    );
    await click("Listen");
    expect(onSelect.mock.calls[index]).toEqual([evidence, finding.title]);
    expect(onSelect.mock.calls[index][0]).toBe(evidence);
    if (index < expected.length - 1) await click("Next moment");
  }
  expect(button("Next moment").disabled).toBe(true);
  expect(screen().textContent).toContain("Moment 6 of 6");
  expect(
    [...screen().querySelectorAll("option")].map(
      (option) => option.textContent,
    ),
  ).toEqual([
    "All sources",
    "Strength",
    "Improvement",
    "Missed opportunity",
    "Objection analysis",
    "Closing analysis",
  ]);
});

it("preserves an intentional empty rewatch selection even when detailed findings have evidence", async () => {
  const report = suppliedReport();
  report.overview!.rewatch = [];
  await render(report);
  expect(screen().textContent).toContain(
    "No rewatch moments were selected for this report",
  );
  expect(screen().querySelector("[data-focused-moment]")).toBeNull();
  expect(countReportMoments(report)).toBe(0);
});

it("exports a pure count of the same supplied evidence dataset, excluding missing excerpts", () => {
  const detailed = suppliedReport();
  expect(countReportMoments(detailed)).toBe(detailed.overview!.rewatch.length);
  const report = {
    ...manyMoments(),
    improvements: [
      {
        title: "Unlinked finding",
        explanation: "No excerpt attached",
        evidence: [],
      },
    ],
  };
  const before = JSON.stringify(report);
  expect(countReportMoments(report)).toBe(9);
  expect(JSON.stringify(report)).toBe(before);
  expect(countReportMoments(emptyReport())).toBe(0);
});

it("keeps duplicate source ranges attached to each original finding and quote", async () => {
  const shared = excerpt(1);
  const otherQuote = {
    ...shared,
    quote: "Another exact supplied quote in the same range",
  };
  const report = {
    ...emptyReport(),
    strengths: [
      {
        title: "Strength context",
        explanation: "First context",
        evidence: [shared],
      },
    ],
    improvements: [
      {
        title: "Improvement context",
        explanation: "Second context",
        evidence: [otherQuote, shared],
      },
    ],
  };
  const onSelect = await render(report);
  expect(countReportMoments(report)).toBe(3);
  expect(screen().querySelectorAll("[data-moment-id]")).toHaveLength(3);
  await click("Listen");
  await click("Next moment");
  await click("Listen");
  await click("Next moment");
  await click("Listen");
  expect(onSelect.mock.calls).toEqual([
    [shared, "Strength context"],
    [otherQuote, "Improvement context"],
    [shared, "Improvement context"],
  ]);
});

it("explains empty and missing-evidence states without counting phantom moments or offering playback", async () => {
  const onSelect = await render(emptyReport());
  expect(screen().textContent).toContain("No source moments supplied");
  expect(screen().textContent).toContain(
    "A transcript has not been provided in this view",
  );
  expect(screen().querySelectorAll("button")).toHaveLength(0);
  await render(
    {
      ...emptyReport(),
      strengths: [
        {
          title: "Supplied item without excerpt",
          explanation: "Available note only",
          evidence: [],
        },
      ],
    },
    onSelect,
  );
  expect(screen().textContent).toContain(
    "No linked source excerpts were supplied",
  );
  expect(screen().textContent).toContain("Key moments (0)");
  expect(screen().textContent).not.toMatch(/\d\d:\d\d/);
  expect(screen().querySelector("[data-focused-moment]")).toBeNull();
  expect(screen().querySelectorAll("button")).toHaveLength(0);
  expect(onSelect).not.toHaveBeenCalled();
});

it("bounds the desktop list to four rows while previous/next traverses every supplied excerpt", async () => {
  const report = manyMoments();
  await render(report);
  expect(screen().querySelectorAll("[data-moment-id]")).toHaveLength(4);
  expect(button("Previous moment").disabled).toBe(true);
  expect(button("Previous moment page").disabled).toBe(true);
  await click("Next moment page");
  expect(focused().dataset.focusedMoment).toBe("strengths:0:4");
  expect(screen().textContent).toContain("Page 2 of 3");
  await click("Next moment page");
  expect(screen().querySelectorAll("[data-moment-id]")).toHaveLength(1);
  expect(focused().dataset.focusedMoment).toBe("strengths:1:3");
  expect(button("Next moment page").disabled).toBe(true);
  expect(button("Next moment").disabled).toBe(true);
  await click("Previous moment");
  expect(screen().textContent).toContain("Page 2 of 3");
  await click("Previous moment page");
  expect(focused().dataset.focusedMoment).toBe("strengths:0:0");
  await act(async () =>
    screen()
      .querySelector<HTMLButtonElement>('[data-moment-id="strengths:0:2"]')!
      .click(),
  );
  expect(focused().dataset.focusedMoment).toBe("strengths:0:2");
});

it("filters by supplied source kind and keeps the full print collection independent of pages and filters", async () => {
  const report = {
    ...manyMoments(),
    improvements: [
      {
        title: "Supplied improvement",
        explanation: "Complete note",
        evidence: [excerpt(12)],
      },
    ],
  };
  await render(report);
  await click("Next moment page");
  await filter("improvements");
  expect(screen().querySelectorAll("[data-moment-id]")).toHaveLength(1);
  expect(focused().textContent).toContain("Supplied improvement");
  expect(button("Previous moment").disabled).toBe(true);
  const printed = container.querySelector("[data-moments-print]")!;
  expect(printed.querySelectorAll("article")).toHaveLength(10);
  expect(printed.querySelectorAll("blockquote")[8].textContent).toBe(
    report.strengths[1].evidence[3].quote,
  );
  expect(printed.textContent).toContain(report.source_sha256);
  await filter("all");
  expect(focused().dataset.focusedMoment).toBe("strengths:0:0");
});

it("opens complete long text and provenance in a focused review, then restores the invoking control", async () => {
  const evidence = {
    ...excerpt(61),
    quote: "Exact multilingual source शब्द ".repeat(60),
  };
  const title = "Long supplied title ".repeat(12);
  const explanation = "Entire supplied observation. ".repeat(130);
  const report = {
    ...emptyReport(),
    strengths: [{ title, explanation, evidence: [evidence] }],
  };
  const onSelect = await render(report);
  const opener = button("Open review");
  opener.focus();
  await click("Open review");
  expect(onSelect).not.toHaveBeenCalled();
  expect(dialog()).not.toBeNull();
  expect(document.activeElement).toBe(button("Close review moment", dialog()));
  expect(dialog().querySelector("h3")?.textContent).toBe(title);
  expect(dialog().querySelector("blockquote")?.textContent).toBe(
    evidence.quote,
  );
  expect(dialog().textContent).toContain(explanation);
  expect(dialog().textContent).toContain("01:01.123 – 01:01.987");
  for (const value of [
    report.source_label,
    report.source_sha256,
    report.transcript_revision,
    evidence.segment_id,
  ])
    expect(dialog().textContent).toContain(value);
  await act(async () =>
    dialog().dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  expect(dialog()).toBeNull();
  expect(document.activeElement).toBe(opener);
  await click("Open review");
  await click("Listen to this excerpt", dialog());
  expect(onSelect).toHaveBeenCalledExactlyOnceWith(evidence, title);
  expect(onSelect.mock.calls[0][0]).toBe(evidence);
  expect(dialog()).toBeNull();
  expect(
    container.querySelector("[data-moments-print]")?.textContent,
  ).toContain(explanation);
});

it("navigates full reviews in place and returns to the start of the next moment's text", async () => {
  await render(manyMoments());
  await click("Open review");
  const sheet = dialog();
  const scrollBody = sheet.querySelector("[data-full-moment]")!.parentElement!;
  scrollBody.scrollTop = 300;
  await click("Next moment", sheet);
  expect(dialog()).toBe(sheet);
  expect(focused().dataset.focusedMoment).toBe("strengths:0:1");
  expect(scrollBody.scrollTop).toBe(0);
  expect(document.activeElement).toBe(sheet.querySelector("h3"));
  expect(sheet.textContent).toContain("Exact supplied phrase 3");
});

it.each(["source", "revision"])(
  "resets selection, filters and open review when the %s changes",
  async (change) => {
    const report = {
      ...manyMoments(),
      improvements: [
        {
          title: "Another finding",
          explanation: "A note",
          evidence: [excerpt(12)],
        },
      ],
    };
    const onSelect = await render(report);
    await filter("improvements");
    await click("Open review");
    const changed = {
      ...report,
      source_sha256:
        change === "source" ? "c".repeat(64) : report.source_sha256,
      transcript_revision:
        change === "revision" ? "new-revision" : report.transcript_revision,
      strengths: [
        {
          title: "New report first moment",
          explanation: "New report observation",
          evidence: [excerpt(24)],
        },
      ],
    };
    await render(changed, onSelect);
    expect(dialog()).toBeNull();
    expect(screen().querySelector<HTMLSelectElement>("select")?.value).toBe(
      "all",
    );
    expect(focused().querySelector("h3")?.textContent).toBe(
      "New report first moment",
    );
    await click("Listen");
    expect(onSelect).toHaveBeenLastCalledWith(
      changed.strengths[0].evidence[0],
      changed.strengths[0].title,
    );
  },
);

it("retains existing transcript phrase search and exact-source selection in an independently scrollable sheet", async () => {
  const onTranscriptSelect = vi.fn();
  await render(
    emptyReport(),
    vi.fn(),
    <ReportTranscript transcript={transcript} onSelect={onTranscriptSelect} />,
  );
  expect(screen().textContent).toContain(
    "You can still search the full transcript",
  );
  await click("Search full transcript");
  const sheet = dialog();
  await act(async () => sheet.querySelector("summary")!.click());
  const search = sheet.querySelector<HTMLInputElement>('input[type="search"]')!;
  const target = transcript.segments[1];
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(search, target.text);
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(sheet.querySelectorAll("[data-segment-id]")).toHaveLength(1);
  await act(async () =>
    sheet.querySelector<HTMLButtonElement>("[data-segment-id]")!.click(),
  );
  expect(onTranscriptSelect).toHaveBeenCalledExactlyOnceWith(target);
  await click("Close full transcript", sheet);
  await click("Search full transcript");
  expect(
    dialog().querySelector<HTMLInputElement>('input[type="search"]')!.value,
  ).toBe(target.text);
  expect(dialog().querySelector("details")!.open).toBe(true);
});
