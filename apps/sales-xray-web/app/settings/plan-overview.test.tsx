// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { MePlan } from "../billing/contract";
import { PlanOverview } from "./plan-overview";

vi.mock("./analysis-time", () => ({
  readTeamTime: vi.fn(() => new Promise(() => undefined)),
}));
vi.mock("../organisation/organisation-api", () => ({
  readSeats: vi.fn(() => new Promise(() => undefined)),
}));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-28T06:30:00Z"));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});

// Owner, 22 Nov 2026: "1 month + 3 hours", whichever comes first.
const plan = (trial: MePlan["trial"]): MePlan => ({
  plan: { key: "trial", name: trial?.endsAt ? "1 month free" : "Trial" },
  allowance: {
    allowanceSeconds: 10_800,
    committedSeconds: 3000,
    availableSeconds: 7800,
    unlimited: false,
  },
  longestCallSeconds: 3600,
  trial,
});

async function show(mePlan: MePlan, available = 7800) {
  await act(async () =>
    root.render(
      <PlanOverview
        allowance={{
          state: "ready",
          value: {
            allowance_seconds: available > 0 ? 10_800 : 0,
            committed_seconds: 3000,
            available_seconds: available,
          },
        }}
        mePlan={mePlan}
        subs={{ current: null } as never}
        documents={[]}
        status="ready"
        invoicesStatus="ready"
        busy={false}
        packs={[]}
        purchasesAllowed={false}
        plansOnWeb={null}
        seesSeats={false}
      />,
    ),
  );
  return host.textContent ?? "";
}

it("says the free month, its three hours and the days and time left", async () => {
  const text = await show(
    plan({ seconds: 10_800, endsAt: "2026-12-25T07:00:00Z" }),
  );
  expect(text).toContain("1 month free");
  expect(text).toContain("Free for 1 month · 3 hours of call analysis");
  expect(text).toContain("27 days · 2 h 10 min left");
  expect(text).toContain("Free");
  expect(text).not.toContain("No plan yet");
  expect(text).not.toContain("No subscription yet.");
  expect(text).not.toMatch(/15\s*days?/i);
});

it("says which end of the free month came first", async () => {
  vi.setSystemTime(new Date("2026-12-26T06:30:00Z"));
  expect(
    await show(plan({ seconds: 10_800, endsAt: "2026-12-25T07:00:00Z" }), 0),
  ).toContain("Your free month has ended");
  vi.setSystemTime(new Date("2026-11-28T06:30:00Z"));
  expect(
    await show(plan({ seconds: 10_800, endsAt: "2026-12-25T07:00:00Z" }), 0),
  ).toContain("You've used your 3 free hours");
});

it("promises no month while the trial has no end (trial v1)", async () => {
  const text = await show(plan({ seconds: 10_800, endsAt: null }));
  expect(text).toContain("Free trial · 3 hours of call analysis");
  expect(text).toContain("2 h 10 min left");
  expect(text).not.toContain("1 month");
});
