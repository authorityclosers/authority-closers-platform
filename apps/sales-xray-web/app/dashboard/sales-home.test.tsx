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
import { resetHomeReads } from "./home-load";
import { NoticeCenter } from "../notice-center";
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
  window.localStorage.clear();
  resetHomeReads();
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

/** One side's figures for the day, all zero unless given (fictional). */
const day = (extra: Record<string, unknown> = {}) => ({
  attempted: 0,
  connected: 0,
  talk_seconds: 0,
  leads_attempted: 0,
  reached: 0,
  interested: 0,
  meetings: 0,
  won: 0,
  worked_interested: 0,
  backlog: 0,
  eligible: 0,
  first_call_minutes: null,
  late: 0,
  missed_calls: 0,
  not_called_back: 0,
  ...extra,
});

/** Today from the Performance engine: one seller, Inbound and Cold apart. */
const effort = (busy: boolean) => ({
  days: 1,
  start: "2026-10-22",
  end: "2026-10-22",
  team: true,
  sellers: [
    {
      person_id: "s1",
      name: "priya example",
      inbound: day(
        busy ? { attempted: 12, connected: 6, talk_seconds: 1500 } : {},
      ),
      cold: day(busy ? { attempted: 5, connected: 1 } : {}),
      breaks: busy
        ? [
            {
              start: "2026-10-22T07:00:00Z",
              end: "2026-10-22T08:15:00Z",
              minutes: 75,
              planned: false,
              approximate: false,
            },
          ]
        : [],
      unplanned_break_minutes: busy ? 75 : 0,
      first_call_at: null,
      last_call_at: null,
      tasks_late: 0,
      missing_recordings: busy ? 1 : 0,
    },
  ],
  inbound: day(
    busy
      ? {
          attempted: 12,
          connected: 6,
          talk_seconds: 1500,
          leads_attempted: 10,
          eligible: 20,
          first_call_minutes: 8,
          late: 1,
          worked_interested: 2,
          reached: 5,
        }
      : {},
  ),
  cold: day(busy ? { attempted: 5, connected: 1, late: 3 } : {}),
  missing_recordings: busy ? 1 : 0,
});

const page = (total: number) => ({
  schema: "lead-desk/1",
  leads: [],
  total,
  next_offset: null,
  stage_counts: {},
  owner_counts: {},
});

/** The side's three counts, each the total of the list its card opens. */
const counts = (
  side: "inbound" | "cold",
  fresh: number,
  open: number,
  unowned: number,
) => ({
  [`/v1/lead-desk/leads?scope=team&side=${side}&view=to_call&step=new`]:
    page(fresh),
  [`/v1/lead-desk/leads?scope=team&side=${side}&view=all&step=open_leads`]:
    page(open),
  [`/v1/lead-desk/leads?scope=unassigned&side=${side}`]: page(unowned),
});

/** A Team today figure's number, by its label. */
const kpi = (label: string) =>
  Array.from(host.querySelectorAll("[data-team-today] li a"))
    .find((link) => link.querySelector("span")?.textContent === label)
    ?.querySelector("strong")?.textContent;

// QA robot 331fa263 (1 Nov 2026): offline, Home said nothing. It says so
// calmly, keeps the numbers it had, and reads again once back online.
it("says it is offline, keeps what it had, and reads again when back", async () => {
  answer({
    "/v1/lead-desk": owner(desk([])),
    "/v1/lead-desk/reports/performance*": performance(),
    "/v1/lead-desk/team": team({ new: 4 }),
    "/v1/lead-desk/performance/sellers*": effort(true),
    ...counts("inbound", 4, 7, 2),
  });
  await mount(true);
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
  let online = false;
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    get: () => online,
  });
  try {
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(host.textContent).toContain(
      "You're offline. Showing what was saved.",
    );
    // Inbound and Cold together, as Growth counts (board 6).
    expect(kpi("Calls")).toBe("17");
    const asked = vi.mocked(fetch).mock.calls.length;
    online = true;
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    await act(async () => Promise.resolve());
    expect(host.textContent).not.toContain("You're offline");
    expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(asked);
  } finally {
    delete (navigator as { onLine?: boolean }).onLine;
  }
});

// ux-audit (9 Nov 2026): in the page's flow, the offline line moved Home 28 to
// 40 px as it came and went. It is a corner card, over the page, so Home stays.
it("says it is offline in the corner, over the page, not in Home's flow", async () => {
  answer({
    "/v1/lead-desk": owner(desk([])),
    "/v1/lead-desk/reports/performance*": performance(),
    "/v1/lead-desk/team": team({ new: 4 }),
    "/v1/lead-desk/performance/sellers*": effort(true),
    ...counts("inbound", 4, 7, 2),
  });
  const corner = document.createElement("div");
  document.body.append(corner);
  const cornerRoot = createRoot(corner);
  await act(async () => cornerRoot.render(<NoticeCenter />));
  await mount(true);
  let online = false;
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    get: () => online,
  });
  try {
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(document.querySelector("[data-corner-own]")?.textContent).toBe(
      "You're offline. Showing what was saved.",
    );
    expect(host.querySelector("[data-home]")?.textContent).not.toContain(
      "You're offline",
    );
    online = true;
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    expect(document.querySelector("[data-corner-own]")?.textContent).toBe("");
  } finally {
    delete (navigator as { onLine?: boolean }).onLine;
    await act(async () => cornerRoot.unmount());
    corner.remove();
  }
});

// The owner (10 Nov 2026, his OnePlus): on Home, even as admin, he was
// "redirected from Team to Me". A choice of Me kept on the device used to be
// applied once the desk answered; Team is where an owner's Home opens.
it("opens an owner's Home on Team, whatever was chosen on an earlier visit", async () => {
  window.localStorage.setItem("sx:home-view:p-owner", "mine");
  window.localStorage.setItem("sx:home-view:person-1", "mine");
  answer({
    "/v1/lead-desk": owner(desk([])),
    "/v1/lead-desk/reports/performance*": performance(),
    "/v1/lead-desk/team": team({ new: 4 }),
    "/v1/lead-desk/performance/sellers*": effort(true),
    ...counts("inbound", 4, 7, 2),
  });
  await mount(true);
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
  // The Team | Me view, not Home's pull-to-refresh mark, which says its own
  // mode too ("idle") and comes first since pull to refresh (62edc21f0).
  expect(
    host
      .querySelector('[data-mode]:not([aria-hidden="true"])')
      ?.getAttribute("data-mode"),
  ).toBe("team");
  expect(window.location.search).not.toContain("view=mine");
});

// The owner (10 Nov 2026): "Refresh isn't well done". Home pulls to refresh as
// Leads does; its mark waits, unseen, at the top.
it("can be pulled down to read everything again", async () => {
  answer({
    "/v1/lead-desk": owner(desk([])),
    "/v1/lead-desk/reports/performance*": performance(),
    "/v1/lead-desk/team": team({ new: 4 }),
    "/v1/lead-desk/performance/sellers*": effort(true),
    ...counts("inbound", 4, 7, 2),
  });
  await mount(true);
  const mark = host.querySelector('[data-home] > [aria-hidden="true"]');
  expect(mark?.getAttribute("data-mode")).toBe("idle");
  expect(mark?.querySelectorAll("i")).toHaveLength(5);
});

it("keeps every figure calm when nothing waits", async () => {
  // Before the working day, so a seller with no call yet isn't news.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-22T03:00:00Z"));
  answer({
    "/v1/lead-desk": owner(desk([])),
    "/v1/lead-desk/reports/performance*": performance({
      sellers: [],
      pipeline: { new: 0, not_connected: 1 },
    }),
    "/v1/lead-desk/team": team({ not_connected: 1, won: 9 }),
    "/v1/lead-desk/performance/sellers*": effort(false),
    ...counts("inbound", 0, 1, 0),
  });
  await mount(true);
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
  expect(host.querySelector("[data-insight]")).toBeNull();
  expect(host.textContent).toContain("Nothing needs you right now. All clear.");
  vi.useRealTimers();
});

it("switches an owner between Team and Me in one tap", async () => {
  answer({
    "/v1/lead-desk": owner(desk([row("ravi sample", { overdue: true })])),
    "/v1/lead-desk/reports/performance*": performance(),
  });
  await mount(true);
  const mine = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Me",
  )!;
  await act(async () => mine.click());
  await act(async () => Promise.resolve());
  expect(window.location.search).toBe("?view=mine");
  // The owner's own day is the seller's Home: Dipak's blocks (handoff, 31 Oct).
  expect(host.textContent).toContain("Next action");
  expect(host.querySelector("a[data-card=tasks]")).not.toBeNull();
  const back = Array.from(host.querySelectorAll("button")).find(
    (button) => button.textContent === "Team",
  )!;
  await act(async () => back.click());
  await act(async () => Promise.resolve());
  expect(window.location.search).toBe("");
  expect(host.querySelector("[data-team-today]")).not.toBeNull();
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

it("says when its content is drawn, so the sandbox card can follow it", async () => {
  // The QA robot, 9 Nov 2026 (474deee5): the sandbox card under Home was
  // drawn while this block was still empty, and pushed down when it filled.
  const drawn = vi.fn();
  let release = () => {};
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      if (String(input) !== "/v1/lead-desk")
        return new Response("{}", { status: 404 });
      await held;
      return new Response(JSON.stringify(desk([])));
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(<SalesHome manager={false} onDrawn={drawn} />),
  );
  expect(drawn).not.toHaveBeenCalled();
  await act(async () => release());
  await vi.waitFor(() => expect(drawn).toHaveBeenCalled());
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
  // Team today, read only: no settings, no My work.
  expect(host.textContent).toContain("Team today");
  expect(host.querySelector('a[href="/settings/lead-rules"]')).toBeNull();
  expect(host.textContent).not.toContain("late follow-up");
  expect(host.textContent).not.toContain("Analyse yourself");
  expect(
    Array.from(host.querySelectorAll("button")).some(
      (button) => button.textContent === "Controls",
    ),
  ).toBe(false);
});
