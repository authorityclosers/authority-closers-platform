// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { WorkspaceAccessContext } from "../../workspace-access";
import { PersonView } from "./person-view";

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
  push.mockClear();
  notices.notify.mockClear();
  calls = [];
  routes = {
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

async function show(id: string, role: "owner" | "admin" | "member" = "owner") {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: ownerId, sessionId: "s-1", tenantId },
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
  expect(host.querySelector("h1")?.textContent).toContain("Member");
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
  expect(marks).toEqual(["Partly seen", "Evidence found"]);
  // Their calls link to each report.
  expect(
    [...host.querySelectorAll(`a[href="/analysis/calls/${callA}"]`)].map(
      (link) => link.textContent,
    ),
  ).toContainEqual(expect.stringContaining("Discovery · Amit, Pixel Digital"));
  // The full list, searchable, is Calls filtered to this person.
  expect(
    host.querySelector(`a[href="/analysis/calls?rep=${ashaId}"]`)?.textContent,
  ).toContain("Open in Calls");
  // Coaching stays private to them.
  expect(host.textContent).toContain(
    "Asha's coaching stays private to them unless they share it.",
  );
  expect(calls.some((call) => call.url.startsWith("/v1/me/coaching"))).toBe(
    false,
  );
});

it("asks before changing a role, then saves it through the organisation API", async () => {
  await show(ashaId);
  const select = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Role for Asha Menon"]',
  );
  expect(select).not.toBeNull();
  await act(async () => {
    select!.value = "admin";
    select!.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("Make Asha Menon admin?");
  const confirm = [...host.querySelectorAll("button")].find(
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

it("shows members only their own calls and offers no actions on others", async () => {
  await show(ashaId, "member");
  expect(host.querySelector("h1")?.textContent).toContain("Asha Menon");
  expect(host.textContent).toContain(
    "Only owners and admins see a teammate's calls and reports.",
  );
  expect(host.querySelector("select")).toBeNull();
  expect(host.textContent).not.toContain("Remove");
});

it("gives invited people a profile with an honest empty state", async () => {
  await show(inviteId);
  expect(host.querySelector("h1")?.textContent).toContain("new@example.com");
  expect(host.querySelector("h1")?.textContent).toContain("Invited");
  expect(host.textContent).toContain("No calls yet: invitation sent");
  expect(host.textContent).toContain("Revoke invitation");
});

it("says so when the person isn't in this organisation", async () => {
  await show("00000000-0000-4000-8000-0000000000ff");
  expect(host.textContent).toContain("This person isn't in the organisation");
  expect(
    host.querySelector('a[href="/organisation?tab=members"]'),
  ).not.toBeNull();
});

it("raises one corner card with Try again when a read fails, never a crash", async () => {
  routes["/v1/organisation/activity?days=84"] = {
    status: 500,
    body: { detail: "Activity is unavailable." },
  };
  await show(ashaId);
  expect(host.querySelector("h1")?.textContent).toContain("Asha Menon");
  expect(notices.notify).toHaveBeenCalledWith(
    expect.objectContaining({
      tone: "error",
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
