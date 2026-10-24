// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("../../notice-center", () => ({ notify: () => undefined }));
vi.mock("../../telemetry", () => ({
  track: () => undefined,
  waitBand: () => "unknown",
}));

import { fixtureReport } from "../../review-fixture/lead-pipeline/lead-pipeline-data";
import { PipelineDashboard, nowTitle, percent } from "./dashboard";
import type { PipelineReport } from "./pipeline-client";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const serve = (report: PipelineReport) =>
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(report), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    ),
  );

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("shows where leads are, what converts and why they were lost", async () => {
  serve(fixtureReport());
  await act(async () => {
    root.render(<PipelineDashboard pipeline="main" />);
  });
  const text = container.textContent ?? "";
  expect(text).toContain("Late follow-ups");
  expect(text).toContain("72%");
  expect(text).toContain("13 of 18 leads");
  expect(text).toContain("Lost most often: price or budget");
  expect(text).toContain("Junk leads are left out of these.");
  expect(text).toContain("Kavya Fictional");
  // Counts only: never money.
  expect(text).not.toMatch(/₹|\$|rupee/i);
});

it("says the numbers will come when there are few leads", async () => {
  serve({ ...fixtureReport(), enough: false, total: 4 });
  await act(async () => {
    root.render(<PipelineDashboard pipeline="main" />);
  });
  expect(container.textContent).toContain("Not enough leads yet: 4");
});

it("a seller sees their own numbers, without the team's rows", async () => {
  serve({ ...fixtureReport(), mine: true });
  await act(async () => {
    root.render(<PipelineDashboard pipeline="main" />);
  });
  expect(container.textContent).toContain("Your own leads.");
  expect(container.textContent).not.toContain("Sellers, by leads won");
});

it("words its numbers", () => {
  expect(percent(0.556)).toBe("56%");
  expect(percent(null)).toBe("–");
  expect(nowTitle({ total: 12, groups: { active: 7 } })).toBe(
    "12 leads, 7 still being worked",
  );
});
