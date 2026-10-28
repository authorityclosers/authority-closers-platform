// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/analysis/sample",
}));

import { SAMPLE_REPORT_HREF } from "../../dashboard/home-v2";
import { SAMPLE_AUDIO_SRC, sampleCall } from "./sample-call";
import { SamplePage } from "./sample-page";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let container: HTMLDivElement;
beforeEach(() => {
  window.history.replaceState(null, "", SAMPLE_REPORT_HREF);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  // The page reads nothing; the shell's profile menu may try and must cope.
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.reject(new Error("no server"))),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("reads the frozen sample call through the real report codec", () => {
  const data = sampleCall();
  expect(data.transcript.segments).toHaveLength(24);
  expect(data.durationMs).toBe(data.transcript.duration_ms);
  expect(data.report.summary).toContain("Meera");
  expect(data.report.dimensions.length).toBeGreaterThan(0);
  expect(data.audioSrc).toBe(SAMPLE_AUDIO_SRC);
});

it("shows the real report of a fictional call, with its recording", async () => {
  await act(async () => root.render(<SamplePage />));
  await act(async () => Promise.resolve());
  const page = container.querySelector('[data-sample-report="true"]');
  expect(page).not.toBeNull();
  expect(container.textContent).toContain("Sample report.");
  expect(
    container.querySelector('a[href="/leads#add=lead"]')?.textContent,
  ).toBe("Add your first lead");
  expect(
    container.querySelector('[aria-label="Sales call report"]'),
  ).not.toBeNull();
  expect(container.querySelector("audio")?.getAttribute("src")).toBe(
    SAMPLE_AUDIO_SRC,
  );
});
