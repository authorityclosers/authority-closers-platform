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

import { SalesHome } from "./sales-home";
import type { LibrarySubmission } from "../acquisition-client";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const outcomes = (scale: number) => ({
  calls: 10 * scale,
  connected: 4 * scale,
  leads_called: 8 * scale,
  interested: 2 * scale,
  won: 1 * scale,
  new_leads: 6 * scale,
  first_call_minutes: 7,
});

const row = (name: string, extra: Record<string, unknown> = {}) => ({
  lead_id: `00000000-0000-4000-8000-${String(name.length).padStart(12, "0")}`,
  revision: 1,
  name,
  company: null,
  city: "Pune",
  language: null,
  interest: null,
  phone_last4: "3210",
  stage: "new",
  stage_label: "New",
  source: "manual",
  source_label: "Added by hand",
  owner_person_id: null,
  owner_name: null,
  why: "New",
  why_kind: "new",
  next_action_at: null,
  created_at: "2026-10-22T05:30:00Z",
  attempts: 0,
  calls: 0,
  last_result: null,
  last_result_label: null,
  test_data: false,
  ...extra,
});

const desk = (queue: unknown[]) => ({
  me: { person_id: "p", name: "asha", role: "member", can_manage: false },
  numbers: {
    calls: 5,
    connected: 2,
    talk_seconds: 300,
    follow_ups_done: 1,
    new_assigned: 0,
  },
  counts: {
    open: 3,
    new: 1,
    follow_up_due: 0,
    not_connected: 0,
    later_today: 0,
    unassigned: null,
  },
  queue,
  call_mode: "phone",
  sandbox: false,
  generated_at: "2026-10-22T05:30:00Z",
});

/** An owner's own desk: they manage (Roles B, 27 Oct 2026: edits follow can_manage). */
const owner = <T extends { me: object }>(value: T) => ({
  ...value,
  me: { ...value.me, role: "owner", can_manage: true },
});

let root: Root;
let host: HTMLDivElement;

function answer(routes: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const path = String(input);
      const key = Object.keys(routes).find((route) =>
        route.endsWith("*")
          ? path.startsWith(route.slice(0, -1))
          : path === route,
      );
      return key
        ? new Response(JSON.stringify(routes[key]))
        : new Response("{}", { status: 404 });
    }),
  );
}

async function mount(
  manager: boolean,
  layout: "v1" | "v2" = "v1",
  recent: LibrarySubmission[] | null = null,
) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <SalesHome manager={manager} layout={layout} recent={recent} />,
    ),
  );
  await act(async () => Promise.resolve());
}

beforeEach(() => {
  window.history.replaceState(null, "", "/dashboard");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

/** The team's report, for the four and the slider (fictional numbers). */
const performance = (extra: Record<string, unknown> = {}) => ({
  days: 7,
  start: "2026-10-16",
  end: "2026-10-22",
  current: outcomes(2),
  previous: outcomes(1),
  sellers: [
    {
      person_id: "s1",
      name: "priya example",
      calls: 12,
      connected: 6,
      interested: 3,
      won: 2,
      open_leads: 20,
      late: 1,
    },
  ],
  pipeline: { new: 4, not_connected: 3, follow_up: 2 },
  ...extra,
});

const four = () =>
  Array.from(host.querySelectorAll("a[data-four]"), (tile) => [
    tile.getAttribute("data-four"),
    tile.querySelector("strong")?.textContent,
    tile.hasAttribute("data-red"),
  ]);

// Owner's meeting, 28 Oct 2026 (bugs #70–#72): today's four on top, each red
// until its rule is met, the second figures sideways, recent work below.
it("gives an owner the team's four, the slider and recent work, in few words", async () => {
  answer({
    "/v1/lead-desk": owner({
      ...desk([]),
      counts: { ...desk([]).counts, unassigned: 2 },
    }),
    "/v1/lead-desk/reports/performance*": performance(),
    "/v1/lead-desk/team": team({ new: 4, not_connected: 3, won: 3 }),
    "/v1/lead-desk/activity*": { items: [], next_before: null },
  });
  await mount(true);
  await act(async () => Promise.resolve());
  expect(host.querySelector("h2")?.textContent).toBe("Today");
  // New leads untouched; open leads 3 of 10 (30%, above 20%); one late
  // follow-up; two leads with no owner. All four red.
  expect(four()).toEqual([
    ["new", "4", true],
    ["open", "30%", true],
    ["follow_ups", "1", true],
    ["no_owner", "2", true],
  ]);
  const links = Array.from(host.querySelectorAll("a[data-four]"), (tile) =>
    tile.getAttribute("href"),
  );
  expect(links).toEqual([
    "/leads?tab=all&stage=new",
    "/leads?tab=all&stage=not_connected",
    "/leads?tab=all&due=late",
    "/leads?tab=all&stage=open&who=unassigned",
  ]);
  // The screen's one primary action.
  const review = Array.from(host.querySelectorAll("a")).find((link) =>
    link.textContent?.startsWith("Review "),
  );
  expect(review?.textContent).toBe("Review 1 late follow-up");
  // The second figures, sideways.
  expect(
    Array.from(
      host.querySelectorAll("[data-layout=slider] [data-tile]"),
      (tile) => tile.getAttribute("data-tile"),
    ),
  ).toEqual(["won", "interested", "connected", "calls", "new_leads"]);
  // Gone from Home: the long lists and their words.
  expect(host.textContent).not.toContain("Needs you");
  expect(host.textContent).not.toContain("Where leads get stuck");
  expect(host.textContent).not.toContain("leads called");
  // Controls, My day, the team and the reports stay one tap away.
  const buttons = Array.from(
    host.querySelectorAll("button"),
    (button) => button.textContent,
  );
  expect(buttons).toContain("Controls");
  expect(buttons).toContain("My day");
  expect(
    host.querySelector('a[href="/organisation?tab=team"]')?.textContent,
  ).toContain("Your team");
  expect(host.querySelector('a[href="/reports"]')).not.toBeNull();
  // Recent calls first, Activity one tap away.
  expect(host.querySelector('[aria-label="Recent"]')?.textContent).toContain(
    "No calls yet today",
  );
  expect(host.textContent).toContain("Analyse yourself");
});

it("keeps a calm tile for a rule that is met", async () => {
  answer({
    "/v1/lead-desk": owner({
      ...desk([]),
      counts: { ...desk([]).counts, unassigned: 0 },
    }),
    "/v1/lead-desk/reports/performance*": performance({
      sellers: [],
      pipeline: { new: 0, not_connected: 1 },
    }),
    "/v1/lead-desk/team": team({ not_connected: 1, won: 9 }),
  });
  await mount(true);
  await act(async () => Promise.resolve());
  expect(four()).toEqual([
    ["new", "0", false],
    ["open", "10%", false],
    ["follow_ups", "0", false],
    ["no_owner", "0", false],
  ]);
  expect(
    Array.from(host.querySelectorAll("a")).some((link) =>
      link.textContent?.startsWith("Review "),
    ),
  ).toBe(false);
});

it("gives a seller their own four and one primary action", async () => {
  answer({
    "/v1/lead-desk": {
      ...desk([row("ravi sample", { overdue: true, why_kind: "due" })]),
      counts: { ...desk([]).counts, follow_up_due: 2, later_today: 1 },
    },
    "/v1/lead-desk/tasks*": { tasks: [], counts: { today: 2, overdue: 1 } },
  });
  await mount(false);
  await act(async () => Promise.resolve());
  expect(host.querySelector("h2")?.textContent).toBe("Today");
  expect(four()).toEqual([
    ["new", "1", true],
    ["open", "0", false],
    ["follow_ups", "3", true],
    ["tasks", "3", true],
  ]);
  const primary = Array.from(host.querySelectorAll("a")).find((link) =>
    link.textContent?.startsWith("Call "),
  );
  expect(primary?.textContent).toBe("Call Ravi");
  // My work: today's own numbers.
  const work = host.querySelector('[aria-labelledby="my-work-title"]');
  expect(work?.textContent).toContain("Attempted5");
  // Attempted minus connected.
  expect(work?.textContent).toContain("Not connected3");
  expect(work?.textContent).toContain("Talk time5m");
});

it("says all caught up when nobody is due", async () => {
  answer({ "/v1/lead-desk": desk([]) });
  await mount(false);
  expect(host.textContent).toContain("All caught up");
  expect(
    Array.from(host.querySelectorAll("a")).some((link) =>
      link.textContent?.startsWith("Call "),
    ),
  ).toBe(false);
});

it("switches an owner to My day and back in one tap", async () => {
  answer({
    "/v1/lead-desk": owner(desk([row("ravi sample", { overdue: true })])),
    "/v1/lead-desk/reports/performance*": performance(),
  });
  await mount(true);
  const mine = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "My day",
  )!;
  await act(async () => mine.click());
  await act(async () => Promise.resolve());
  expect(window.location.search).toBe("?view=mine");
  // Tasks that didn't load say so, instead of waiting forever.
  expect(host.querySelector("a[data-four=tasks] strong")?.textContent).toBe(
    "–",
  );
  const back = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Team",
  )!;
  await act(async () => back.click());
  await act(async () => Promise.resolve());
  expect(window.location.search).toBe("");
  expect(host.querySelector("a[data-four=no_owner]")).not.toBeNull();
});

// Owner, #20 (26 Oct 2026): a brand-new workspace starts with three steps.
const empty = () => ({
  ...desk([]),
  numbers: {
    calls: 0,
    connected: 0,
    talk_seconds: 0,
    follow_ups_done: 0,
    new_assigned: 0,
  },
  counts: {
    open: 0,
    new: 0,
    follow_up_due: 0,
    not_connected: 0,
    later_today: 0,
    unassigned: null,
  },
});
const team = (byStage: Record<string, number>) => ({
  reps: [],
  settings: {
    revision: 1,
    auto_reassign: false,
    reassign_minutes: 10,
    default_country: "91",
  },
  by_stage: byStage,
  by_source: {},
  unassigned: 0,
  waiting_first_call: 0,
});

it("starts a new seller with three steps, no empty figures", async () => {
  answer({ "/v1/lead-desk": empty() });
  await mount(false);
  expect(host.textContent).toContain("Welcome to Sales X-Ray. Start here.");
  expect(host.textContent).toContain("Analyse a call");
  expect(host.textContent).not.toContain("All caught up");
});

it("starts a new organisation's owner with Add your team", async () => {
  answer({ "/v1/lead-desk": owner(empty()), "/v1/lead-desk/team": team({}) });
  await mount(true);
  await act(async () => Promise.resolve());
  expect(host.textContent).toContain("Add your team");
});

it("keeps the team's Home for an owner whose sellers have leads", async () => {
  answer({
    "/v1/lead-desk": owner(empty()),
    "/v1/lead-desk/team": team({ new: 5 }),
  });
  await mount(true);
  await act(async () => Promise.resolve());
  expect(host.textContent).not.toContain("Welcome to Sales X-Ray");
});

// Roles B (27 Oct 2026): a Viewer reads the team's Home and changes nothing.
it("gives a Viewer the team's Home with nothing to change", async () => {
  answer({
    "/v1/lead-desk": {
      ...empty(),
      me: { ...desk([]).me, role: "viewer", can_manage: false },
      counts: { ...empty().counts, unassigned: 2 },
    },
    "/v1/lead-desk/team": team({}),
    "/v1/lead-desk/reports/performance*": {
      days: 7,
      start: "2026-10-16",
      end: "2026-10-22",
      current: outcomes(2),
      previous: outcomes(1),
      sellers: [],
      pipeline: {},
    },
  });
  await mount(true);
  await act(async () => Promise.resolve());
  // No first steps in an empty workspace, and no My day: a Viewer works no leads.
  expect(host.textContent).not.toContain("Welcome to Sales X-Ray");
  expect(host.textContent).not.toContain("Let's get you calling");
  expect(
    Array.from(host.querySelectorAll("button")).some(
      (button) => button.textContent === "My day",
    ),
  ).toBe(false);
  expect(host.textContent).toContain("How sales are going");
  // The team's four, read only: no Review button, no settings, no My work.
  expect(host.querySelector("a[data-four=no_owner]")).not.toBeNull();
  expect(host.querySelector('a[href="/settings/lead-rules"]')).toBeNull();
  expect(host.textContent).not.toContain("late follow-up");
  expect(host.textContent).not.toContain("Analyse yourself");
  expect(
    Array.from(host.querySelectorAll("button")).some(
      (button) => button.textContent === "Controls",
    ),
  ).toBe(false);
});

// #18: the seller dashboard answers who needs a call before showing history.
it("puts Today and the next call before recent work on the seller dashboard", async () => {
  answer({
    "/v1/lead-desk/activity*": { items: [], next_before: null },
    "/v1/lead-desk": desk([
      row("ravi sample", { overdue: true, why_kind: "due" }),
    ]),
  });
  await mount(false, "v2", [
    {
      id: "00000000-0000-4000-8000-000000000501",
      createdAt: new Date().toISOString(),
      durationSeconds: 120,
      state: "completed",
      hasReport: true,
      label: { displayName: "Fictional discovery", revision: 1 },
    },
  ]);
  expect(host.querySelector("h2")?.textContent).toBe("Today");
  expect(host.textContent).toContain("Call Ravi");
  const text = host.textContent!;
  expect(text.indexOf("Today")).toBeLessThan(text.indexOf("Recent calls"));
  // Activity sits beside Recent calls, one tap away.
  const activity = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Activity",
  )!;
  await act(async () => activity.click());
  expect(host.querySelector('[aria-label="Recent"]')?.textContent).toContain(
    "Notes, messages and stage moves show here.",
  );
});
