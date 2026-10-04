import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReportDocument } from "./report-document";
import type { DocumentReportData } from "./report-document-data";

const mocks = vi.hoisted(() => ({ generate: vi.fn(), render: vi.fn() }));
vi.mock("./report-docx", () => ({
  createReportDocx: mocks.generate,
  reportDocxFilename: (title: string) => `${title} – Sales Xray report.docx`,
  DOCUMENT_CHAPTERS: [{ id: "overview", label: "Overview" }],
}));
vi.mock("docx-preview", () => ({ renderAsync: mocks.render }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, container: HTMLDivElement;
const url = vi.fn(),
  revoke = vi.fn();
const blob = new Blob(["one generated file"]);
beforeEach(() => {
  vi.clearAllMocks();
  mocks.generate.mockReset().mockResolvedValue(blob);
  mocks.render
    .mockReset()
    .mockImplementation(async (_blob, body: HTMLElement) => {
      body.innerHTML =
        '<section><p><span id="overview"></span>Overview</p></section>';
    });
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
async function render(
  data: DocumentReportData = { title: "Fictional call" },
  textSize = "100",
) {
  await act(async () =>
    root.render(<ReportDocument data={data} id="report" textSize={textSize} />),
  );
  await act(async () => {
    await vi.waitFor(() =>
      expect(container.querySelector("a[download]")).not.toBeNull(),
    );
  });
}

it("previews and downloads the same Blob, and zoom does not regenerate it", async () => {
  await render();
  expect(mocks.render.mock.calls[0][0]).toBe(blob);
  expect(url.mock.calls[0][0]).toBe(blob);
  expect(container.querySelector("a[download]")?.getAttribute("href")).toBe(
    "blob:generated-report",
  );
  expect(container.querySelector("a[download]")?.getAttribute("download")).toBe(
    "Fictional call – Sales Xray report.docx",
  );
  expect(
    container.querySelector('[data-report-mode-section="overview"]')?.id,
  ).toBe("report-heading-overview");
  await render({ title: "Fictional call" }, "125");
  expect(mocks.generate).toHaveBeenCalledOnce();
  expect(mocks.render).toHaveBeenCalledOnce();
  expect(
    container
      .querySelector('[style*="--document-zoom"]')
      ?.getAttribute("style"),
  ).toContain("1.25");
  await act(async () => root.unmount());
  expect(revoke).toHaveBeenCalledWith("blob:generated-report");
});

it("disables a stale download and ignores a previous report that finishes late", async () => {
  let finish!: (blob: Blob) => void;
  mocks.generate.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await act(async () =>
    root.render(
      <ReportDocument
        data={{ title: "Old call" }}
        id="report"
        textSize="100"
      />,
    ),
  );
  await act(async () => {
    await vi.waitFor(() => expect(mocks.generate).toHaveBeenCalledOnce());
  });
  expect(container.querySelector("button")?.disabled).toBe(true);
  await render({ title: "New call" });
  await act(async () => finish(new Blob(["stale file"])));
  expect(mocks.render).toHaveBeenCalledOnce();
  expect(url).toHaveBeenCalledOnce();
  expect(
    container.querySelector("a[download]")?.getAttribute("download"),
  ).toContain("New call");
});

it("shows a recoverable failure without offering another file", async () => {
  mocks.render.mockRejectedValueOnce(new Error("preview failed"));
  await act(async () =>
    root.render(
      <ReportDocument data={{ title: "Call" }} id="report" textSize="100" />,
    ),
  );
  await act(async () => {
    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')).not.toBeNull(),
    );
  });
  expect(container.querySelector("a[download]")).toBeNull();
  expect(url).not.toHaveBeenCalled();
  await act(async () =>
    container
      .querySelector<HTMLButtonElement>('[role="alert"] button')!
      .click(),
  );
  await act(async () => {
    await vi.waitFor(() =>
      expect(container.querySelector("a[download]")).not.toBeNull(),
    );
  });
  expect(mocks.generate).toHaveBeenCalledTimes(2);
});
