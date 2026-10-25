import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

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

import { becauseLine } from "./my-day-client";
import { SalesHome } from "./sales-home";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const HOUR = 3_600_000;

const numbers = (calls: number, connected = 0, follow_ups_done = 0) => ({
  calls,
  connected,
  talk_seconds: calls * 60,
  follow_ups_done,
  new_assigned: 0,
});

const row = (name: string, index: number) => ({
  lead_id: `00000000-0000-4000-8000-0000000005${String(index).padStart(2, "0")}`,
  revision: 1,
  name,
  company: null,
  city: null,
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "follow_up",
  stage_label: "Call back",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: "p",
  owner_name: "kavya fictional",
  why: "Call back now",
  why_kind: "due",
  next_action_at: new Date(Date.now() - HOUR).toISOString(),
  created_at: "2026-10-22T05:30:00Z",
  attempts: 1,
  calls: 1,
  last_result: null,
  last_result_label: null,
  test_data: false,
  overdue: index === 0,
});

const desk = (extra: Record<string, unknown> = {}) => ({
  me: {
    person_id: "p",
    name: "kavya fictional",
    role: "member",
    can_manage: false,
  },
  numbers: numbers(0),
  counts: {
    open: 4,
    new: 0,
    follow_up_due: 2,
    not_connected: 0,
    later_today: 0,
    unassigned: null,
  },
  queue: [row("priya sample", 0), row("rohan example", 1)],
  call_mode: "phone",
  sandbox: false,
  generated_at: new Date().toISOString(),
  numbers_yesterday: numbers(12, 5, 3),
  numbers_week: numbers(40, 18, 9),
  team_pool: { open: 382, unassigned: 40, may_take: true },
  ...extra,
});

const myDay = (extra: Record<string, unknown> = {}) => ({
  schema: "lead-desk/1",
  person_id: "p",
  do_now: [
    {
      lead_id: "00000000-0000-4000-8000-000000000500",
      lead_name: "priya sample",
      task_id: "00000000-0000-4000-8000-000000000600",
      due_at: new Date(Date.now() - 2 * HOUR).toISOString(),
      score: 0.92,
      because: ["promised a call back", "2 h overdue"],
    },
    {
      lead_id: "00000000-0000-4000-8000-000000000501",
      lead_name: "rohan example",
      due_at: null,
      score: 0.61,
      because: ["new lead, 12 min waiting"],
    },
  ],
  today: { calls: 18, connects: 7 },
  progress: [],
  fallback: null,
  ...extra,
});

let root: Root;
let host: HTMLDivElement | undefined;

function answer(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      return path in routes
        ? new Response(JSON.stringify(routes[path]))
        : new Response("{}", { status: 404 });
    }),
  );
}

async function mount() {
  const element = document.createElement("div");
  document.body.append(element);
  host = element;
  root = createRoot(element);
  await act(async () => root.render(<SalesHome manager={false} />));
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
}

const text = () => host?.textContent ?? "";

beforeEach(() => {
  window.history.replaceState(null, "", "/dashboard");
});
afterEach(async () => {
  if (host) {
    await act(async () => root.unmount());
    host.remove();
  }
  vi.unstubAllGlobals();
});

it("words why a lead is there, biggest reason first", () => {
  expect(becauseLine(["promised a call back", "2 h overdue"])).toBe(
    "Promised a call back · 2 h overdue",
  );
  expect(becauseLine([])).toBe("");
});

// Owner program, 25 Oct 2026: "what to do now" first, with why.
it("lists My day's ranked work with why, and calls the first one", async () => {
  answer({ "/v1/lead-desk": desk(), "/v1/lead-desk/my-day": myDay() });
  await mount();
  expect(text()).toContain("Promised a call back · 2 h overdue");
  expect(text()).toContain("New lead, 12 min waiting");
  expect(host!.querySelector('[data-late=""]')?.textContent).toContain(
    "Priya Sample",
  );
  const primary = Array.from(host!.querySelectorAll("a")).find((link) =>
    link.textContent?.startsWith("Call "),
  );
  expect(primary?.textContent).toBe("Call Priya");
  // Today's numbers beside yesterday's; no zero chips.
  const today = host!.querySelector('[aria-label="Today"]');
  expect(today?.textContent).toContain("Calls18");
  expect(today?.textContent).toContain("Yesterday 12");
  expect(today?.textContent).not.toContain("Follow-ups done");
  expect(text()).not.toMatch(/\b0 (to call now|later today)/);
});

it("shows targets with progress and how far behind pace", async () => {
  answer({
    "/v1/lead-desk": desk(),
    "/v1/lead-desk/my-day": myDay({
      progress: [
        {
          metric: "calls",
          period: "day",
          target: 40,
          done: 18,
          pace: 0.65,
          expected: 26,
          behind: true,
          short: 8,
        },
        {
          metric: "connects",
          period: "day",
          target: 5,
          done: 7,
          pace: 0.65,
          expected: 3.25,
          behind: false,
          short: 0,
        },
      ],
    }),
  });
  await mount();
  const targets = host!.querySelector('[aria-label="Your targets"]');
  expect(targets?.textContent).toContain("Calls18 of 40");
  expect(targets?.textContent).toContain("8 behind pace");
  expect(targets?.textContent).toContain("Done for today");
  const meter = host!.querySelector('[role="meter"]');
  expect(meter?.getAttribute("aria-valuenow")).toBe("18");
});

// Owner, 25 Oct 2026: "show the next useful data, the last days or weeks".
it("shows what is next and this week beside last week on an empty day", async () => {
  answer({
    "/v1/lead-desk": desk({ queue: [] }),
    "/v1/lead-desk/my-day": myDay({
      do_now: [],
      today: {},
      fallback: {
        next_up: [
          {
            lead_id: "00000000-0000-4000-8000-000000000502",
            lead_name: "meera fictional",
            at: new Date(Date.now() + 20 * HOUR).toISOString(),
            what: "Call",
          },
        ],
        week: { calls: 40, connects: 18 },
        last_week: { calls: 32, connects: 18 },
        recent: [],
      },
    }),
  });
  await mount();
  expect(text()).toContain("All caught up");
  expect(text()).toContain("Nothing is due now. Next up:");
  expect(host!.querySelector('[aria-label="Next up"]')?.textContent).toContain(
    "Meera Fictional",
  );
  const week = host!.querySelector('[aria-label="This week"]');
  expect(week?.textContent).toContain("Calls40");
  expect(week?.textContent).toContain("25%");
  expect(text()).not.toContain("Calls0");
});

it("tells a seller with no leads what the team has", async () => {
  answer({
    "/v1/lead-desk": desk({
      queue: [],
      counts: { ...desk().counts, open: 0 },
    }),
    "/v1/lead-desk/my-day": myDay({ do_now: [], today: {}, fallback: null }),
  });
  await mount();
  expect(text()).toContain("No leads are yours yet");
  expect(text()).toContain(
    "Your team has 382 open leads, 40 with no owner yet.",
  );
  expect(text()).toContain("New leads come to you the moment they arrive.");
  expect(text()).not.toContain("All caught up");
});

it("lets a manager with no leads share out the ones with no owner", async () => {
  answer({
    "/v1/lead-desk": desk({
      me: { ...desk().me, role: "admin", can_manage: true },
      queue: [],
      counts: { ...desk().counts, open: 0 },
      team_pool: { open: 9, unassigned: 3, may_take: false },
    }),
    "/v1/lead-desk/my-day": myDay({ do_now: [], today: {}, fallback: null }),
  });
  await mount();
  expect(text()).toContain("You aren't taking new leads.");
  // Share out leads opens the sheet in place (Lead OS's distribute).
  const share = Array.from(host!.querySelectorAll("button")).find(
    (button) => button.textContent === "Share out leads",
  );
  expect(share).toBeDefined();
});

it("falls back to the desk's queue and numbers when My day doesn't load", async () => {
  answer({
    "/v1/lead-desk": desk({ numbers: numbers(5, 2, 1) }),
  });
  await mount();
  expect(text()).toContain("Priya Sample");
  expect(text()).toContain("Call Priya");
  const today = host!.querySelector('[aria-label="Today"]');
  expect(today?.textContent).toContain("Follow-ups done1");
  expect(today?.textContent).toContain("Yesterday 3");
});
