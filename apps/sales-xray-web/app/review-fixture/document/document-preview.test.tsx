import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { DocumentPreview } from "./document-preview";
import Page from "./page";
import { ReportDocument } from "../../report-document";
import { syntheticReport } from "../report/synthetic-report";
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

it("does not publish fictional document content in production", () => {
  vi.stubEnv("NODE_ENV", "production");
  expect(() => Page()).toThrow("not found");
  vi.stubEnv("NODE_ENV", "development");
  expect(Page().type).toBe(DocumentPreview);
});
