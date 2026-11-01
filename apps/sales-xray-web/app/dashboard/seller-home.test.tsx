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

import type { HomeSide } from "./my-day-client";
import { SalesHome } from "./sales-home";
import { NextCall } from "./seller-home";
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
      if (path === "/v1/lead-desk") return Response.json(desk);
      if (path === "/v1/lead-desk/sides?scope=mine")
        return Response.json(sides);
      if (path === "/v1/lead-desk/tasks?view=overdue")
        return Response.json({ tasks: [], counts: {} });
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
  doneFails = false;
  emptyToday = false;
  lateBrochure = false;
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

it("is Dipak's Home: the work in six blocks, each opening its exact place", async () => {
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
  // No line under the number (owner, 31 Oct 2026); what it counts is its description.
  expect(card("new")?.textContent).toBe("New leads8");
  expect(card("new")?.getAttribute("aria-description")).toBe(
    "First call pending",
  );
  expect(card("open")?.getAttribute("href")).toBe(
    "/leads?view=all&step=open_leads",
  );
  expect(card("follow_ups")?.getAttribute("href")).toBe(
    "/leads?view=follow_ups&when=today",
  );
  expect(card("follow_ups")?.querySelector("strong")?.textContent).toBe("7");
  // Tasks today: the Tasks page's Today, the non-calling work (Dipak's
  // handoff; one truth with Tasks, persona QA, 31 Oct 2026).
  expect(card("tasks")?.querySelector("strong")?.textContent).toBe("4");
  // Next to call: one customer, opening the lead; Call now calls them.
  const name = host.querySelector(
    'a[href="/leads?lead=00000000-0000-4000-8000-000000000001"]',
  );
  expect(name?.textContent).toBe("Amit Sample");
  expect(host.textContent).toContain("Meta Ads · Assigned 4 min ago");
  expect(
    host.querySelector("[data-countdown]")?.getAttribute("aria-label"),
  ).toContain("18 left to call today");
  const call = Array.from(host.querySelectorAll("a")).find(
    (link) => link.textContent === "Call Amit now",
  );
  // To Call by name: a bare /leads opens the person's last view (31 Oct).
  expect(call?.getAttribute("href")).toBe("/leads?view=to_call");
  // Today's tasks: three at most; a task with no lead is General.
  const tasks = Array.from(
    host.querySelectorAll('[aria-labelledby="tasks-title"] li'),
    (item) => item.textContent?.replace(/\s+/g, " "),
  );
  expect(tasks).toHaveLength(3);
  expect(tasks[1]).toContain("Prepare tomorrow's demo");
  expect(tasks[1]).toContain("General");
  // Upcoming follow-ups: two at most, See all on this side.
  const follow = host.querySelector('[aria-labelledby="follow-ups-title"]');
  expect(follow?.querySelectorAll("li")).toHaveLength(2);
  expect(follow?.textContent).toContain("Discuss proposal");
  expect(
    follow?.querySelector('a[href="/leads?view=follow_ups&when=upcoming"]'),
  ).not.toBeNull();
  // Today's performance: one row, this side only.
  const performance = host.querySelector(
    '[aria-labelledby="performance-title"]',
  );
  expect(
    Array.from(
      performance?.querySelectorAll("li") ?? [],
      (item) => item.textContent,
    ),
  ).toEqual(["12Tried", "7Connected", "34 minTalk time", "3F/U done"]);
  // No recent calls on Home: history is in Reports and on each lead.
  expect(host.textContent).not.toContain("Recent calls");
});

it("switches to Cold at once, with no second read", async () => {
  answer({ inbound: { leads: 40 }, cold: { imported: 200 } });
  await mount();
  const reads = calls.length;
  await act(async () => radios()[1].click());
  expect(calls.length).toBe(reads);
  expect(window.location.search).toBe("?side=cold");
  expect(card("new")?.textContent).toBe("Unworked180");
  expect(card("new")?.getAttribute("href")).toBe(
    "/leads?view=to_call&step=new&side=cold",
  );
  expect(card("follow_ups")?.getAttribute("href")).toBe(
    "/leads?view=follow_ups&when=today&side=cold",
  );
  expect(host.textContent).toContain("Next cold call");
  expect(host.querySelector("[data-countdown]")).toBeNull();
  const start = Array.from(host.querySelectorAll("a")).find(
    (link) => link.textContent === "Start cold calling",
  );
  expect(start?.getAttribute("href")).toBe("/leads?view=to_call&side=cold");
  // Fresh enquiries waiting on Inbound, one tap to them.
  const alert = Array.from(host.querySelectorAll("a")).find((link) =>
    link.textContent?.startsWith("8 fresh inbound enquiries need attention"),
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
  host.querySelector<HTMLElement>('section[aria-labelledby="tasks-title"]');

// Competitor teardown #1 (1 Nov 2026, Pipedrive Focus, Close Inbox): a late
// task goes first, in red; swipe left, hold or right-click moves it to one of
// the after-call's times.
it("puts a late task first in red, and moves it to next week", async () => {
  lateBrochure = true;
  answer({ inbound: { leads: 40 }, cold: { imported: 0 } });
  await mount();
  const first = tasksBlock()?.querySelector<HTMLLIElement>("ul > li");
  expect(first?.textContent).toContain("Share brochure");
  expect(first?.hasAttribute("data-late")).toBe(true);
  expect(first?.querySelector("[data-late-time]")).not.toBeNull();
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

it("says All clear with the next call when nothing is left, and no helper lines", async () => {
  emptyToday = true;
  answer({ inbound: { leads: 40 }, cold: { imported: 0 } });
  await mount();
  const block = tasksBlock();
  expect(block?.textContent).toContain("All clear");
  expect(
    block?.querySelector<HTMLAnchorElement>("a[href*='view=to_call']")
      ?.textContent,
  ).toContain("Call your next lead");
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
    expect(host.textContent).toContain("Call Meera back");
    expect(host.textContent).not.toContain("Start cold calling");
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
      /Start cold calling|Call \S+ (now|back)/.test(anchor.textContent ?? ""),
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
// thing on Home; Finish opens that lead on Leads at its after-call question.
it("puts a call waiting for its answer first, and Finish opens its question", async () => {
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
    expect(first?.textContent).toContain("Finish: Meera Fictional");
    expect(first?.textContent).toContain("called 4 min ago · How did it go?");
    takeHandedLead();
    const open = [...first!.querySelectorAll("button")].find((button) =>
      button.textContent?.startsWith("Finish:"),
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
// arrived after Today's cards and pushed them down (0.06 at 360 px). Home keeps
// its skeleton until it knows the seller's sides, so they come in together.
it("waits for the seller's sides before drawing Today, so nothing moves", async () => {
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
  expect(host.querySelector('[data-area="cards"]')).toBeNull();
  await act(async () => release());
  for (let step = 0; step < 4; step += 1)
    await act(async () => Promise.resolve());
  expect(host.querySelector('[data-area="side"]')).not.toBeNull();
  expect(host.querySelector('[data-area="cards"]')).not.toBeNull();
});
