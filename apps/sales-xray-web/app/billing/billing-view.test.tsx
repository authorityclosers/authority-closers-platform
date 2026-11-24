// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { notify } from "../notice-center";
import { BillingView } from "./billing-view";

vi.mock("../notice-center", () => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
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
  vi.clearAllMocks();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows the cards' outline while billing loads, not a line of text", async () => {
  await act(async () => root.render(<BillingView status="loading" />));
  expect(
    host.querySelector('[aria-label="Loading billing details"]'),
  ).not.toBeNull();
  expect(host.textContent).not.toContain("Loading billing details");
  expect(host.textContent).not.toContain("couldn't load");
});

it("raises one corner card when billing can't be read, with quiet placeholders", async () => {
  const onRefresh = vi.fn();
  await act(async () =>
    root.render(<BillingView status="error" onRefresh={onRefresh} />),
  );
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.textContent).toContain("We couldn't load your plan right now.");
  expect(vi.mocked(notify)).toHaveBeenCalledWith(
    expect.objectContaining({
      id: "billing-read-error",
      tone: "error",
      action: expect.objectContaining({ label: "Try again" }),
    }),
  );
  vi.mocked(notify).mock.calls[0][0].action!.run();
  expect(onRefresh).toHaveBeenCalledOnce();
});

it("says the free month, its three hours and what is left", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-28T06:30:00Z"));
  try {
    await act(async () =>
      root.render(
        <BillingView
          status="ready"
          documents={[]}
          mePlan={{
            plan: { key: "trial", name: "1 month free" },
            allowance: {
              allowanceSeconds: 10_800,
              committedSeconds: 3000,
              availableSeconds: 7800,
              unlimited: false,
            },
            longestCallSeconds: 3600,
            trial: { seconds: 10_800, endsAt: "2026-12-25T07:00:00Z" },
          }}
        />,
      ),
    );
    const text = host.textContent ?? "";
    expect(text).toContain("Free for 1 month or 3 hours of call analysis");
    expect(text).toContain("27 days · 2 h 10 min left");
    expect(text).toContain("1 month free");
    expect(text).not.toContain("You're on the free trial.");
    expect(text).not.toMatch(/15\s*days?/i);
  } finally {
    vi.useRealTimers();
  }
});

it("says when the free month has ended", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-12-26T06:30:00Z"));
  try {
    await act(async () =>
      root.render(
        <BillingView
          status="ready"
          documents={[]}
          mePlan={{
            plan: { key: "trial", name: "1 month free" },
            allowance: {
              allowanceSeconds: 0,
              committedSeconds: 3000,
              availableSeconds: 0,
              unlimited: false,
            },
            longestCallSeconds: 3600,
            trial: { seconds: 10_800, endsAt: "2026-12-25T07:00:00Z" },
          }}
        />,
      ),
    );
    expect(host.textContent).toContain("Your free trial has ended");
  } finally {
    vi.useRealTimers();
  }
});

it("tells a trial buyer where they stand", async () => {
  await act(async () =>
    root.render(<BillingView status="ready" documents={[]} />),
  );
  expect(host.textContent).toContain("You're on the free trial.");
  expect(host.textContent).not.toContain("Full refund within 7 days");
  expect(host.textContent).toContain(
    "No invoices or receipts yet. Each payment adds one here.",
  );
  expect(vi.mocked(notify)).not.toHaveBeenCalled();
});
