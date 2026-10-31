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

import { SalesHome } from "./sales-home";

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
let calls: { path: string; method: string }[];
let doneFails = false;

function answer(sides: {
  inbound: { leads: number };
  cold: { imported: number };
}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      calls.push({ path, method: init?.method ?? "GET" });
      if (path === "/v1/lead-desk") return Response.json(desk);
      if (path === "/v1/lead-desk/sides?scope=mine")
        return Response.json(sides);
      if (path === "/v1/lead-desk/tasks?view=overdue")
        return Response.json({ tasks: [], counts: {} });
      if (path === "/v1/lead-desk/tasks?view=today")
        return Response.json({
          tasks: [
            task("5", "Send proposal to Neha"),
            task("6", "Call back Ravi", { kind: "call_back" }),
            task("7", "Prepare tomorrow's demo", {
              lead_id: null,
              lead_name: null,
            }),
            task("8", "Share brochure"),
            task("9", "Fourth task"),
          ],
          counts: { today: 5 },
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
  // Tasks today: never a call (a follow-up counts under Follow-ups).
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
