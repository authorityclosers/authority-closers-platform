import { act, type AnchorHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

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

import { resetHomeReads } from "./home-load";
import type { HomeSide } from "./my-day-client";
import { SalesHome } from "./sales-home";
import { followUpsDay, NextCall, TodayPerformance } from "./seller-home";
import { takeHandedLead } from "../leads/lead-handoff";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Fictional people and numbers throughout.
const row = (
  name: string,
  id: string,
  extra: Record<string, unknown> = {},
) => ({
  lead_id: `00000000-0000-4000-8000-0000000000${id}`,
  revision: 1,
  name,
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New Lead",
  source: "meta",
  source_label: "Meta Ads",
  owner_person_id: null,
  owner_name: null,
  why: "Assigned 4 min ago",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-31T05:30:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...extra,
});

const numbers = (
  calls: number,
  connected: number,
  talk: number,
  done: number,
) => ({
  calls,
  connected,
  talk_seconds: talk,
  follow_ups_done: done,
  new_assigned: 0,
});

const side = (
  next: ReturnType<typeof row> | null,
  counts: { new: number; open_leads: number; follow_ups_today: number },
  today: ReturnType<typeof numbers>,
  upcoming: ReturnType<typeof row>[] = [],
) => ({
  counts,
  numbers: today,
  numbers_week: today,
  numbers_month: today,
  to_call_today: { left: 18, called: 2 },
  next_lead: next,
  upcoming,
  new_key: "new",
  open_key: "open_leads",
});

const desk = {
  me: {
    person_id: "p",
    name: "asha",
    role: "member",
    can_manage: false,
    taking_leads: true,
  },
  numbers: numbers(43, 16, 3480, 4),
  counts: {
    open: 30,
    new: 8,
    follow_up_due: 0,
    not_connected: 2,
    later_today: 0,
    unassigned: null,
  },
  queue: [row("amit sample", "01")],
  call_mode: "phone",
  sandbox: false,
  generated_at: "2026-10-31T05:30:00Z",
  team_pool: { open: 30, unassigned: 0, may_take: true },
  sides: {
    inbound: side(
      row("amit sample", "01"),
      { new: 8, open_leads: 22, follow_ups_today: 7 },
      numbers(12, 7, 2040, 3),
      [
        row("neha example", "02", {
          stage_label: "Interested",
          next_action_note: "Discuss proposal",
          next_action_at: "2026-10-31T09:30:00Z",
        }),
        row("vikas fictional", "03", {
          next_action_at: "2026-10-31T11:30:00Z",
        }),
        row("third one", "04"),
      ],
    ),
    cold: side(
      row("rohan sample", "05", {
        source_label: "October import",
        why: "Unworked",
      }),
      { new: 180, open_leads: 25, follow_ups_today: 4 },
      numbers(31, 9, 1440, 1),
    ),
  },
};

const task = (
  id: string,
  title: string,
  extra: Record<string, unknown> = {},
) => ({
  task_id: `00000000-0000-4000-9000-0000000000${id}`,
  lead_id: "00000000-0000-4000-8000-000000000002",
  lead_name: "neha example",
  kind: "send_file",
  title,
  note: null,
  starts_at: `2026-10-31T0${id}:30:00Z`,
  ends_at: null,
  location: null,
  status: "open",
  done_at: null,
  original_due_at: `2026-10-31T0${id}:30:00Z`,
  snoozes: 0,
  rollovers: 0,
  source: "seller",
  revision: 1,
  owner_person_id: "p",
  overdue: false,
  bucket: "today",
  ...extra,
});

let root: Root;
let host: HTMLDivElement;
let calls: { path: string; method: string; body?: string }[];
let doneFails = false;
let emptyToday = false;
let lateBrochure = false;
let noFollowUps = false;
let lateOwn = false;

function answer(sides: {
  inbound: { leads: number };
  cold: { imported: number };
}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      calls.push({
        path,
        method: init?.method ?? "GET",
        body: typeof init?.body === "string" ? init.body : undefined,
      });
      if (path === "/v1/lead-desk")
        return Response.json(
          noFollowUps
            ? {
                ...desk,
                sides: {
                  ...desk.sides,
                  inbound: { ...desk.sides.inbound, upcoming: [] },
                },
              }
            : desk,
        );
      if (path === "/v1/lead-desk/sides?scope=mine")
        return Response.json(sides);
      if (path === "/v1/lead-desk/tasks?view=overdue")
        return Response.json({
          tasks: lateOwn
            ? [
                task("1", "Call the bank about the loan papers", {
                  lead_id: null,
                  lead_name: null,
                  overdue: true,
                  bucket: "overdue",
                }),
              ]
            : [],
          counts: {},
        });
      if (path === "/v1/lead-desk/tasks?view=today" && emptyToday)
        return Response.json({ tasks: [], counts: { today: 0, overdue: 0 } });
      if (path.endsWith("/snooze"))
        return Response.json({
          ...task("8", "Share brochure"),
          starts_at: "2026-11-07T04:30:00Z",
        });
      if (path === "/v1/lead-desk/tasks?view=today")
        return Response.json({
          // One overdue, on Tasks' Overdue.
          tasks: [
            task("5", "Send proposal to Neha"),
            task("7", "Prepare tomorrow's demo", {
              lead_id: null,
              lead_name: null,
            }),
            task("8", "Share brochure", { overdue: lateBrochure }),
            task("9", "Fourth task"),
          ],
          counts: { today: 4, overdue: 1 },
        });
      // This week's calls, newest first, for Recent calls.
      if (path.startsWith("/v1/lead-desk/activity"))
        return Response.json({
          items: [
            recentCall("c1", "Rohan Fictional", { outcome: "unknown" }),
            recentCall("c2", "Aakash Sample", {
              duration_seconds: 77,
              outcome: "connected",
              seconds_from: "recording",
            }),
            recentCall("c3", "Sanjay Example", { outcome: "not_connected" }),
            recentCall("c4", "Fourth Fictional", { outcome: "unknown" }),
          ],
          next_before: null,
          counts: {},
        });
      if (path.endsWith("/done") || path.endsWith("/undo")) {
        if (doneFails) return new Response("{}", { status: 503 });
        return Response.json({
          ...task("5", "Send proposal to Neha"),
          status: "done",
        });
      }
      return new Response("{}", { status: 404 });
    }),
  );
}

function recentCall(
  id: string,
  lead: string,
  extra: Record<string, unknown> = {},
) {
  return {
    event_id: id,
    lead_id: `lead-${id}`,
    lead_name: lead,
    stage_label: null,
    side: "inbound",
    event: {
      kind: "call",
      at: new Date().toISOString(),
      actor_name: null,
      direction: null,
      via: null,
      duration_seconds: null,
      submission_id: null,
      simulated: false,
      ...extra,
    },
  };
}

async function mount() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<SalesHome manager={false} />));
  for (let step = 0; step < 4; step += 1)
    await act(async () => Promise.resolve());
}

beforeEach(() => {
  window.history.replaceState(null, "", "/dashboard");
  // Home keeps the seller's sides on the device and its answers in memory;
  // each test starts fresh.
  window.localStorage.clear();
  resetHomeReads();
  doneFails = false;
  emptyToday = false;
  lateBrochure = false;
  noFollowUps = false;
  lateOwn = false;
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

const card = (key: string) =>
  host.querySelector<HTMLAnchorElement>(`a[data-card="${key}"]`);
const radios = () =>
  Array.from(host.querySelectorAll<HTMLButtonElement>('[role="radio"]'));

it("hides the selector from someone with one lead type", async () => {
  answer({ inbound: { leads: 0 }, cold: { imported: 200 } });
  await mount();
  expect(radios()).toHaveLength(0);
  // Cold-only: the cold side, Unworked first.
  expect(card("new")?.textContent).toContain("Unworked");
});

// Leads 2 (1 Nov 2026): a missed call not yet returned is To Call's first row,
// so it can be Home's next lead; Home says so, and its button calls them back.
it("says the next lead rang and wasn't reached, and calls them back", async () => {
  const rang = row("Meera Fictional", "41", {
    missed_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
    missed_calls: 2,
  });
  const own = side(
    rang,
    { new: 1, open_leads: 0, follow_ups_today: 0 },
    numbers(0, 0, 0, 0),
  ) as unknown as HomeSide;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  for (const which of ["inbound", "cold"] as const) {
    await act(async () => root.render(<NextCall side={which} own={own} />));
    for (const chip of ["Meta Ads", "Missed call 30 min ago", "2 calls"])
      expect(host.textContent).toContain(chip);
    expect(host.textContent).toContain("Call back");
    expect(host.textContent).not.toContain("Start Cold Calling");
  }
});

// Phone personas ph2-33 (1 Nov 2026): Start cold calling opens a round at the
// card and dials nothing until Call; a call-back or an Inbound lead dials.
it("starts a cold round at the card, and dials only a call-back or an Inbound lead", async () => {
  const plain = row("Kunal Fictional", "42");
  const rang = row("Meera Fictional", "41", {
    missed_at: new Date(Date.now() - 60_000).toISOString(),
    missed_calls: 1,
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  // The links stay on this page: only what they hand over is checked.
  host.addEventListener("click", (event) => event.preventDefault());
  const own = (lead: ReturnType<typeof row>) =>
    side(
      lead,
      { new: 1, open_leads: 0, follow_ups_today: 0 },
      numbers(0, 0, 0, 0),
    ) as unknown as HomeSide;
  const press = async (
    which: "inbound" | "cold",
    lead: ReturnType<typeof row>,
  ) => {
    await act(async () =>
      root.render(<NextCall side={which} own={own(lead)} />),
    );
    takeHandedLead();
    const link = [...host.querySelectorAll("a")].find((anchor) =>
      /Start Cold Calling|Call (now|back)/.test(anchor.textContent ?? ""),
    );
    await act(async () => link?.click());
    return takeHandedLead();
  };
  expect(await press("cold", plain)).toEqual({
    leadId: plain.lead_id,
    call: false,
    round: true,
  });
  expect(await press("inbound", plain)).toEqual({
    leadId: plain.lead_id,
    call: true,
  });
  expect(await press("cold", rang)).toEqual({
    leadId: rang.lead_id,
    call: true,
  });
});

it("never counts a call whose outcome the phone never said, and each number opens its calls", async () => {
  // Owner and Dipak, 2 Nov 2026: 36 calls, 35 Call-button dials the phone never
  // matched, one recorded call of 77 s.
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const own = {
    numbers: {
      ...numbers(36, 1, 77, 0),
      unknown: 35,
      talk_recorded_seconds: 77,
    },
  } as unknown as HomeSide;
  await act(async () =>
    root.render(<TodayPerformance side="cold" own={own} />),
  );
  const figures = Array.from(host.querySelectorAll("li a"), (link) => [
    link.textContent,
    link.getAttribute("href"),
  ]);
  const calls = "/analysis/calls?day=today&side=cold";
  expect(figures[0]).toEqual(["Attempted36", calls]);
  // Out of the calls attempted, said (the owner, 13 Nov 2026).
  expect(figures[1]).toEqual([
    "Outcome known1 of 36",
    `${calls}&outcome=known`,
  ]);
  expect(figures[2]?.[0]).toContain("Talk · recordings");
  expect(figures[2]?.[1]).toBe(`${calls}&outcome=connected`);
  expect(host.textContent).not.toContain("Connected");
});

// Later visits draw at once from the sides this device saw last, so Today
// and the selector arrive together, with no wait and nothing moving.
// QA robot 27a7dd88 (9 Nov 2026): back on Home from Tasks, the blocks under
// Today's tasks jumped as it grew. A return draws Today's list from what it
// showed last, at once, while its read refreshes it.
it("draws Today's list at once on a return, from what it showed", async () => {
  window.localStorage.setItem("sx:home-sides", "11");
  answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
  await mount();
  for (let step = 0; step < 4; step += 1)
    await act(async () => Promise.resolve());
  const task = () => host.textContent?.includes("Send proposal to Neha");
  expect(task()).toBe(true);
  await act(async () => root.unmount());
  host.remove();
  // Back on Home: the reads are on their way again, and nothing has answered yet.
  const served = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>((input, init) =>
      String(input).startsWith("/v1/lead-desk/tasks") ||
      String(input).startsWith("/v1/lead-desk/activity")
        ? new Promise<Response>(() => {})
        : served(input, init),
    ),
  );
  await mount();
  expect(task()).toBe(true);
});

// Bug report #92: Home's next follow-ups run from now, so one later today is in
// Due Today; Upcoming starts at midnight in India.
it("opens a follow-up's own list: later today Due Today, after midnight Upcoming", () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  try {
    vi.setSystemTime(new Date("2026-11-08T06:00:00Z")); // 11:30 IST
    expect(followUpsDay("2026-11-08T12:00:00Z")).toBe("today"); // 17:30
    expect(followUpsDay("2026-11-08T18:29:00Z")).toBe("today"); // 23:59
    expect(followUpsDay("2026-11-08T18:31:00Z")).toBe("upcoming"); // 00:01, 9 Nov
    expect(followUpsDay(null)).toBe("upcoming");
  } finally {
    vi.useRealTimers();
  }
});
