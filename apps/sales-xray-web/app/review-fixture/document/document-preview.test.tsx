import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { DOCUMENT_FIXTURE_DATA, DocumentPreview } from "./document-preview";
import Page from "./page";
import { ReportDocument } from "../../report-document";
import { reportDocumentModel } from "../../report-document-model";
import type { ReportEvidence } from "../../report-contract";
import { REPORT_PILLARS } from "../../report-pillars";
import { syntheticEvidence, syntheticReport } from "../report/synthetic-report";
vi.mock("../../report-document", () => ({
  ReportDocument: vi.fn(() => <div data-document-export />),
}));

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not found");
  },
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => vi.unstubAllEnvs());

it("supplies the fictional report and transcript to the file preview", async () => {
  window.history.replaceState(
    null,
    "",
    "/review-fixture/document?call=00000000-0000-4000-8000-000000000002&view=document&print=1",
  );
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<DocumentPreview />));
    expect(
      container.querySelector("[data-report-modes]")?.getAttribute("data-view"),
    ).toBe("document");
    expect(container.querySelectorAll("[data-document-export]")).toHaveLength(
      1,
    );
    const { data } = vi.mocked(ReportDocument).mock.calls.at(-1)![0];
    expect(data?.report).toBe(syntheticReport);
    expect(data?.transcript?.segments.map((s) => s.text)).toContain(
      "I don't want to set another step today. Please don't follow up.",
    );
    expect(container.querySelector("[data-document-page]")).toBeNull();
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

it("its fictional call makes the whole six-part Document (QA's six-section check)", () => {
  // QA saw "This report didn't load" here once on the shared dev server.
  const doc = reportDocumentModel(DOCUMENT_FIXTURE_DATA, {
    roles: { seller: "fictional-seller", prospect: "fictional-buyer" },
    speakerName: (id) => DOCUMENT_FIXTURE_DATA.speakerNames?.[id],
  });
  expect(doc.sections.map((section) => section.id)).toEqual(
    REPORT_PILLARS.map((pillar) => pillar.id),
  );
  for (const section of doc.sections)
    expect(section.parts.length).toBeGreaterThan(0);
  expect(doc.title).toBe("Fictional seller — sample call report");
});

it("keeps every source in this fictional call and its declined next step consistent", () => {
  const sources: ReportEvidence[] = [];
  const collect = (value: unknown) => {
    if (Array.isArray(value)) value.forEach(collect);
    else if (value && typeof value === "object") {
      if ("segment_id" in value) sources.push(value as ReportEvidence);
      else Object.values(value).forEach(collect);
    }
  };
  const doc = reportDocumentModel(DOCUMENT_FIXTURE_DATA);
  collect(DOCUMENT_FIXTURE_DATA.report);
  collect(doc);
  const allowed = new Map(
    Object.values(syntheticEvidence).map((source) => [
      source.segment_id,
      source,
    ]),
  );
  expect(sources.length).toBeGreaterThan(0);
  for (const source of sources)
    expect(source).toEqual(allowed.get(source.segment_id));

  const influence = doc.sections[0].parts.find((part) =>
    part.heading?.startsWith("1.3 "),
  );
  expect(influence?.items[0]).toMatchObject({
    type: "text",
    text: "The buyer declined a next step and asked the seller not to follow up.",
    clip: { source: syntheticEvidence.boundary },
  });
  const action = doc.sections[5].parts.find((part) =>
    part.heading?.startsWith("6.9 "),
  );
  expect(action?.items[0]).toMatchObject({
    type: "text",
    text: "Respect the buyer's request not to follow up.",
  });
  expect(doc.sections[0].parts[0].items[0]).toMatchObject({
    type: "status",
    status: "Outcome not set",
  });
  expect(
    doc.sections[5].parts.find((part) => part.heading?.startsWith("6.8 "))
      ?.items[0],
  ).toMatchObject({
    type: "list",
    items: ["Comparable conversion history", "Lead volume"],
  });
  expect(JSON.stringify(doc)).not.toContain(
    "The closer clarified a follow-up time.",
  );
});

it("assigns the two buyer lines and seller acknowledgement to their stated voices", () => {
  expect(
    DOCUMENT_FIXTURE_DATA.transcript?.segments.map((segment) => [
      segment.id,
      segment.speaker_id,
      segment.text,
    ]),
  ).toEqual([
    [
      syntheticEvidence.concern.segment_id,
      "fictional-buyer",
      syntheticEvidence.concern.quote,
    ],
    [
      syntheticEvidence.boundary.segment_id,
      "fictional-buyer",
      syntheticEvidence.boundary.quote,
    ],
    [
      syntheticEvidence.respect.segment_id,
      "fictional-seller",
      syntheticEvidence.respect.quote,
    ],
  ]);
});

it("does not publish fictional document content in production", () => {
  vi.stubEnv("NODE_ENV", "production");
  expect(() => Page()).toThrow("not found");
  vi.stubEnv("NODE_ENV", "development");
  expect(Page().type).toBe(DocumentPreview);
});
