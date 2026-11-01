// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: React.ComponentProps<"a">) => (
    <a {...props}>{children}</a>
  ),
}));

import { AlertsView } from "./alerts-page";
import { SummaryView, talk } from "../summary/summary-page";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  push.mockClear();
});

const answer = (body: unknown, status = 200) =>
  vi.fn(async () => new Response(JSON.stringify(body), { status }));

// Competitor teardown 19 (1 Nov 2026): each alert opens its exact list, and a
// lead in it opens on Leads. Fictional names.
it("lists what an alert is about, and opens a lead on Leads", async () => {
  const fetch = answer({
    kind: "missed_call",
    title: "Missed calls not returned in 30 min",
    items: [
      {
        lead_id: "lead-1",
        person_id: null,
        name: "asha fictional",
        seller: "rohan example",
        since: "2026-10-28T10:30:00Z",
      },
    ],
    more: 0,
  });
  vi.stubGlobal("fetch", fetch);
  await act(async () => root.render(<AlertsView initialKind="missed_call" />));
  expect(fetch).toHaveBeenCalledWith(
    "/v1/lead-desk/owner-alerts/list?kind=missed_call",
    expect.anything(),
  );
  expect(host.textContent).toContain("Missed calls not returned in 30 min");
  const row = host.querySelector<HTMLButtonElement>("ul button")!;
  expect(row.textContent).toContain("Asha Fictional");
  expect(row.textContent).toContain("Rohan Example · Called 28 Oct");
  act(() => row.click());
  expect(push).toHaveBeenCalledWith("/leads");
});

it("says when nothing waits, and keeps sellers out", async () => {
  vi.stubGlobal(
    "fetch",
    answer({
      kind: "seller_idle",
      title: "Sellers with no call for 45 min",
      items: [],
      more: 0,
    }),
  );
  await act(async () => root.render(<AlertsView initialKind="seller_idle" />));
  expect(host.textContent).toContain("Nothing here right now.");
  vi.stubGlobal("fetch", answer({ detail: "Only owners and admins" }, 403));
  act(() => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(<AlertsView initialKind="first_call" />));
  expect(host.textContent).toContain("Only owners and admins see alerts.");
});

// Teardown 20: the page the 7 PM summary opens.
it("shows today per seller, with calls missing a recording called out", async () => {
  expect(talk(65 * 60)).toBe("1 h 5 min");
  vi.stubGlobal(
    "fetch",
    answer({
      day: "2026-11-01",
      totals: { sellers: 1, tried: 12, connected: 8, wins: 1 },
      sellers: [
        {
          person_id: "p1",
          name: "priya sample",
          tried: 12,
          connected: 8,
          talk_seconds: 1440,
          follow_ups_done: 3,
          wins: 1,
          no_recording: 2,
        },
      ],
    }),
  );
  await act(async () => root.render(<SummaryView />));
  const row = host.querySelector('[aria-label="Each seller today"] li')!;
  expect(row.textContent).toContain("Priya Sample");
  expect(row.textContent).toContain("12 tried");
  expect(row.textContent).toContain("24 min talk");
  expect(row.textContent).toContain("3 follow-ups");
  expect(row.textContent).toContain("2 calls without a recording");
});
