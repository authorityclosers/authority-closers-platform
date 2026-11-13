// @vitest-environment happy-dom
import { act, type AnchorHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("../shell/app-router", () => ({ useAppRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));

import { takeHandedLead } from "../leads/lead-handoff";
import type { HomeSide } from "./my-day-client";
import { NextCall } from "./seller-home";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  push.mockClear();
  takeHandedLead();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const own = (extra: Record<string, unknown> = {}) =>
  ({
    next_lead: {
      lead_id: "lead-7",
      name: "asha fictional",
      source_label: "Meta Ads",
      why: "New lead",
      ...extra,
    },
  }) as unknown as HomeSide;

// On the page's body (Home's blocks are containers), not in the test's host.
const band = () =>
  document.querySelector<HTMLButtonElement>("[data-call-band] button");

// The owner's pick (13 Nov 2026, seller Flow 1, F1): "Call band above tab
// bar", Leads' own band on Home, so the first call is on the first screen.
it("puts Leads' Call band on Home, calling the next lead", async () => {
  await act(async () => root.render(<NextCall side="inbound" own={own()} />));
  expect(band()?.textContent).toBe("Call Asha");
  await act(async () => band()?.click());
  // As Next action's Call now: the lead, ready to call, on To Call.
  expect(takeHandedLead()).toEqual({ leadId: "lead-7", call: true });
  expect(push).toHaveBeenCalledWith(expect.stringContaining("view=to_call"));
});

it("says call back for one who rang, and starts a cold round on Cold", async () => {
  await act(async () =>
    root.render(
      <NextCall
        side="inbound"
        own={own({
          missed_at: new Date(Date.now() - 60_000).toISOString(),
          missed_calls: 1,
        })}
      />,
    ),
  );
  expect(band()?.textContent).toBe("Call back Asha");
  await act(async () => root.render(<NextCall side="cold" own={own()} />));
  expect(band()?.textContent).toBe("Start Cold Calling");
  await act(async () => band()?.click());
  expect(takeHandedLead()).toEqual({
    leadId: "lead-7",
    call: false,
    round: true,
  });
});

it("has no band without a lead to call, or while Home reads", async () => {
  await act(async () =>
    root.render(<NextCall side="inbound" own={{} as HomeSide} />),
  );
  expect(band()).toBeNull();
  await act(async () =>
    root.render(<NextCall side="inbound" own={own()} state="loading" />),
  );
  expect(band()).toBeNull();
});
