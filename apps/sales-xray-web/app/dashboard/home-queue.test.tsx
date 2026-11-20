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

import type { LeadRow } from "../leads/leads-client";
import { resetHomeReads } from "./home-load";
import { noteBeside, queueKind, queueLine, waited } from "./queue-words";
import { SalesHome } from "./sales-home";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Round 2, board 2 (owner's pick, 20 Nov 2026): a seller's Home is the work
// queue, the lead picked from it, and a Today column. Fictional people.
const NOW = new Date("2026-11-20T09:10:00Z"); // 2:40 PM in India

const row = (
  name: string,
  id: string,
  extra: Partial<LeadRow> = {},
): LeadRow => ({
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
  owner_person_id: "p",
  owner_name: "asha",
  why: "New lead",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-11-20T08:42:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...extra,
});

const fresh = row("amit sample", "01", { interest: "Coaching programme" });
const late = row("neha example", "02", {
  stage: "follow_up",
  stage_label: "Follow-up",
  calls: 1,
  attempts: 1,
  next_action_at: "2026-11-20T04:30:00Z",
  next_action_note: "Call back Neha Example",
});
const later = row("vikas fictional", "03", {
  stage: "follow_up",
  stage_label: "Follow-up",
  calls: 1,
  attempts: 1,
  next_action_at: "2026-11-20T11:30:00Z",
  next_action_note: "Discuss proposal",
});

const numbers = (calls: number) => ({
  calls,
  connected: 2,
  talk_seconds: 600,
  follow_ups_done: 1,
  new_assigned: 3,
});
const side = (next: LeadRow | null, calls: number) => ({
  counts: { new: 2, open_leads: 9, follow_ups_today: 4 },
  numbers: numbers(calls),
  numbers_week: numbers(calls),
  numbers_month: numbers(calls),
  to_call_today: { left: 3, called: 1 },
  next_lead: next,
  upcoming: [],
  new_key: "new",
  open_key: "open_leads",
});
const desk = (inboundCalls = 5) => ({
  me: { person_id: "p", name: "asha", role: "member", can_manage: false },
  numbers: numbers(inboundCalls),
  counts: {
    open: 9,
    new: 2,
    follow_up_due: 0,
    not_connected: 0,
    later_today: 0,
    unassigned: null,
  },
  queue: [fresh],
  call_mode: "phone",
  sandbox: false,
  generated_at: NOW.toISOString(),
  sides: {
    inbound: side(fresh, inboundCalls),
    cold: side(row("rohan sample", "05"), 7),
  },
});
const effortSide = (minutes: number | null) => ({
  attempted: 5,
  connected: 2,
  talk_seconds: 600,
  leads_attempted: 4,
  reached: 2,
  interested: 0,
  meetings: 0,
  won: 0,
  worked_interested: 0,
  backlog: 0,
  eligible: 4,
  first_call_minutes: minutes,
  late: 0,
  missed_calls: 0,
  not_called_back: 0,
});

let root: Root;
let host: HTMLDivElement;
let calls: { path: string; method: string }[];

function answer(inboundCalls = 5) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      const path = String(input);
      calls.push({ path, method: init?.method ?? "GET" });
      if (path === "/v1/lead-desk") return Response.json(desk(inboundCalls));
      if (path === "/v1/lead-desk/sides?scope=mine")
        return Response.json({
          inbound: { leads: 40 },
          cold: { imported: 100 },
        });
      if (path === "/v1/lead-desk/leads?scope=mine&side=inbound&view=to_call")
        return Response.json({
          leads: [fresh, late, later],
          total: 3,
          next_offset: null,
        });
      if (path === "/v1/lead-desk/leads?scope=mine&side=cold&view=to_call")
        return Response.json({ leads: [], total: 0, next_offset: null });
      if (path.startsWith("/v1/lead-desk/performance/sellers"))
        return Response.json({
          days: 1,
          start: "2026-11-20",
          end: "2026-11-20",
          team: false,
          sellers: [
            {
              person_id: "p",
              name: "asha",
              inbound: effortSide(6),
              cold: effortSide(null),
              breaks: [],
              unplanned_break_minutes: 0,
              first_call_at: null,
              last_call_at: null,
              tasks_late: 0,
              missing_recordings: 0,
            },
          ],
          inbound: effortSide(6),
          cold: effortSide(null),
          missing_recordings: 0,
        });
      if (path === "/v1/lead-desk/tasks?view=today")
        return Response.json({
          tasks: [
            {
              task_id: "00000000-0000-4000-9000-000000000001",
              lead_id: null,
              lead_name: null,
              kind: "other",
              title: "Prepare the demo",
              note: null,
              starts_at: "2026-11-20T10:30:00Z",
              ends_at: null,
              location: null,
              status: "open",
              done_at: null,
              original_due_at: "2026-11-20T10:30:00Z",
              snoozes: 0,
              rollovers: 0,
              source: "seller",
              revision: 1,
              owner_person_id: "p",
              overdue: false,
              bucket: "today",
            },
          ],
          counts: { today: 1, overdue: 0 },
        });
      if (path === "/v1/lead-desk/tasks?view=overdue")
        return Response.json({ tasks: [], counts: {} });
      if (path.endsWith("/done"))
        return Response.json({ status: "done", task_id: "x" });
      return new Response("{}", { status: 404 });
    }),
  );
}

async function mount() {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<SalesHome manager={false} />));
  for (let step = 0; step < 5; step += 1)
    await act(async () => Promise.resolve());
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
  window.history.replaceState(null, "", "/dashboard");
  window.localStorage.clear();
  resetHomeReads();
});
afterEach(async () => {
  // The plain-function cases draw nothing.
  if (root) await act(async () => root.unmount());
  if (host) host.remove();
  root = undefined as unknown as Root;
  host = undefined as unknown as HTMLDivElement;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("says where each To Call row stands, and a note only when it adds something", () => {
  expect(queueKind(fresh, NOW)).toBe("new");
  expect(queueLine(fresh, NOW)).toBe("Waiting 28 min");
  expect(queueKind(late, NOW)).toBe("late");
  expect(queueLine(late, NOW)).toBe("Was due 10:00 AM");
  expect(queueKind(later, NOW)).toBe("later");
  expect(queueLine(later, NOW)).toBe("5:00 PM");
  expect(
    queueKind(row("rang", "09", { missed_at: "2026-11-20T09:00:00Z" }), NOW),
  ).toBe("missed");
  // Board 2: Today's list read "Call back Shubham Rao … Call back Shubham Rao".
  expect(noteBeside("Call back Neha Example", "neha example")).toBeNull();
  expect(noteBeside("Discuss proposal", "vikas fictional")).toBe(
    "Discuss proposal",
  );
  expect(waited(65)).toBe("1 h 5 min");
  expect(waited(3 * 1440)).toBe("3 days");
});

it("is the work queue: To Call in its order, the picked lead ready to call, Today beside it", async () => {
  answer();
  await mount();
  const queue = host.querySelector('[aria-labelledby="queue-title"]');
  // The same list as Leads › To Call, in its order, a heading where the kind changes.
  expect(
    Array.from(queue?.querySelectorAll("h3") ?? [], (h) => h.textContent),
  ).toEqual(["New leads", "Late", "Later today", "Tasks today"]);
  const lines = Array.from(
    queue?.querySelectorAll("li button[aria-pressed]") ?? [],
    (pick) => pick.textContent,
  );
  expect(lines).toEqual([
    "ASAmit SampleWaiting 28 min",
    "NENeha ExampleWas due 10:00 AM",
    "VFVikas Fictional5:00 PM · Discuss proposal",
  ]);
  // Next action's first lead waits on the phone; its row is marked for that.
  expect(queue?.querySelector("li[data-next]")?.textContent).toContain(
    "Amit Sample",
  );
  expect(queue?.textContent).toContain("All 3 in Leads");
  // The preview shows the first lead, then the one picked.
  const preview = () => host.querySelector('[aria-labelledby="preview-title"]');
  expect(preview()?.textContent).toContain("Amit Sample");
  expect(preview()?.textContent).toContain("Coaching programme");
  expect(preview()?.textContent).toContain("waiting 28 min");
  expect(
    Array.from(preview()?.querySelectorAll("a") ?? [], (a) => a.textContent),
  ).toContain("Call Amit");
  const pick = queue?.querySelectorAll<HTMLButtonElement>(
    "li button[aria-pressed]",
  )[1];
  await act(async () => pick?.click());
  expect(pick?.getAttribute("aria-pressed")).toBe("true");
  expect(preview()?.textContent).toContain("Neha Example");
  // Next action says how long a new lead has waited.
  expect(
    host.querySelector("#next-title")?.closest("section")?.textContent,
  ).toContain("waiting 28 min");
  // Today: my speed to lead, the day's numbers, and the lists each opening its own.
  const today = host.querySelector('[aria-labelledby="today-col-title"]');
  expect(today?.textContent).toContain("6 min");
  const line = (key: string) =>
    today?.querySelector<HTMLAnchorElement>(`a[data-line="${key}"]`);
  expect(line("calls")?.textContent).toBe("Calls5");
  expect(line("given")?.textContent).toBe("New leads given to you3");
  expect(line("follow_ups")?.getAttribute("href")).toBe(
    "/leads?view=follow_ups&when=today",
  );
  expect(line("follow_ups")?.hasAttribute("data-card")).toBe(true);
  expect(line("tasks")?.textContent).toBe("Tasks1");
  // The side switch is small, in the header, not a full-width bar.
  expect(
    host.querySelector('[data-queue-home] header [role="radiogroup"]'),
  ).not.toBeNull();
});

it("ticks a task done from the queue", async () => {
  answer();
  await mount();
  const box = host.querySelector<HTMLInputElement>(
    'input[aria-label="Done: Prepare the demo"]',
  );
  await act(async () => box?.click());
  await act(async () => Promise.resolve());
  expect(
    calls.some((item) => item.path.endsWith("/done") && item.method === "POST"),
  ).toBe(true);
});

it("says where today's calls are when this side has none (#170 #174 #175)", async () => {
  answer(0);
  await mount();
  expect(host.querySelector("[data-elsewhere]")?.textContent).toBe(
    "7 tried on Cold today",
  );
});
