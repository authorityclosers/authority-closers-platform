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
