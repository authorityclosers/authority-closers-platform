// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const push = vi.fn();
vi.mock("../shell/app-router", () => ({ useAppRouter: () => ({ push }) }));
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
  callsFilter,
  dayLabel,
  PhoneCalls,
  SHOWN_CALLS,
  weekCalls,
} from "./phone-calls";
import { inFilter } from "./call-rows";

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
  window.history.replaceState(null, "", "/analysis/calls");
  await act(async () => rows[0].click());
  expect(push).toHaveBeenCalledWith("/leads");
  // Its Back comes back to Calls (Redmi QA R2, 10 Nov 2026), named and lit
  // as Calls on the way (batch 6, 13 Nov 2026).
  expect(takeHandedLead()).toEqual({
    leadId: "lead-e1",
    call: false,
    at: "2026-10-27T09:30:00Z",
    back: true,
    from: "/analysis/calls",
  });
  window.history.replaceState(null, "", "/");
});

// Redmi QA batch 6 (13 Nov 2026): Back from a lead opened on Calls landed at
// the top of the list. The row opened sits where it was once the list is back.
it("puts the opened row back where it sat on screen", async () => {
  window.history.replaceState(null, "", "/analysis/calls");
  let top = 420;
  const rect = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      return { top: this.dataset.callKey === "e2" ? top : 0 } as DOMRect;
    });
  const scroll = vi.spyOn(window, "scrollBy").mockImplementation(() => {});
  await act(async () => root.render(<PhoneCalls />));
  const missed = container.querySelector<HTMLAnchorElement>(
    'a[data-call-key="e2"]',
  );
  await act(async () => missed?.click());
  act(() => root.unmount());
  // Back: the list comes again, scrolled to its top, the row 300 px higher.
  top = 120;
  root = createRoot(container);
  await act(async () => root.render(<PhoneCalls />));
  expect(scroll).toHaveBeenCalledWith(0, -300);
  // The list comes again as it loads: still put back.
  scroll.mockClear();
  act(() => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(<PhoneCalls />));
  expect(scroll).toHaveBeenCalledWith(0, -300);
  // Once the seller moves the page, it's theirs: a later visit starts at the top.
  act(() => window.dispatchEvent(new Event("wheel")));
  scroll.mockClear();
  act(() => root.unmount());
  root = createRoot(container);
  await act(async () => root.render(<PhoneCalls />));
  expect(scroll).not.toHaveBeenCalled();
  rect.mockRestore();
  scroll.mockRestore();
  window.history.replaceState(null, "", "/");
});

it("each connected call shows its way to a Report; missed calls and reports don't", async () => {
  const activity = answer.body;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const body = String(url).startsWith("/v1/lead-desk/capture-guard")
        ? {
            generated_at: "2026-10-27T10:00:00Z",
            rates: [],
            calls: [
              {
                event_id: "e1",
                lead_id: "lead-e1",
                person_id: null,
                at: "2026-10-27T09:30:00Z",
                state: "uploaded",
                submission_id: null,
                attention: false,
              },
            ],
          }
        : activity;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  await act(async () => root.render(<PhoneCalls />));
  await act(async () => {});
  const rows = [
    ...container.querySelectorAll<HTMLAnchorElement>("a[data-sx-action]"),
  ];
  expect(rows[0].textContent).toContain("Uploaded");
  expect(rows[0].querySelectorAll("i[data-done]")).toHaveLength(5);
  // A row is one link: the state line adds none.
  expect(rows[0].querySelector("a")).toBeNull();
  expect(rows[1].querySelector('[role="img"]')).toBeNull();
  expect(rows[2].querySelector('[role="img"]')).toBeNull();
});

// Redmi QA batch 8 (13 Nov 2026): header search's "Search calls for …" opened
// Calls with every call in Your calls; only the saved calls far below kept the
// words. Your calls finds them too, says so, and All calls clears them.
it("finds the searched words in this week's calls", async () => {
  await act(async () => root.render(<PhoneCalls query=" Ravi " />));
  const rows = [
    ...container.querySelectorAll<HTMLAnchorElement>("a[data-sx-action]"),
  ];
  expect(rows).toHaveLength(1);
  expect(rows[0].textContent).toContain("Ravi Sample");
  expect(container.querySelector("h2")?.textContent).toBe(
    "Your calls with “Ravi”",
  );
  const all = [...container.querySelectorAll("a")].find(
    (link) => link.textContent === "All calls",
  );
  expect(all?.getAttribute("href")).toBe("/analysis/calls");
  await act(async () => root.render(<PhoneCalls query="nobody" />));
  expect(container.textContent).toContain("No calls this week with “nobody”.");
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

// Owner and Dipak, 2 Nov 2026: a dial whose outcome the phone never told us
// says so, and each call says where its seconds came from.
const unknownDial = (extra: Partial<LeadEvent> = {}) =>
  call({ via: null, duration_seconds: null, outcome: "unknown", ...extra });

it("says where each call's seconds came from, and when its outcome is unknown", () => {
  expect(callLine(call({ seconds_from: "call_log" }))).toBe(
    "You called · 3:14 from call history",
  );
  expect(
    callLine(call({ duration_seconds: 77, seconds_from: "recording" })),
  ).toBe("You called · 1:17 from the phone's recording");
  expect(callLine(unknownDial())).toBe("You called · outcome unknown");
  expect(callLine(unknownDial({ outcome: "not_connected" }))).toBe(
    "You called · no answer",
  );
  expect(callLine(unknownDial(), "Asha")).toBe("Asha called · outcome unknown");
});

it("reads a day's filter from the address, and nothing without a day", () => {
  expect(
    callsFilter(new URLSearchParams("day=today&side=cold&outcome=unknown")),
  ).toEqual({
    day: "today",
    person: null,
    team: false,
    side: "cold",
    outcome: "unknown",
  });
  expect(callsFilter(new URLSearchParams("q=asha"))).toBeNull();
  expect(
    callsFilter(new URLSearchParams("day=today&team=1&outcome=odd")),
  ).toMatchObject({ team: true, outcome: null });
});

it("opened from a number, lists that day's calls with that outcome, all of them", async () => {
  const asked: string[] = [];
  answer.body = {
    items: [
      item("u1", "asha fictional", unknownDial()),
      item(
        "c1",
        "ravi sample",
        call({ seconds_from: "call_log", outcome: "connected" }),
      ),
      ...Array.from({ length: SHOWN_CALLS + 1 }, (_, index) =>
        item(`u${index + 2}`, "meera fictional", unknownDial()),
      ),
    ],
    next_before: null,
    counts: {},
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      asked.push(String(url));
      return new Response(JSON.stringify(answer.body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }),
  );
  await act(async () =>
    root.render(
      <PhoneCalls
        filter={{
          day: "today",
          person: null,
          team: false,
          side: null,
          outcome: "unknown",
        }}
      />,
    ),
  );
  const rows = [
    ...container.querySelectorAll<HTMLAnchorElement>("a[data-sx-action]"),
  ];
  expect(rows).toHaveLength(SHOWN_CALLS + 2);
  expect(rows[0].textContent).toContain("You called · outcome unknown");
  expect(container.textContent).not.toContain("Ravi");
  expect(container.querySelector("h2")?.textContent).toBe(
    "Today's calls · outcome unknown",
  );
  expect(
    container.querySelector('a[href="/analysis/calls"]')?.textContent,
  ).toContain("All calls");
  expect(container.textContent).not.toContain("See all in My work");
  expect(
    asked.some((url) => url.includes("day=today") && url.includes("kind=call")),
  ).toBe(true);
});

it("a seller's day names who made each call", async () => {
  answer.body = {
    items: [item("u1", "asha fictional", unknownDial())],
    next_before: null,
    counts: {},
  };
  await act(async () =>
    root.render(
      <PhoneCalls
        filter={{
          day: "today",
          person: "00000000-0000-4000-8000-000000000777",
          team: false,
          side: null,
          outcome: null,
        }}
      />,
    ),
  );
  expect(container.querySelector("a[data-sx-action]")?.textContent).toContain(
    "Meera called · outcome unknown",
  );
});

it("opened from a number, counts calls out only, as the number does", () => {
  // The orchestrator, 3 Nov 2026: Attempted counts calls out, so the list it opens does.
  const filter = callsFilter(new URLSearchParams("day=today"));
  if (!filter) throw new Error("no filter");
  expect(inFilter(item("o1", "asha fictional", call()), filter)).toBe(true);
  for (const direction of [
    "incoming",
    "missed",
    "rejected",
    "blocked",
  ] as const)
    expect(
      inFilter(item("i1", "asha fictional", call({ direction })), filter),
    ).toBe(false);
  // A Call-button dial has no direction: a call out.
  expect(
    inFilter(
      item("d1", "asha fictional", call({ direction: null, via: null })),
      filter,
    ),
  ).toBe(true);
});
