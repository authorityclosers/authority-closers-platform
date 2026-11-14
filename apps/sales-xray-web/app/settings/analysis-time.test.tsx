import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ pays: false as boolean | null }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("../dashboard/dashboard-data", () => ({
  readAllowance: vi.fn(async () => ({
    allowance_seconds: 10_800,
    committed_seconds: 1_140,
    available_seconds: 9_660,
  })),
}));
vi.mock("../workspace-role", () => ({
  useCanHere: () => () => mocks.pays,
}));

import { AnalysisTimeSection, analysisTimeHeadline } from "./analysis-time";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root, host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

// Orchestrator, 13 Nov 2026: what is left and who adds more, for everyone.
it("tells a member what is left and that their owner or admin adds more", async () => {
  mocks.pays = false;
  await act(async () => root.render(<AnalysisTimeSection />));
  expect(host.textContent).toContain("2 h 41 min of analysis left");
  expect(host.textContent).toContain("Your owner or admin can add more.");
  expect(host.textContent).not.toMatch(/₹|Rs|price/);
});

it("sends whoever pays to Plan & usage for more", async () => {
  mocks.pays = true;
  await act(async () => root.render(<AnalysisTimeSection />));
  expect(host.querySelector("a")?.getAttribute("href")).toBe("/settings/plan");
});

it("names the cases with nothing to count", () => {
  expect(
    analysisTimeHeadline({
      allowance_seconds: 0,
      committed_seconds: 0,
      available_seconds: 0,
    }),
  ).toBe("Not on yet");
  expect(
    analysisTimeHeadline({
      allowance_seconds: 600,
      committed_seconds: 600,
      available_seconds: 0,
    }),
  ).toBe("None left");
  expect(
    analysisTimeHeadline({
      allowance_seconds: 0,
      committed_seconds: 0,
      available_seconds: 0,
      unlimited: true,
    }),
  ).toBe("Unlimited");
});
