// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PersonWork, activityDay } from "./person-work";
import { readPersonWork, type ActivityItem } from "../../leads/leads-client";

vi.mock("../../leads/leads-client", async (original) => ({
  ...(await original<typeof import("../../leads/leads-client")>()),
  readPersonWork: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/organisation/people/example",
}));
vi.mock("../../notice-center", () => ({ notify: vi.fn() }));
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
const at = new Date(Date.now() - 86400000).toISOString();
const item = (id: string, kind: string, extra = {}) =>
  ({
    event_id: id,
    lead_id: "lead",
    lead_name: "Rowan Fictional",
    stage_label: "Follow up",
    event: {
      kind,
      at,
      actor_name: "Mira Example",
      note: kind === "note" ? "Call after lunch" : null,
      direction: "outgoing",
      duration_seconds: 75,
      ...extra,
    },
  }) as ActivityItem;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(readPersonWork).mockReset();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
  vi.mocked(readPersonWork).mockResolvedValue({
    items: [
      item("call", "call"),
      item("note", "note"),
      item("message", "message"),
    ],
    next_before: null,
    counts: { call: 1, note: 1 },
    today_counts: { call: 0, note: 0 },
    week_counts: { call: 1, note: 1 },
    last_active_at: at,
    last_call_at: at,
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
it("shows desk calls, notes and messages without reading a report, with the last working day when today is quiet", async () => {
  await act(async () => root.render(<PersonWork personId="seller" />));
  expect(readPersonWork).toHaveBeenCalledWith(
    "seller",
    null,
    expect.any(AbortSignal),
  );
  expect(host.textContent).toContain("Quiet today");
  expect(host.textContent).toContain("Yesterday");
  expect(host.textContent).toContain("Mira called Rowan Fictional");
  expect(host.textContent).toContain("Call after lunch");
  expect(host.textContent).toContain("sent Rowan Fictional");
  expect(
    host.querySelector('[aria-label="Today and the last 7 days"]')?.textContent,
  ).toContain("Calls0today · 1 in 7 days");
  expect(host.textContent).not.toContain("On a call now");
});
it("appends the next server page when Show more is tapped", async () => {
  vi.mocked(readPersonWork)
    .mockResolvedValueOnce({
      items: [item("1", "note")],
      counts: {},
      next_before: at,
    })
    .mockResolvedValueOnce({
      items: [item("2", "message")],
      counts: {},
      next_before: null,
    });
  await act(async () => root.render(<PersonWork personId="seller" />));
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((el) => el.textContent === "Show more")!
      .click(),
  );
  expect(readPersonWork).toHaveBeenLastCalledWith("seller", at);
  expect(
    host.querySelectorAll(
      'ol[aria-label="Recent activity, newest first"] > li ol > li',
    ),
  ).toHaveLength(2);
});
it("keeps actual numbers without requesting animation when reduced motion is enabled", async () => {
  const animate = vi.fn();
  vi.stubGlobal("requestAnimationFrame", animate);
  await act(async () => root.render(<PersonWork personId="seller" />));
  expect(animate).not.toHaveBeenCalled();
  expect(
    host.querySelector('[aria-label="Today and the last 7 days"] strong')
      ?.textContent,
  ).toBe("0");
});
it("labels calendar days in the desk timezone", () => {
  expect(
    activityDay(
      "2026-10-27T21:00:00Z",
      "Asia/Kolkata",
      new Date("2026-10-28T10:00:00Z"),
    ),
  ).toBe("Today");
});

it("includes uploaded calls and ready reports alongside desk work without duplicating a linked call", async () => {
  const saved = [
    {
      id: "00000000-0000-4000-8000-000000000099",
      createdAt: at,
      label: "Fictional saved call",
      ownerName: "Mira Example",
      ownerPersonId: "seller",
      hasReport: true,
      durationSeconds: 60,
      state: "report_ready",
    },
  ];
  await act(async () =>
    root.render(<PersonWork personId="seller" saved={saved} />),
  );
  expect(host.textContent).toContain("Report ready: Fictional saved call");
  expect(host.textContent).toContain("Call after lunch");
});
