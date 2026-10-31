// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessContext } from "../../workspace-access";
import { PersonView } from "./person-view";
import { fictionalCoaching } from "../../coaching/coaching.fixture";
import { PersonCalls } from "./person-panels";
import type { PersonActivity } from "./person-data";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, prefetch: vi.fn() }),
  usePathname: () => "/organisation/people/x",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
const notices = vi.hoisted(() => ({ notify: vi.fn(), dismissNotice: vi.fn() }));
vi.mock("../../notice-center", () => notices);
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const ownerId = "00000000-0000-4000-8000-000000000001";
const ashaId = "00000000-0000-4000-8000-000000000002";
const inviteId = "00000000-0000-4000-8000-000000000003";
const tenantId = "00000000-0000-4000-8000-000000000004";
const sessionId = "00000000-0000-4000-8000-000000000005";
const callA = "00000000-0000-4000-8000-0000000000a1";
const callB = "00000000-0000-4000-8000-0000000000b2";
const now = Date.now();
const ago = (days: number) => new Date(now - days * 86_400_000).toISOString();

const member = (overrides: Record<string, unknown>) => ({
  person_id: ownerId,
  invite_id: null,
  name: "Owner Person",
  email: "owner@example.com",
  role: "owner",
  status: "active",
  joined_at: "2026-09-01T12:00:00Z",
  last_active_at: "2026-10-01T12:00:00Z",
  minutes_used_30d: 0,
  calls_30d: 0,
  ...overrides,
});
const report = (kind: string, status: string) => ({
  report: {
    content: {
      overview: {
        outcome: { kind },
        final_assessment: { fix_first: "Ask what the budget is." },
      },
      dimensions: [{ dimension_id: "discovery", label: "Discovery", status }],
    },
  },
});

let routes: Record<string, { status: number; body: unknown }>;
let calls: { url: string; method: string; body: string | null }[];
let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false })),
  );
  push.mockClear();
  notices.notify.mockClear();
  calls = [];
  routes = {
    [`/v1/lead-desk/activity?day=recent&person=${ashaId}`]: {
      status: 200,
      body: { items: [], counts: {}, next_before: null },
    },
    [`/v1/lead-desk/activity?day=recent&person=${ownerId}`]: {
      status: 200,
      body: { items: [], counts: {}, next_before: null },
    },
    "/v1/organisation/members": {
      status: 200,
      body: {
        members: [
          member({}),
          member({
            person_id: ashaId,
            name: "Asha Menon",
            email: "asha@example.com",
            role: "member",
          }),
          member({
            person_id: null,
            invite_id: inviteId,
            name: null,
            email: "new@example.com",
            role: "member",
            status: "invited",
            joined_at: null,
            last_active_at: null,
          }),
        ],
      },
    },
    "/v1/organisation/activity?days=84": {
      status: 200,
      body: {
        members: [],
        per_day: [],
        per_rep: [
          {
            person_id: ashaId,
            name: "Asha Menon",
            calls: 2,
            recorded_minutes: 25.5,
            reports_ready: 2,
          },
        ],
        calls: [
          {
            id: callA,
            owner_person_id: ashaId,
            owner_name: "Asha Menon",
            label: "Discovery · Amit, Pixel Digital",
            created_at: ago(1),
            duration_seconds: 900,
            state: "completed",
            has_report: true,
          },
          {
            id: callB,
            owner_person_id: ashaId,
            owner_name: "Asha Menon",
            label: null,
            created_at: ago(9),
            duration_seconds: 630,
            state: "completed",
            has_report: true,
          },
        ],
      },
    },
    [`/v1/conversation/acquisition/submissions/${callA}/report`]: {
      status: 200,
      body: report("follow_up", "observed"),
    },
    [`/v1/conversation/acquisition/submissions/${callB}/report`]: {
      status: 200,
      body: report("follow_up", "partial"),
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({
        url,
        method: init?.method ?? "GET",
        body: init?.body ? String(init.body) : null,
      });
      if ((init?.method ?? "GET") !== "GET")
        return new Response(null, { status: 204 });
      const route = routes[url];
      return route
        ? new Response(JSON.stringify(route.body), {
            status: route.status,
            headers: { "content-type": "application/json" },
          })
        : new Response(JSON.stringify({ detail: "Not found." }), {
            status: 404,
            headers: { "content-type": "application/json" },
          });
    }),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

async function show(
  id: string,
  role: "owner" | "admin" | "member" | "viewer" = "owner",
) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: ownerId, sessionId, tenantId },
          workspaces: [
            {
              tenant_id: tenantId,
              kind: "organisation",
              name: "Fictional Studio",
              role,
              sales_xray_enabled: true,
            },
          ],
          retry: () => {},
        }}
      >
        <PersonView id={id} />
      </WorkspaceAccessContext.Provider>,
    ),
  );
  for (let index = 0; index < 6; index += 1)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
}

it("shows a teammate's profile to an owner: who, figures, weekly charts, reports and calls", async () => {
  await show(ashaId);
  expect(host.querySelector("h1")?.textContent).toContain("Asha Menon");
  expect(host.querySelector("header")?.textContent).toContain("Seller");
  expect(host.textContent).toContain("asha@example.com");
  const tiles = host.querySelector('[aria-label="Last 12 weeks"]');
  expect(tiles?.textContent).toContain("Calls2");
  expect(tiles?.textContent).toContain("Minutes recorded26");
  expect(tiles?.textContent).toContain("of 2 calls");
  expect(host.textContent).toContain("Calls per week");
  expect(host.textContent).toContain("Minutes per week");
  // How calls ended and skills come from the two reports.
  expect(host.textContent).toContain("From 2 reports");
  expect(host.textContent).toContain("Next step agreed");
  const marks = [...host.querySelectorAll('tbody [role="img"]')].map((mark) =>
    mark.getAttribute("aria-label"),
  );
  expect(marks).toEqual(["Partly seen", "Observed"]);
  // Their calls link to each report.
  expect(
    [...host.querySelectorAll(`a[href="/analysis/calls/${callA}"]`)].map(
      (link) => link.textContent,
    ),
  ).toContainEqual(expect.stringContaining("Discovery · Amit, Pixel Digital"));
  // The existing Calls view filters its loaded rows to this person.
  expect(
    host.querySelector(`a[href="/analysis/calls?rep=${ashaId}"]`)?.textContent,
  ).toContain("Open in Calls");
  // The existing shared reader decides whether their focus can be shown.
  expect(host.textContent).toContain("This coaching is not shared with you.");
  expect(
    host.querySelector(`a[href="/coaching?person=${ashaId}"]`)?.textContent,
  ).toBe("Open Coaching");
  expect(
    calls.some((call) => call.url === `/v1/me/coaching/people/${ashaId}`),
  ).toBe(true);
  expect(calls.some((call) => call.url === "/v1/me/coaching")).toBe(false);
  const latest = [...host.querySelectorAll("section")].find((section) =>
    section.querySelector("h2")?.textContent?.startsWith("Latest call"),
  );
  expect(
    latest?.querySelector(`a[href="/analysis/calls/${callA}"]`)?.textContent,
  ).toBe("Open report");
  expect(
    latest?.querySelector(`a[href="/coaching?call=${callA}"]`)?.textContent,
  ).toBe("Call coaching");
});

it("asks before changing a role, then saves it through the organisation API", async () => {
  await show(ashaId);
  const click = async (label: string) =>
    act(async () =>
      [...document.querySelectorAll<HTMLButtonElement>("button")]
        .find((button) => button.textContent === label)
        ?.click(),
    );
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Settings for Asha Menon"]',
      )!
      .click(),
  );
  await click("Change role");
  expect(
    document.querySelector('select[aria-label="Role for Asha Menon"]'),
  ).toBeNull();
  await click("Admin");
  expect(document.body.textContent).toContain("Make Asha Menon admin?");
  const confirm = [...document.querySelectorAll("button")].find(
    (button) => button.textContent === "Change role",
  );
  await act(async () => confirm?.click());
  await act(async () => {});
  expect(calls).toContainEqual({
    url: `/v1/organisation/members/${ashaId}`,
    method: "PATCH",
    body: JSON.stringify({ role: "admin" }),
  });
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({ tone: "success" }),
  );
});

// A teammate's page is for those who see the team (roles.ts "team.view"): a
// member who follows a link to one reads a calm line with a way back, never a
// 403, and nothing about the teammate is read.
it("shows a member a calm line with a way back on a teammate's page, and reads nothing", async () => {
  await show(ashaId, "member");
  expect(host.textContent).toContain(
    "Only owners and managers can see a teammate's page",
  );
  expect(host.textContent).toContain(
    "You see your own calls and reports, not a teammate's.",
  );
  expect(host.querySelector('a[href="/organisation"]')?.textContent).toBe(
    "Back to Organisation",
  );
  expect(host.textContent).not.toContain("Asha Menon");
  expect(host.querySelector('button[aria-haspopup="listbox"]')).toBeNull();
  expect(host.textContent).not.toContain("Remove");
  expect(host.querySelector('a[href^="/coaching"]')).toBeNull();
  expect(calls).toEqual([]);
  expect(notices.notify).not.toHaveBeenCalled();
});

it("gives invited people a profile with an honest empty state", async () => {
  await show(inviteId);
  expect(host.querySelector("h1")?.textContent).toContain("new@example.com");
  expect(host.querySelector("header")?.textContent).toContain("Invited");
  expect(host.textContent).toContain("No calls yet: invitation sent");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Settings for new@example.com"]',
      )!
      .click(),
  );
  expect(document.body.textContent).toContain("Revoke invitation");
});

it("says so when the person isn't in this organisation", async () => {
  await show("00000000-0000-4000-8000-0000000000ff");
  expect(host.textContent).toContain("This person isn't in the organisation");
  expect(
    host.querySelector('a[href="/organisation?tab=members"]'),
  ).not.toBeNull();
});

it("says in place when their calls can't be loaded, with Try again, never a blank page", async () => {
  routes["/v1/organisation/activity?days=84"] = {
    status: 500,
    body: { detail: "Internal Server Error" },
  };
  await show(ashaId);
  expect(host.querySelector("h1")?.textContent).toContain("Asha Menon");
  expect(host.textContent).toContain("Reports are unavailable.");
  expect(host.textContent).toContain("Recent activity");
  expect(host.textContent).not.toContain("Internal Server Error");
  expect(notices.notify).not.toHaveBeenCalled();

  routes["/v1/organisation/activity?days=84"] = {
    status: 200,
    body: { members: [], per_day: [], per_rep: [], calls: [] },
  };
  const retry = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Try again",
  );
  await act(async () => retry?.click());
  for (let index = 0; index < 4; index += 1)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  expect(host.textContent).toContain("Reports and coaching");
});

it("raises one corner card with Try again when the directory can't be read, never a crash", async () => {
  routes["/v1/organisation/members"] = {
    status: 503,
    body: { detail: "Service Unavailable" },
  };
  await show(ashaId);
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({
      tone: "error",
      message: "Check your connection and try again.",
      action: expect.objectContaining({ label: "Try again" }),
    }),
  );
});

it("uses the person's own weekly read where the server has it: exact totals, newest calls listed", async () => {
  const org = routes["/v1/organisation/activity?days=84"].body as {
    calls: unknown[];
  };
  routes[`/v1/organisation/members/${ashaId}/activity?weeks=12`] = {
    status: 200,
    body: {
      person_id: ashaId,
      weeks: Array.from({ length: 12 }, (_, index) => ({
        start: ago(84 - index * 7),
        calls: index === 11 ? 4 : 5,
        recorded_minutes: 60,
        reports_ready: 5,
      })),
      totals: { calls: 64, recorded_minutes: 720, reports_ready: 60 },
      calls: org.calls,
    },
  };
  await show(ashaId);
  const tiles = host.querySelector('[aria-label="Last 12 weeks"]');
  expect(tiles?.textContent).toContain("Calls64");
  expect(tiles?.textContent).toContain("Minutes recorded720");
  expect(host.textContent).toContain("Showing the newest 2 of 64 calls.");
  expect(calls.some((item) => item.url.includes("/activity?days="))).toBe(
    false,
  );
});

it("puts an authorized shared focus and next-call action before the weekly charts", async () => {
  routes[`/v1/me/coaching/people/${ashaId}`] = {
    status: 200,
    body: {
      ...fictionalCoaching,
      person_id: ashaId,
      tenant_id: tenantId,
      session_id: sessionId,
      sandbox: true,
    },
  };
  await show(ashaId);
  expect(host.textContent).toContain(fictionalCoaching.focus!.label);
  expect(host.textContent).toContain(fictionalCoaching.focus!.selected_reason);
  expect(host.textContent).toContain(fictionalCoaching.mission!.behavior);
  expect(host.textContent).toContain("Fictional sandbox coaching");
  const text = host.textContent!;
  expect(text.indexOf("Current focus")).toBeLessThan(
    text.indexOf("Calls per week"),
  );
  expect(text.indexOf("Latest call")).toBeLessThan(
    text.indexOf("Calls per week"),
  );
  expect(calls.every((call) => call.method === "GET")).toBe(true);
});

it.each([
  { person_id: ownerId },
  { tenant_id: "00000000-0000-4000-8000-000000000099" },
  { session_id: "another-session" },
])(
  "does not expose coaching from a different identity or workspace: %j",
  async (wrong) => {
    routes[`/v1/me/coaching/people/${ashaId}`] = {
      status: 200,
      body: {
        ...fictionalCoaching,
        person_id: ashaId,
        tenant_id: tenantId,
        ...wrong,
      },
    };
    await show(ashaId);
    expect(host.textContent).not.toContain(fictionalCoaching.focus!.label);
    expect(host.textContent).not.toContain(fictionalCoaching.mission!.behavior);
    expect(host.textContent).toContain("Open report");
  },
);

it("reads a member's own focus through My coaching and keeps failures distinct from no focus", async () => {
  routes["/v1/me/coaching"] = { status: 503, body: {} };
  await show(ownerId, "member");
  expect(host.textContent).toContain("Coaching didn’t load. Try again.");
  expect(host.textContent).not.toContain("No focus yet");
  expect(host.querySelector('a[href="/coaching"]')?.textContent).toBe(
    "Open Coaching",
  );
  expect(calls.some((call) => call.url.includes("/coaching/people/"))).toBe(
    false,
  );
  routes["/v1/me/coaching"] = {
    status: 200,
    body: { ...fictionalCoaching, person_id: ownerId, tenant_id: tenantId },
  };
  const retry = [...host.querySelectorAll("button")].find(
    (button) => button.textContent === "Try again",
  );
  await act(async () => retry?.click());
  for (let index = 0; index < 4; index += 1)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  expect(host.textContent).toContain(fictionalCoaching.focus!.label);
});

it("keeps a pending latest call distinct from the most recent ready report", async () => {
  const activity = routes["/v1/organisation/activity?days=84"].body as {
    calls: { id: string; has_report: boolean; state: string }[];
  };
  activity.calls[0]!.has_report = false;
  activity.calls[0]!.state = "queued";
  await show(ashaId);
  const latest = [...host.querySelectorAll("section")].find((section) =>
    section.querySelector("h2")?.textContent?.startsWith("Latest call"),
  );
  expect(
    latest?.querySelector(`a[href="/analysis/calls/${callA}"]`)?.textContent,
  ).toBe("View call");
  expect(latest?.querySelector(`a[href="/coaching?call=${callA}"]`)).toBeNull();
  expect(
    latest?.querySelector(`a[href="/analysis/calls/${callB}"]`)?.textContent,
  ).toBe("Open report");
  expect(latest?.textContent).toContain("Latest ready report");
});

it("shows an honest no-focus state only after the authorized coaching read succeeds", async () => {
  routes[`/v1/me/coaching/people/${ashaId}`] = {
    status: 200,
    body: {
      ...fictionalCoaching,
      person_id: ashaId,
      tenant_id: tenantId,
      state: "not_enough_evidence",
      focus: null,
      mission: null,
      practice: null,
      lesson: null,
    },
  };
  await show(ashaId);
  expect(host.textContent).toContain("No focus yet");
  expect(host.textContent).not.toContain(
    "This coaching is not shared with you.",
  );
});

it("keeps known totals honest when individual calls cannot be listed", async () => {
  routes[`/v1/organisation/members/${ashaId}/activity?weeks=12`] = {
    status: 200,
    body: {
      person_id: ashaId,
      weeks: [],
      totals: { calls: 64, recorded_minutes: 720, reports_ready: 60 },
      calls: [],
    },
  };
  await show(ashaId);
  const tiles = host.querySelector('[aria-label="Last 12 weeks"]');
  expect(tiles?.textContent).toContain("Calls64");
  expect(tiles?.textContent).toContain("Unavailable");
  expect(host.textContent).toContain("Recent call details are unavailable.");
  expect(host.textContent).toContain("Weekly activity is unavailable.");
  expect(host.textContent).not.toContain("No calls in the last 12 weeks.");
  expect(host.querySelector('a[href^="/analysis/calls/"]')).toBeNull();
});

const callsPanel = () =>
  [...host.querySelectorAll("section")].find(
    (section) =>
      section.querySelector("h2")?.firstChild?.textContent === "Calls",
  )!;
const callRows = () => [...callsPanel().querySelectorAll("li a")];
const callSearch = () =>
  callsPanel().querySelector<HTMLInputElement>('input[type="search"]')!;
const callCount = () =>
  callsPanel().querySelector('[role="status"]')?.textContent;
const callButton = (name: string) =>
  [...callsPanel().querySelectorAll("button")].find(
    (button) => button.textContent === name,
  )!;

async function searchCalls(value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(callSearch(), value);
    callSearch().dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function listedCalls(): PersonActivity {
  const listed = Array.from({ length: 12 }, (_, index) => ({
    id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    ownerPersonId: ashaId,
    ownerName: "Asha Menon",
    label:
      index === 6
        ? null
        : index === 11
          ? "मराठी · Budget review"
          : index === 0 || index === 10
            ? "Discovery · Same name"
            : `Discovery · Prospect ${index}`,
    createdAt: ago(index + 1),
    durationSeconds: index === 10 ? 0 : 900,
    state: index === 10 ? "queued" : "completed",
    hasReport: index !== 10,
  }));
  return {
    listed,
    calls: 12,
    minutes: 165,
    reportsReady: 11,
    complete: true,
    lastCallAt: listed[0]!.createdAt,
  };
}

async function showCalls(data = listedCalls()) {
  await act(async () =>
    root.render(
      <PersonCalls
        data={data}
        dates={{
          locale: "en-IN",
          timeZone: "Asia/Kolkata",
          today: "2026-10-13",
        }}
        callsHref={`/analysis/calls?rep=${ashaId}`}
      />,
    ),
  );
}

it("searches the person's displayed call names without changing other panels or making reads", async () => {
  await show(ashaId);
  const figures = host.querySelector('[aria-label="Last 12 weeks"]')!.innerHTML;
  const otherPanels = [...host.querySelectorAll("section")]
    .filter((section) => section !== callsPanel())
    .map((section) => section.innerHTML);
  const reads = [...calls];
  const row = callRows()[0]!.innerHTML;
  expect(callSearch().closest("label")?.textContent).toBe("Search these calls");
  expect(callSearch().getAttribute("aria-describedby")).toBe(
    callsPanel().querySelector('[role="status"]')!.id,
  );
  await searchCalls("  dIsCoVeRy  ");
  expect(callCount()).toBe("Matches: 1 of 2 listed calls");
  expect(callRows()[0]!.getAttribute("href")).toBe(`/analysis/calls/${callA}`);
  expect(callRows()[0]!.innerHTML).toBe(row);
  expect(host.querySelector('[aria-label="Last 12 weeks"]')!.innerHTML).toBe(
    figures,
  );
  expect(
    [...host.querySelectorAll("section")]
      .filter((section) => section !== callsPanel())
      .map((section) => section.innerHTML),
  ).toEqual(otherPanels);
  expect(calls).toEqual(reads);
});

it("reaches every matching returned call beyond eight in the original order", async () => {
  const data = listedCalls();
  await showCalls(data);
  expect(callRows()).toHaveLength(8);
  expect(callCount()).toBe("Showing 8 of 12 listed calls");
  expect(callButton("Show all 12 calls").getAttribute("aria-expanded")).toBe(
    "false",
  );
  await searchCalls("Discovery");
  expect(callRows()).toHaveLength(10);
  expect(callCount()).toBe("Matches: 10 of 12 listed calls");
  expect(callRows().map((row) => row.getAttribute("href"))).toEqual(
    data.listed
      .filter((call) => call.label?.startsWith("Discovery"))
      .map((call) => `/analysis/calls/${call.id}`),
  );
  expect(callButton("Show all 12 calls")).toBeUndefined();
  expect(callButton("Show fewer")).toBeUndefined();
});

it("keeps duplicate call names distinct with their own links, dates, durations and statuses", async () => {
  const data = listedCalls();
  await showCalls(data);
  await act(async () => callButton("Show all 12 calls").click());
  const duplicates = [callRows()[0]!.innerHTML, callRows()[10]!.innerHTML];
  await searchCalls("same name");
  expect(callRows().map((row) => row.getAttribute("href"))).toEqual([
    `/analysis/calls/${data.listed[0]!.id}`,
    `/analysis/calls/${data.listed[10]!.id}`,
  ]);
  expect(callRows().map((row) => row.innerHTML)).toEqual(duplicates);
  expect(callRows()[0]!.textContent).toContain("15:00");
  expect(callRows()[1]!.textContent).toContain("—");
  expect(callRows()[0]!.textContent).not.toBe(callRows()[1]!.textContent);
});

it.each([false, true])(
  "clears with focus and restores the prior all=%s disclosure",
  async (all) => {
    await showCalls();
    if (all) await act(async () => callButton("Show all 12 calls").click());
    const before = callRows().map((row) => row.innerHTML);
    await searchCalls("मराठी");
    expect(callCount()).toBe("Matches: 1 of 12 listed calls");
    await act(async () => callButton("Clear search").click());
    expect(callSearch().value).toBe("");
    expect(document.activeElement).toBe(callSearch());
    expect(callRows().map((row) => row.innerHTML)).toEqual(before);
    expect(
      callButton(all ? "Show fewer" : "Show all 12 calls").getAttribute(
        "aria-expanded",
      ),
    ).toBe(String(all));
    expect(callButton("Clear search").disabled).toBe(true);
  },
);

it("shows an honest name-only no-match state and handles whitespace without folding changes", async () => {
  await showCalls();
  for (const query of ["Ready", "15:00", ashaId, "Unknown prospect"]) {
    await searchCalls(query);
    expect(callRows()).toHaveLength(0);
    expect(callCount()).toBe("Matches: 0 of 12 listed calls");
    expect(callsPanel().textContent).toContain(
      "No listed calls match this name.",
    );
    expect(callsPanel().textContent).not.toContain(
      "No calls in the last 12 weeks.",
    );
    expect(callsPanel().textContent).not.toContain(
      "Recent call details are unavailable.",
    );
  }
  await searchCalls("   ");
  expect(callRows()).toHaveLength(8);
  expect(callCount()).toBe("Showing 8 of 12 listed calls");
  expect(callButton("Clear search").disabled).toBe(false);
  await act(async () => callButton("Clear search").click());
  expect(document.activeElement).toBe(callSearch());
});

it("matches the visible unnamed-call fallback and retains incomplete coverage while searching", async () => {
  const data = { ...listedCalls(), complete: false, calls: 64 };
  await showCalls(data);
  expect(callsPanel().textContent).toContain(
    "Showing the newest 12 of 64 calls.",
  );
  const fallback = callRows()[6]!.querySelector("span")!.textContent!;
  await searchCalls(fallback);
  expect(callCount()).toBe("Matches: 1 of 12 listed calls");
  expect(callRows()[0]!.getAttribute("href")).toBe(
    `/analysis/calls/${data.listed[6]!.id}`,
  );
  expect(callsPanel().textContent).toContain(
    "Searching the newest 12 of 64 calls.",
  );
  await searchCalls("Absent call");
  expect(callCount()).toBe("Matches: 0 of 12 listed calls");
  expect(callsPanel().textContent).toContain(
    "Searching the newest 12 of 64 calls.",
  );
  expect(callsPanel().textContent).toContain(
    "No listed calls match this name.",
  );
  await act(async () => callButton("Clear search").click());
  expect(callsPanel().textContent).toContain(
    "Showing the newest 12 of 64 calls.",
  );
});

it.each([0, 64])(
  "does not offer search or invent results when no call details are returned: total %s",
  async (total) => {
    await showCalls({
      ...listedCalls(),
      listed: [],
      calls: total,
      complete: total === 0,
      lastCallAt: null,
    });
    expect(callSearch()).toBeNull();
    expect(callCount()).toBeUndefined();
    expect(callsPanel().textContent).toContain(
      total
        ? "Recent call details are unavailable."
        : "No calls in the last 12 weeks.",
    );
    expect(callsPanel().textContent).not.toContain("Matches: 0");
  },
);

it("shows desk calls and notes with no reports even when the report read fails", async () => {
  routes["/v1/organisation/activity?days=84"] = { status: 500, body: {} };
  const at = new Date().toISOString();
  routes[`/v1/lead-desk/activity?day=recent&person=${ashaId}`] = {
    status: 200,
    body: {
      counts: { call: 1, note: 1 },
      today_counts: { call: 1, note: 1 },
      week_counts: { call: 1, note: 1 },
      next_before: null,
      items: [
        {
          event_id: "call",
          lead_id: "example",
          lead_name: "Rowan Example",
          stage_label: "New",
          event: {
            kind: "call",
            at,
            actor_name: "Asha Menon",
            duration_seconds: 75,
          },
        },
        {
          event_id: "note",
          lead_id: "example",
          lead_name: "Rowan Example",
          stage_label: "New",
          event: {
            kind: "note",
            at,
            actor_name: "Asha Menon",
            note: "Send the details after lunch",
          },
        },
      ],
    },
  };
  await show(ashaId);
  expect(host.textContent).toContain("Asha called Rowan Example");
  expect(host.textContent).toContain("Send the details after lunch");
  expect(
    host.querySelector('[aria-label="Today and the last 7 days"]')?.textContent,
  ).toContain("Calls1today");
  expect(host.textContent).toContain("Reports are unavailable");
});

it("lets a read-only Viewer see the person's work without settings controls", async () => {
  await show(ashaId, "viewer");
  expect(host.querySelector('[aria-label="Recent activity"]')).not.toBeNull();
  expect(
    host.querySelector('[aria-label="Settings for Asha Menon"]'),
  ).toBeNull();
  expect(host.querySelector('[aria-label="Rename Asha Menon"]')).toBeNull();
  expect(
    calls.some(
      (call) =>
        call.url === `/v1/lead-desk/activity?day=recent&person=${ashaId}`,
    ),
  ).toBe(true);
});

// Only an organisation's owners and admins read a teammate's coaching
// (team-coaching-access.ts, after the server's organisation_call_reader): a
// Viewer gets one line, with no read and no link to it.
it("tells a Viewer who reads a teammate's coaching, without reading or linking to it", async () => {
  await show(ashaId, "viewer");
  expect(host.textContent).toContain(
    "Only owners and admins can see a teammate's coaching.",
  );
  expect(host.querySelector('a[href^="/coaching?person="]')).toBeNull();
  expect(calls.some((call) => call.url.startsWith("/v1/me/coaching"))).toBe(
    false,
  );
});

it("keeps removal in the sheet until an explicit confirmation, and Cancel does not write", async () => {
  await show(ashaId);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Settings for Asha Menon"]',
      )!
      .click(),
  );
  await act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Remove person")!
      .click(),
  );
  expect(document.body.textContent).toContain(
    "Their calls stay with the organisation.",
  );
  expect(calls.some((call) => call.method === "DELETE")).toBe(false);
  await act(async () =>
    [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Cancel")!
      .click(),
  );
  expect(calls.some((call) => call.method === "DELETE")).toBe(false);
});

it("offers the self-service rename pencil and a capped display-name form only on one's own page", async () => {
  await show(ownerId);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Rename Owner Person"]')!
      .click(),
  );
  expect(
    document.querySelector<HTMLInputElement>(
      'input[aria-describedby="display-name-limit"]',
    )?.maxLength,
  ).toBe(40);
  expect(document.body.textContent).toContain("Use 1–40 characters");
});
