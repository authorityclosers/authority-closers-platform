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
const team = vi.fn();
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  team.mockReset().mockResolvedValue(new Response("{}", { status: 403 }));
  vi.stubGlobal("fetch", team);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

// Orchestrator, 13 Nov 2026: what is left and who adds more, for everyone.
it("tells a member what is left and that their owner or admin adds more", async () => {
  mocks.pays = false;
  await act(async () => root.render(<AnalysisTimeSection />));
  expect(host.textContent).toContain("2 h 41 min of analysis left");
  expect(host.textContent).toContain("Your owner or admin can add more.");
  expect(host.textContent).not.toMatch(/₹|\bRs\b|price/);
  // A member never asks for the team's numbers.
  expect(team).not.toHaveBeenCalled();
});

it("sends whoever pays to Plan & usage for more", async () => {
  mocks.pays = true;
  await act(async () => root.render(<AnalysisTimeSection />));
  expect(host.querySelector("a")?.getAttribute("href")).toBe("/settings/plan");
  // A personal workspace has no team: nothing more shows.
  expect(host.textContent).not.toContain("Each seller");
});

it("shows an owner the workspace's time and what each seller used", async () => {
  mocks.pays = true;
  team.mockResolvedValue(
    new Response(
      JSON.stringify({
        allowance: {},
        people: [
          { person_id: "p1", name: "fictional asha", used_seconds: 4_320 },
          { person_id: "p2", name: "Fictional Rohan", used_seconds: 0 },
        ],
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    ),
  );
  await act(async () => root.render(<AnalysisTimeSection />));
  expect(team).toHaveBeenCalledWith(
    "/v1/me/analysis-time/team",
    expect.objectContaining({ credentials: "same-origin" }),
  );
  expect(host.textContent).toContain("Your workspace");
  const rows = [
    ...host.querySelectorAll('[aria-label="Each seller\'s analysis time"] li'),
  ].map((row) => row.textContent);
  expect(rows).toEqual([
    "Fictional Asha1 h 12 min used",
    "Fictional RohanNone used",
  ]);
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
