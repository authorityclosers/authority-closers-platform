import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import Page from "./page";
import { PillarsPreview } from "./pillars-preview";
import { StoryShellPreview } from "../story/preview";
import { contentReport, contentTranscript } from "./content-fixture";
import { ReportDocument } from "../../../report-document";
import { REPORT_PILLARS } from "../../../report-pillars";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("not found");
  },
}));
vi.mock("../story/preview", () => ({
  StoryShellPreview: vi.fn(() => <div data-native-preview />),
}));
vi.mock("../../../report-document", () => ({
  ReportDocument: vi.fn(() => <div data-document-preview />),
}));

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

it("keeps native v8 as the route default and exposes the revised reader, source and Document data", async () => {
  vi.stubEnv("NODE_ENV", "development");
  window.history.replaceState(null, "", "/review-fixture/report/pillars");
  const page = Page();
  expect(page.type).toBe(PillarsPreview);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const click = async (label: string) => {
    const control = [...host.querySelectorAll("button")].find(
      (b) => b.textContent?.trim() === label,
    );
    expect(control, label).toBeDefined();
    await act(async () => control!.click());
  };
  try {
    await act(async () => root.render(page));
    expect(host.querySelector("[data-native-preview]")).not.toBeNull();
    expect(
      vi.mocked(StoryShellPreview).mock.calls.at(-1)![0].fixture,
    ).toMatchObject({ report: { pillars: { version: "report-pillars/1" } } });

    await click("Revised Report");
    expect(host.querySelector("[data-native-preview]")).toBeNull();
    expect(
      [...host.querySelectorAll("[data-report-mode-section]")].map((e) =>
        e.getAttribute("data-report-mode-section"),
      ),
    ).toEqual(REPORT_PILLARS.map((p) => p.id));
    for (const text of ["Meeting Booked", "Friday", "4 PM", "Not Applicable"])
      expect(host.textContent).toContain(text);
    expect(host.textContent).not.toContain(
      "Synthetic call: the buyer declined a sale",
    );
    const source = host.querySelector<HTMLButtonElement>(
      '[data-report-pillar="overview"] button[aria-label="Play 00:04: Strongest part"]',
    );
    expect(source).not.toBeNull();
    await act(async () => source!.click());
    expect(host.querySelector('[role="status"]')?.textContent).toContain(
      contentTranscript.segments[4].text,
    );

    await click("Document · print or Word");
    expect(host.querySelector("[data-document-preview]")).not.toBeNull();
    const data = vi.mocked(ReportDocument).mock.calls.at(-1)![0].data;
    expect(data?.report).toBe(contentReport);
    expect(data?.transcript).toBe(contentTranscript);

    await click("Older report");
    expect(host.querySelector('[role="status"]')?.textContent).not.toContain(
      contentTranscript.segments[4].text,
    );
    expect(host.textContent).toContain(
      "Synthetic call: the buyer declined a sale",
    );
    expect(host.textContent).not.toContain("Meeting Booked");
    await click("Native v8 Report");
    expect(host.querySelector("[data-native-preview]")).not.toBeNull();
    expect(vi.mocked(StoryShellPreview).mock.calls.at(-1)![0].fixture).toEqual(
      page.props.nativeFixture,
    );
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("keeps every fictional candidate out of production", () => {
  vi.stubEnv("NODE_ENV", "production");
  expect(() => Page()).toThrow("not found");
});
