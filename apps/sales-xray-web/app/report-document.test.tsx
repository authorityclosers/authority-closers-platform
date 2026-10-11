import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { SalesReport, Transcript } from "./report-contract";
import { ReportDocument } from "./report-document";
import type { DocumentReportData } from "./report-document-data";
import {
  amitReport,
  amitTranscript,
} from "./review-fixture/report/story/amit-call";

const mocks = vi.hoisted(() => ({ generate: vi.fn() }));
vi.mock("./report-docx", () => ({
  createReportDocx: mocks.generate,
  reportDocxFilename: (title: string) => `${title} – Sales Xray report.docx`,
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root, container: HTMLDivElement;
const url = vi.fn(),
  revoke = vi.fn();
const blob = new Blob(["one generated file"]);
const DATA: DocumentReportData = {
  title: "Amit Sharma · discovery call",
  report: amitReport as SalesReport,
  transcript: amitTranscript as Transcript,
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.generate.mockReset().mockResolvedValue(blob);
  url.mockReturnValue("blob:generated-report");
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = url;
      static revokeObjectURL = revoke;
    },
  );
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function render(data: DocumentReportData = DATA, textSize = "100") {
  await act(async () =>
    root.render(<ReportDocument data={data} id="report" textSize={textSize} />),
  );
}
const button = (name: string) =>
  [...container.querySelectorAll("button")].find((b) =>
    b.textContent?.includes(name),
  )!;

it("renders the report as one page with Dipak's headings and section anchors", async () => {
  await render();
  const pillars = [...container.querySelectorAll("h3")].map(
    (h) => h.textContent,
  );
  expect(pillars).toEqual([
    "1. The Big Picture",
    "2. How the Call Played Out",
    "3. What Worked — & What Didn't",
    "4. Moments That Mattered",
    "5. Your Skills on This Call",
    "6. Where the Deal Stands",
  ]);
  expect(
    container.querySelector(`[data-report-mode-section="overview"]`)?.id,
  ).toBe("report-heading-overview");
  expect(
    container.querySelector('[data-report-mode-section="facts"]')?.id,
  ).toBe("report-heading-facts");
  const parts = [...container.querySelectorAll("h4")].map((h) => h.textContent);
  expect(parts.slice(0, 2)).toEqual([
    "1.1 Call Outcome",
    "1.2 Executive Summary",
  ]);
  expect(container.querySelector("h2")?.textContent).toBe(
    "Amit Sharma · discovery call",
  );
  // Without a player the times read like the document: "18:42 · Play".
  expect(container.textContent).toMatch(/\d\d:\d\d · Play/);
  expect(
    container.querySelector('[style*="--doc-scale"]')?.getAttribute("style"),
  ).toContain("1");
});

it("plays a moment through the report's player when one is given", async () => {
  const onSelect = vi.fn();
  await act(async () =>
    root.render(
      <ReportDocument
        data={DATA}
        id="report"
        textSize="100"
        onSelect={onSelect}
      />,
    ),
  );
  const play = container.querySelector<HTMLButtonElement>(
    'button[aria-label^="Play "]',
  )!;
  expect(play).not.toBeNull();
  // Every chip reads time first, a moment's stretch too: "06:35–06:58 · Play".
  const chips = [...container.querySelectorAll("button[aria-pressed]")].map(
    (b) => b.textContent,
  );
  expect(chips.some((t) => /^\d\d:\d\d–\d\d:\d\d · Play$/.test(t ?? ""))).toBe(
    true,
  );
  expect(chips.every((t) => /· Play$/.test(t ?? ""))).toBe(true);
  await act(async () => play.click());
  expect(onSelect).toHaveBeenCalledOnce();
  expect(onSelect.mock.calls[0][0]).toHaveProperty("start_ms");
});

it("builds the Word file only when asked, from the same report", async () => {
  await render();
  expect(mocks.generate).not.toHaveBeenCalled();
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  await act(async () => button("Download Word file").click());
  await act(async () => {
    await vi.waitFor(() => expect(click).toHaveBeenCalledOnce());
  });
  expect(mocks.generate.mock.calls[0][0]).toBe(DATA);
  expect(url).toHaveBeenCalledWith(blob);
  const link = click.mock.instances[0] as unknown as HTMLAnchorElement;
  expect(link.download).toBe(
    "Amit Sharma · discovery call – Sales Xray report.docx",
  );
  click.mockRestore();
});

it("a failed Word file says so and can be tried again", async () => {
  mocks.generate.mockRejectedValueOnce(new Error("build failed"));
  await render();
  await act(async () => button("Download Word file").click());
  await act(async () => {
    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')).not.toBeNull(),
    );
  });
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    "didn't build",
  );
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  await act(async () => button("Try again").click());
  await act(async () => {
    await vi.waitFor(() => expect(click).toHaveBeenCalledOnce());
  });
  expect(container.querySelector('[role="alert"]')).toBeNull();
  click.mockRestore();
});

it("prints the page", async () => {
  const print = vi.fn();
  vi.stubGlobal("print", print);
  await render();
  await act(async () => button("Print or save as PDF").click());
  expect(print).toHaveBeenCalledOnce();
});

it("a report it can't read shows a quiet note, not a broken page", async () => {
  const unreadable = new Proxy(
    {},
    {
      get() {
        throw new Error("unreadable report");
      },
    },
  );
  await render({ report: unreadable as SalesReport });
  expect(container.querySelector("article")).toBeNull();
  expect(container.querySelector('[role="status"]')?.textContent).toContain(
    "didn't load",
  );
  expect(button("Download Word file").disabled).toBe(true);
});
