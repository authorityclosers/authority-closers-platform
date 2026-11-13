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

it("is the owner's Smart lists Home: the work in five blocks, each opening its exact place", async () => {
  answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
  await mount();
  // Both types: the selector.
  expect(radios().map((radio) => radio.textContent)).toEqual([
    "Inbound Leads",
    "Cold Leads",
  ]);
  // The four cards, Inbound: the side's own three and the shared tasks.
  expect(card("new")?.getAttribute("href")).toBe(
    "/leads?view=to_call&step=new",
  );
  // One caption under the number (Dipak's picture, 2 Nov 2026); the number as
  // H5 writes it, beside a coloured icon (owner's pick, 10 Nov 2026).
  expect(card("new")?.textContent).toBe("New leads8First call pending");
  expect(card("new")?.querySelector("[data-icon] svg")).not.toBeNull();
  expect(card("new")?.getAttribute("data-tone")).toBe("teal");
  expect(card("open")?.getAttribute("href")).toBe(
    "/leads?view=all&step=open_leads",
  );
  // A caption short enough to fit whole on one line at 360 (ux-audit).
  expect(card("open")?.textContent).toMatch(/^Open leads\d*Needs discussion$/);
  expect(card("follow_ups")?.getAttribute("href")).toBe(
    "/leads?view=follow_ups&when=today",
  );
  expect(card("follow_ups")?.textContent).toBe("Follow-ups7Due today");
  // Tasks: the Tasks page's Today, the non-calling work (Dipak's handoff;
  // one truth with Tasks, persona QA, 31 Oct 2026), a box per task due (H3).
  // One overdue on Tasks' Overdue: "1 late", as H5 says it.
  expect(card("tasks")?.textContent).toBe("Tasks4Due today, 1 late");
  expect(card("tasks")?.querySelectorAll("i")).toHaveLength(4);
  // Today's overview, and whose activity it counts.
  expect(host.querySelector("#today-title")?.textContent).toBe(
    "Today's overview",
  );
  expect(host.textContent).toContain("Your inbound lead activity");
  // Next to call: one customer, opening the lead; Call now calls them.
  const name = host.querySelector(
    'a[href="/leads?lead=00000000-0000-4000-8000-000000000001"]',
  );
  expect(name?.textContent).toBe("Amit Sample");
  expect(host.textContent).toContain("Meta Ads · Assigned 4 min ago");
  // Next action, ready to call; one big button, no countdown beside it.
  expect(host.querySelector("#next-title")?.textContent).toBe("Next action");
  expect(host.textContent).toContain("Ready to call");
  expect(host.querySelector("[data-countdown]")).toBeNull();
  const call = Array.from(host.querySelectorAll("a")).find(
    (link) => link.textContent === "Call now",
  );
  // To Call by name: a bare /leads opens the person's last view (31 Oct).
  expect(call?.getAttribute("href")).toBe("/leads?view=to_call");
  // Today's list: today's tasks and today's follow-ups in one list by time,
  // five at most (H5); each says its kind (H4); a past follow-up is Late, its
  // time in red (H1), and its phone opens the list it sits in (bug report #92).
  const list = host.querySelector('[aria-labelledby="list-title"]');
  expect(list?.querySelector("h2")?.textContent).toBe("Today's list");
  const rows = Array.from(
    list?.querySelectorAll("[data-today-row]") ?? [],
    (item) => item.textContent?.replace(/\s+/g, " "),
  );
  expect(rows).toHaveLength(5);
  expect(rows[0]).toContain("Send proposal to Neha");
  expect(rows[0]).toContain("Task");
  // Its lead under the words, which don't name her in full; the words open her.
  expect(rows[0]).toContain("Neha Example");
  expect(
    list?.querySelector("[data-today-row] a[href^='/leads?lead=']")
      ?.textContent,
  ).toBe("Send proposal to Neha");
  expect(rows[1]).toContain("Prepare tomorrow's demo");
  expect(rows[4]).toContain("Call back Neha Example");
  expect(rows[4]).toContain("Follow-up");
  expect(rows[4]).toContain("Late");
  expect(rows[4]).toContain("Discuss proposal");
  const followRow = list?.querySelectorAll("[data-today-row]")[4];
  expect(followRow?.querySelector("[data-late-time]")).not.toBeNull();
  expect(
    followRow
      ?.querySelector('a[aria-label="Call Neha Example"]')
      ?.getAttribute("href"),
  ).toBe("/leads?view=follow_ups&when=today");
  // Upcoming follow-ups and Recent calls left Me with the pick.
  expect(host.querySelector('[aria-labelledby="follow-ups-title"]')).toBeNull();
  expect(host.querySelector('[aria-labelledby="recent-title"]')).toBeNull();
  // Done today: two by two, this side only; each number beside a ring, the
  // arc a real share or none (Connected of Attempted).
  const performance = host.querySelector(
    '[aria-labelledby="performance-title"]',
  );
  expect(performance?.querySelector("h2")?.textContent).toBe("Done today");
  expect(
    Array.from(performance?.querySelectorAll("[data-share]") ?? [], (ring) =>
      ring.closest("a")?.getAttribute("data-done"),
    ),
  ).toEqual(["connected"]);
  expect(
    Array.from(
      performance?.querySelectorAll("li") ?? [],
      (item) => item.textContent,
    ),
  ).toEqual(["Attempted12", "Connected7", "Talk time34 min", "Follow-ups3"]);
  expect(performance?.textContent).toContain("Inbound calls only · Today");
  // Not in the picture: the longest breaks and the Taking new leads pill.
  expect(host.textContent).not.toContain("Your longest breaks");
  expect(host.textContent).not.toContain("Taking new leads");
});

it("switches to Cold at once, with no second read", async () => {
  answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
  await mount();
  const reads = calls.length;
  await act(async () => radios()[1].click());
  expect(calls.length).toBe(reads);
  expect(window.location.search).toBe("?side=cold");
  expect(card("new")?.textContent).toBe("Unworked leads180Never attempted");
  expect(card("new")?.getAttribute("href")).toBe(
    "/leads?view=to_call&step=new&side=cold",
  );
  expect(card("follow_ups")?.getAttribute("href")).toBe(
    "/leads?view=follow_ups&when=today&side=cold",
  );
  expect(host.textContent).toContain("Your cold lead activity");
  expect(host.querySelector("[data-countdown]")).toBeNull();
  const start = Array.from(host.querySelectorAll("a")).find(
    (link) => link.textContent === "Start Cold Calling",
  );
  expect(start?.getAttribute("href")).toBe("/leads?view=to_call&side=cold");
  // Fresh enquiries waiting on Inbound, one tap to them.
  const alert = Array.from(host.querySelectorAll("a")).find((link) =>
    link.textContent?.startsWith("8 fresh inbound leads need attention"),
  );
  expect(alert?.getAttribute("href")).toBe("/leads?view=to_call&step=new");
});

it("hides the selector from someone with one lead type", async () => {
  answer({ inbound: { leads: 0 }, cold: { imported: 200 } });
  await mount();
  expect(radios()).toHaveLength(0);
  // Cold-only: the cold side, Unworked first.
  expect(card("new")?.textContent).toContain("Unworked");
});

it("completes a task in one tap, and puts it back if it wasn't saved", async () => {
  answer({ inbound: { leads: 40 }, cold: { imported: 0 } });
  await mount();
  const box = () =>
    host.querySelector<HTMLInputElement>(
      'input[aria-label="Done: Send proposal to Neha"]',
    );
  await act(async () => box()?.click());
  await act(async () => Promise.resolve());
  expect(
    calls.some((item) => item.path.endsWith("/done") && item.method === "POST"),
  ).toBe(true);
  expect(box()?.checked).toBe(true);
  doneFails = true;
  await act(async () => box()?.click());
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
  // The undo didn't save (a 503 here): the screen keeps what is true.
  expect(box()?.checked).toBe(true);
});

const tasksBlock = () =>
  host.querySelector<HTMLElement>('section[aria-labelledby="list-title"]');

// Competitor teardown #1 (1 Nov 2026, Pipedrive Focus, Close Inbox): a late
// task says so in red, its time red as H1 draws it (owner's pick, 10 Nov 2026),
// and the word Late beside its kind; swipe left, hold or right-click moves it
// to one of the after-call's times.
it("marks a late task in red, and moves it to next week", async () => {
  lateBrochure = true;
  answer({ inbound: { leads: 40 }, cold: { imported: 0 } });
  await mount();
  const first = Array.from(
    tasksBlock()?.querySelectorAll<HTMLLIElement>("ul > li") ?? [],
  ).find((item) => item.textContent?.includes("Share brochure"));
  expect(first?.hasAttribute("data-late")).toBe(true);
  expect(first?.querySelector("[data-late-time]")).not.toBeNull();
  expect(first?.textContent).toContain("Late");
  await act(async () => {
    first?.dispatchEvent(
      new MouseEvent("contextmenu", { bubbles: true, cancelable: true }),
    );
  });
  const week = Array.from(document.querySelectorAll("button")).find(
    (button) => button.textContent === "Next week",
  );
  expect(
    Array.from(
      document.querySelectorAll("button"),
      (button) => button.textContent,
    ).filter((text) =>
      ["In 1 hour", "This evening", "Tomorrow morning", "Next week"].includes(
        text ?? "",
      ),
    ),
  ).toHaveLength(4);
  await act(async () => week?.click());
  await act(async () => Promise.resolve());
  const snooze = calls.find(
    (item) => item.path.endsWith("/snooze") && item.method === "POST",
  );
  expect(JSON.parse(snooze?.body ?? "{}").choice).toBe("week");
});

// Tasks moves a task to Overdue a while after its time; Home's list read only
// Today, so a late task vanished from Home. Now it comes first, Late in red
// (owner's pick, 10 Nov 2026), and one tap marks it done.
it("brings a task from Tasks' Overdue into Today's list, Late, and ticks it done", async () => {
  lateOwn = true;
  answer({ inbound: { leads: 40 }, cold: { imported: 0 } });
  await mount();
  const first = tasksBlock()?.querySelector("[data-today-row]");
  expect(first?.textContent).toContain("Call the bank about the loan papers");
  expect(first?.textContent).toContain("Late");
  expect(first?.querySelector("[data-late-time]")).not.toBeNull();
  // See all opens Tasks on Overdue, where this late task is (Redmi QA).
  expect(
    tasksBlock()?.querySelector('a[href="/leads?tab=tasks&tasks=overdue"]'),
  ).not.toBeNull();
  const box = first?.querySelector<HTMLInputElement>('input[type="checkbox"]');
  await act(async () => box?.click());
  await act(async () => Promise.resolve());
  expect(
    calls.some(
      (item) =>
        item.path.endsWith("-00000000001/done") && item.method === "POST",
    ),
  ).toBe(true);
});

it("says All clear with the next call when nothing is left, and no helper lines", async () => {
  emptyToday = true;
  noFollowUps = true;
  answer({ inbound: { leads: 40 }, cold: { imported: 0 } });
  await mount();
  const block = tasksBlock();
  expect(block?.textContent).toContain("All clear");
  expect(
    block?.querySelector<HTMLAnchorElement>("a[href*='view=to_call']")
      ?.textContent,
  ).toContain("Call your next lead");
  // Once: an empty Upcoming follow-ups says only All clear (ux-audit N9).
  expect(host.textContent?.split("Call your next lead")).toHaveLength(2);
  expect(host.textContent).not.toContain("Fresh enquiries from ads");
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
    expect(host.textContent).toContain(
      "Meta Ads · Missed call 30 min ago · 2 calls · call back",
    );
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

// Teardown 3 (1 Nov 2026): a call still waiting for its answer is the first
// thing on Home; in Dipak's design (4 Nov 2026) it is Pending action, and
// Complete call activity opens that lead on Leads at its after-call question.
it("puts a call waiting for its answer first, as Pending action that opens its question", async () => {
  const assign = vi
    .spyOn(window.location, "assign")
    .mockImplementation(() => {});
  const shared = desk as Record<string, unknown>;
  shared.unanswered = [
    {
      lead_id: "00000000-0000-4000-8000-000000000041",
      name: "meera fictional",
      called_at: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
      event_id: "00000000-0000-4000-a000-000000000041",
    },
  ];
  try {
    answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
    await mount();
    const first = host.querySelector("[data-area]");
    expect(first?.getAttribute("data-area")).toBe("finish");
    expect(first?.textContent).toContain("Pending action");
    expect(first?.textContent).toContain("1 reminder");
    expect(first?.textContent).toContain(
      "Meera Fictional · Last dialled 4 min ago",
    );
    takeHandedLead();
    const open = [...first!.querySelectorAll("button")].find(
      (button) => button.textContent === "Complete call activity",
    );
    await act(async () => open?.click());
    expect(takeHandedLead()).toEqual({
      leadId: "00000000-0000-4000-8000-000000000041",
      call: false,
      log: true,
    });
    expect(assign).toHaveBeenCalledWith("/leads");
  } finally {
    delete shared.unanswered;
    assign.mockRestore();
  }
});

// The test robot (1 Nov 2026): on a slow network the Inbound | Cold selector
// arrived after Today's cards and pushed them down (0.06 at 360 px). Waiting
// for the sides instead left Home blank on 3G (QA robot 4cf9a9c7 and 054a9c20,
// 9 Nov 2026). Today's outline draws at once, the selector's place held
// unseen, and the selector arrives in that place.
it("draws Today's outline at once and holds the selector's place until the sides are known", async () => {
  answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
  const served = globalThis.fetch;
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/v1/lead-desk/sides?scope=mine") await held;
      return served(input, init);
    }),
  );
  await mount();
  const side = () => host.querySelector('[data-area="side"]');
  expect(host.querySelector('[data-area="cards"]')).not.toBeNull();
  expect(side()?.querySelector("[inert] [role=radiogroup]")).not.toBeNull();
  expect(host.querySelector("[data-call-lens]")).toBeNull();
  await act(async () => release());
  for (let step = 0; step < 4; step += 1)
    await act(async () => Promise.resolve());
  expect(side()?.querySelector("[role=radiogroup]")).not.toBeNull();
  expect(side()?.querySelector("[inert]")).toBeNull();
  expect(host.querySelector('[data-area="cards"]')).not.toBeNull();
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
  expect(figures[1]).toEqual(["Outcome known1", `${calls}&outcome=known`]);
  expect(figures[2]?.[0]).toContain("Talk · recordings");
  expect(figures[2]?.[1]).toBe(`${calls}&outcome=connected`);
  expect(host.textContent).not.toContain("Connected");
});

// Home studio, 4 Nov 2026 (judges, round 2): a bad network never takes Dipak's
// blocks away. The four cards keep their places and say "–", never a 0 they
// don't know, and the next call's card offers Try again in the Call's place.
it("keeps every block in place with a dash when the leads didn't load", async () => {
  resetHomeReads();
  answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
  const served = globalThis.fetch;
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) =>
      String(input) === "/v1/lead-desk"
        ? new Response("{}", { status: 503 })
        : served(input, init),
    ),
  );
  await mount();
  expect(
    Array.from(
      host.querySelectorAll("[data-card] strong"),
      (figure) => figure.textContent,
    ),
  ).toEqual(["–", "–", "–", "–"]);
  // A dash opens nothing: there is no list behind a number it doesn't know.
  expect(host.querySelector("a[data-card]")).toBeNull();
  const next = host.querySelector('[aria-labelledby="next-title"]');
  expect(next?.textContent).toContain("Leads didn't load");
  expect(
    Array.from(next?.querySelectorAll("button") ?? [], (button) =>
      button.textContent?.trim(),
    ),
  ).toContain("Try again");
  expect(host.querySelector("[data-call-lens]")).toBeNull();
  resetHomeReads();
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

it("draws Today at once on a later visit, from the sides this device kept", async () => {
  window.localStorage.setItem("sx:home-sides", "11");
  answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
  const served = globalThis.fetch;
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/v1/lead-desk/sides?scope=mine") await held;
      return served(input, init);
    }),
  );
  await mount();
  expect(host.querySelector('[data-area="side"]')).not.toBeNull();
  expect(host.querySelector('[data-area="cards"]')).not.toBeNull();
  // The next call is the one Call pill, its glyph beside the words.
  expect(host.querySelector("[data-call-lens]")?.textContent).toBe("Call now");
  await act(async () => release());
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
