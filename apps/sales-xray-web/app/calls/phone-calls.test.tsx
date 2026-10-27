// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children: React.ReactNode;
  }) => (
    <a {...props} href={href}>
      {children}
    </a>
  ),
}));
vi.mock("../notice-center", () => ({ notify: () => undefined }));

import { takeHandedLead } from "../leads/lead-handoff";
import type { ActivityItem, LeadEvent } from "../leads/leads-client";
import {
  callLine,
  dayLabel,
  PhoneCalls,
  SHOWN_CALLS,
  weekCalls,
} from "./phone-calls";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const REPORT = "00000000-0000-4000-8000-000000000501";

const call = (extra: Partial<LeadEvent> = {}): LeadEvent =>
  ({
    kind: "call",
    at: "2026-10-27T09:30:00Z",
    actor_name: "Meera Fictional",
    duration_seconds: 194,
    direction: "outgoing",
    via: "phone",
    submission_id: null,
    ...extra,
  }) as LeadEvent;

const item = (id: string, lead: string, event: LeadEvent): ActivityItem => ({
  event_id: id,
  lead_id: `lead-${id}`,
  lead_name: lead,
  stage_label: "Interested",
  event,
});

let container: HTMLDivElement;
let root: Root;
let answer: { status: number; body: unknown };

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  push.mockClear();
  takeHandedLead();
  answer = {
    status: 200,
    body: {
      items: [
        item("e1", "asha fictional", call()),
        item("e2", "ravi sample", {
          ...call({ direction: "missed", duration_seconds: null }),
          at: "2026-10-27T08:00:00Z",
        }),
        item(
          "e3",
          "meera fictional",
          call({ submission_id: REPORT, at: "2026-10-26T12:00:00Z" }),
        ),
        // Notes and stage moves stay in My work.
        item("e4", "karan example", {
          ...call(),
          kind: "note",
          note: "Wants a call after 6",
        }),
      ],
      next_before: null,
      counts: { call: 3, note: 1 },
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(answer.body), {
          status: answer.status,
          headers: { "content-type": "application/json" },
        }),
    ),
  );
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

it("says each call from the seller's side", () => {
  expect(callLine(call())).toBe("You called · 3:14");
  expect(callLine(call({ duration_seconds: 0 }))).toBe(
    "You called · no answer",
  );
  expect(callLine(call({ direction: "incoming", duration_seconds: 65 }))).toBe(
    "They called · 1:05",
  );
  expect(callLine(call({ direction: "missed" }))).toBe("Missed call");
  expect(callLine(call({ via: null, duration_seconds: null }))).toBe(
    "You called",
  );
});

it("names the day in words", () => {
  const now = new Date(2026, 9, 27, 15, 0);
  expect(dayLabel(new Date(2026, 9, 27, 9, 0).toISOString(), now)).toBe(
    "Today",
  );
  expect(dayLabel(new Date(2026, 9, 26, 9, 0).toISOString(), now)).toBe(
    "Yesterday",
  );
});

it("keeps calls only, each once", () => {
  const first = item("e1", "asha fictional", call());
  expect(
    weekCalls([
      first,
      first,
      item("e2", "ravi sample", { ...call(), kind: "note" }),
    ]),
  ).toEqual([first]);
});

it("lists this week's calls first and opens each one", async () => {
  await act(async () => root.render(<PhoneCalls />));
  const rows = [
    ...container.querySelectorAll<HTMLAnchorElement>("a[data-sx-action]"),
  ];
  expect(rows).toHaveLength(3);
  // Names with capitals, who called whom, and missed calls marked.
  expect(rows[0].textContent).toContain("Asha Fictional");
  expect(rows[0].textContent).toContain("You called · 3:14");
  expect(rows[1].textContent).toContain("Missed call");
  expect(rows[1].hasAttribute("data-missed")).toBe(true);
  expect(container.textContent).not.toContain("Karan");

  // A call with a Report opens the Report.
  expect(rows[2].getAttribute("href")).toBe(`/analysis/calls/${REPORT}`);
  expect(rows[2].dataset.sxAction).toBe("report_open");
  expect(rows[2].textContent).toContain("Report");

  // A phone call opens its lead, at that call.
  expect(rows[0].dataset.sxAction).toBe("lead_open");
  await act(async () => rows[0].click());
  expect(push).toHaveBeenCalledWith("/leads");
  expect(takeHandedLead()).toEqual({
    leadId: "lead-e1",
    call: false,
    at: "2026-10-27T09:30:00Z",
  });
});

it("shows at most a few, with the way to all of them", async () => {
  answer.body = {
    items: Array.from({ length: SHOWN_CALLS + 2 }, (_, index) =>
      item(`e${index}`, "asha fictional", call()),
    ),
    next_before: null,
    counts: {},
  };
  await act(async () => root.render(<PhoneCalls />));
  expect(container.querySelectorAll("a[data-sx-action]")).toHaveLength(
    SHOWN_CALLS,
  );
  expect(container.textContent).toContain("See all in My work");
});

it("says how to start when there are no calls yet", async () => {
  answer.body = { items: [], next_before: null, counts: {} };
  await act(async () => root.render(<PhoneCalls />));
  expect(container.textContent).toContain("No calls this week yet");
  expect(container.querySelector('a[href="/leads"]')?.textContent).toBe(
    "Call a lead",
  );
});

it("stays out of the way outside an organisation", async () => {
  answer = { status: 403, body: { detail: "Not in an organisation." } };
  await act(async () => root.render(<PhoneCalls />));
  expect(container.textContent).toBe("");
});
