// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WorkspaceAccessContext } from "../workspace-access";
import { OrganisationView } from "./organisation-view";
import { receiptFixture } from "./receipt-activity.fixture";

vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
const notices = vi.hoisted(() => ({
  notify: vi.fn(),
  dismissNotice: vi.fn(),
}));
vi.mock("../notice-center", () => notices);
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const ownerId = "00000000-0000-4000-8000-000000000001";
const memberId = "00000000-0000-4000-8000-000000000002";
const inviteId = "00000000-0000-4000-8000-000000000003";
const tenantId = "00000000-0000-4000-8000-000000000004";
const active = {
  person_id: ownerId,
  invite_id: null,
  name: "Admin",
  email: "admin@example.com",
  role: "owner",
  status: "active",
  joined_at: "2026-09-01T12:00:00Z",
  last_active_at: "2026-10-01T12:00:00Z",
  minutes_used_30d: 12,
  calls_30d: 3,
};
let root: Root;
let host: HTMLDivElement;
let routes: Record<string, unknown>;
let fetchMock: ReturnType<typeof vi.fn>;
let writeStatus: number;
let writeDetail: string;
let accessRetry: ReturnType<typeof vi.fn<() => void>>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
beforeEach(() => {
  window.history.replaceState(null, "", "/organisation");
  notices.notify.mockClear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  writeStatus = 204;
  writeDetail = "";
  accessRetry = vi.fn();
  routes = {
    "/v1/me/sales-xray-workspaces": {
      selected_tenant_id: tenantId,
      workspaces: [
        {
          tenant_id: "personal",
          kind: "personal",
          name: "Personal",
          role: null,
          sales_xray_enabled: true,
        },
        {
          tenant_id: tenantId,
          kind: "organisation",
          name: "Directory name",
          role: "owner",
          sales_xray_enabled: true,
        },
      ],
    },
    "/v1/organisation": {
      tenant_id: tenantId,
      name: "Authority Closers",
      role: "owner",
      verified_domains: ["example.com"],
      auto_join: true,
      member_count: 2,
    },
    "/v1/organisation/settings": {
      tenant_id: tenantId,
      name: "Authority Closers",
      legal_name: "Fictional Limited",
      gstin: "",
      address: "123 Example Street",
      industry: "Training",
      team_size: "3-10",
      website: "https://example.test",
      city: "Example City",
      logo_url: null,
    },
    "/v1/organisation/members": {
      members: [
        active,
        {
          ...active,
          person_id: memberId,
          name: "Dipak",
          email: "dipak@example.com",
          role: "member",
          calls_30d: 0,
          minutes_used_30d: 0,
        },
        {
          ...active,
          person_id: null,
          invite_id: inviteId,
          name: null,
          email: "new@example.com",
          role: "member",
          status: "invited",
          joined_at: null,
          last_active_at: null,
          calls_30d: 0,
          minutes_used_30d: 0,
        },
      ],
    },
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    if (
      path === "/v1/organisation/settings" &&
      init?.method === "PUT" &&
      writeStatus === 204
    ) {
      const details = JSON.parse(String(init.body)) as Record<string, string>;
      const canonical = Object.fromEntries(
        Object.entries(details).map(([key, value]) => [key, value.trim()]),
      );
      routes[path] = { ...(routes[path] as object), ...canonical };
      routes["/v1/organisation"] = {
        ...(routes["/v1/organisation"] as object),
        name: canonical.name,
      };
      return json(routes[path]);
    }
    if (init?.method && init.method !== "GET")
      return writeStatus === 204
        ? new Response(null, { status: 204 })
        : json({ detail: writeDetail }, writeStatus);
    return path in routes
      ? json(routes[path])
      : json({ detail: "Not Found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
async function render(contextTenant = tenantId, authenticated = true) {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated,
          context: {
            personId: ownerId,
            sessionId: "s-1",
            tenantId: contextTenant,
          },
          retry: accessRetry,
        }}
      >
        <OrganisationView />
      </WorkspaceAccessContext.Provider>,
    ),
  );
}
const button = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) =>
      item.getAttribute("aria-label") === name ||
      item.textContent?.trim() === name,
  )!;
const click = (name: string) => act(async () => button(name).click());
/** The confirmation's action button is named for its verb (Add, Remove…). */
const confirm = () =>
  act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')]
      .at(-1)!
      .click(),
  );
const noticeText = () =>
  notices.notify.mock.calls
    .map(([notice]) => `${notice.title} ${notice.message ?? ""}`)
    .join("\n");
const writes = () =>
  fetchMock.mock.calls.filter(
    ([, init]) => init?.method && init.method !== "GET",
  );
const org = () =>
  routes["/v1/organisation"] as { role: string; member_count: number };
async function select(label: string, value: string) {
  await act(async () => {
    const input = host.querySelector<HTMLSelectElement>(
      `select[aria-label="${label}"]`,
    )!;
    input.value = value;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function add() {
  await act(async () => {
    const input = host.querySelector<HTMLInputElement>(
      'input[aria-label="Email to add"]',
    )!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "add@example.com");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
}

it("reads the header, zero usage, dates and invite identity from the real contract", async () => {
  await render();
  expect(host.querySelector("h1")?.textContent).toBe("Authority Closers");
  expect(host.textContent).toContain("2 people");
  await click("Members");
  expect(host.querySelectorAll('[role="row"]')).toHaveLength(4);
  expect(host.textContent).toContain("Invited");
  expect(host.textContent).toContain("Has not joined yet");
  expect(host.textContent).toContain("Joined");
  expect(host.textContent).toContain("Last active");
  expect(host.textContent).toContain("Admin (you)");
  expect(button("Revoke invite for new@example.com")).toBeDefined();
  expect(
    host.querySelector('select[aria-label="Role for new@example.com"]'),
  ).toBeNull();
  // Usage figures live on Overview only, from one source; no zero columns here.
  expect(host.textContent).not.toContain("Minutes");
});

it.each([
  [
    "add",
    add,
    "/v1/organisation/members",
    "POST",
    { email: "add@example.com", role: "member" },
  ],
  [
    "role",
    () => select("Role for Dipak", "admin"),
    `/v1/organisation/members/${memberId}`,
    "PATCH",
    { role: "admin" },
  ],
  [
    "remove",
    () => click("Remove Dipak"),
    `/v1/organisation/members/${memberId}`,
    "DELETE",
    undefined,
  ],
  [
    "transfer",
    () => click("Make Dipak the owner"),
    "/v1/organisation/owner",
    "POST",
    { person_id: memberId },
  ],
  [
    "revoke",
    () => click("Revoke invite for new@example.com"),
    `/v1/organisation/invites/${inviteId}`,
    "DELETE",
    undefined,
  ],
] as const)(
  "confirms %s before sending one keyed action and refreshing both reads",
  async (_, action, path, method, body) => {
    await render();
    await click("Members");
    await action();
    expect(host.querySelector('[role="dialog"]')).not.toBeNull();
    expect(writes()).toHaveLength(0);
    await confirm();
    expect(writes()).toHaveLength(1);
    const [url, init] = writes()[0];
    expect(url).toBe(path);
    expect(init.method).toBe(method);
    expect(init.body ? JSON.parse(String(init.body)) : undefined).toEqual(body);
    expect(new Headers(init.headers).get("Idempotency-Key")).toMatch(
      /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/,
    );
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    for (const read of ["/v1/organisation", "/v1/organisation/members"])
      expect(
        fetchMock.mock.calls.filter(([url]) => url === read).length,
      ).toBeGreaterThan(1);
  },
);
it("cancels a role change without writing", async () => {
  await render();
  await click("Members");
  await select("Role for Dipak", "admin");
  await click("Cancel");
  expect(writes()).toHaveLength(0);
  expect(
    host.querySelector<HTMLSelectElement>('select[aria-label="Role for Dipak"]')
      ?.value,
  ).toBe("member");
});
it("refreshes ownership permissions and uses member additions after a transfer", async () => {
  await render();
  await click("Members");
  await select("Role for the new person", "admin");
  await click("Make Dipak the owner");
  org().role = "admin";
  await confirm();
  expect(host.querySelector("header")?.textContent).toContain(
    "Your role: Admin",
  );
  expect(button("Make Dipak the owner")).toBeUndefined();
  expect(host.querySelector('select[aria-label="Role for Dipak"]')).toBeNull();
  await add();
  await confirm();
  expect(JSON.parse(String(writes()[1][1].body)).role).toBe("member");
});
it("allows admins to add/remove members and revoke pending invites", async () => {
  org().role = "admin";
  const list = routes["/v1/organisation/members"] as {
    members: (typeof active)[];
  };
  list.members[2].role = "admin";
  await render();
  await click("Members");
  expect(
    [
      ...host.querySelectorAll(
        'select[aria-label="Role for the new person"] option',
      ),
    ].map((item) => item.textContent),
  ).toEqual(["Member"]);
  expect(host.querySelector('select[aria-label="Role for Dipak"]')).toBeNull();
  expect(button("Make Dipak the owner")).toBeUndefined();
  expect(button("Remove Admin")).toBeUndefined();
  expect(button("Remove Dipak").disabled).toBe(false);
  expect(button("Revoke invite for new@example.com").disabled).toBe(false);
});
it("uses the API role and shows members only their own row read-only", async () => {
  org().role = "member";
  await render();
  await click("Members");
  expect(host.querySelector("header")?.textContent).toContain(
    "Your role: Member",
  );
  expect(host.querySelectorAll('[role="row"]')).toHaveLength(2);
  expect(host.textContent).not.toContain("dipak@example.com");
  expect(host.textContent).not.toContain("new@example.com");
  // Members see one quiet line instead of a form they cannot use.
  expect(host.querySelector('input[aria-label="Email to add"]')).toBeNull();
  expect(host.textContent).toContain("Only owners and admins can add people");
  expect(button("Remove Admin")).toBeUndefined();
});
it.each([
  [403, "Only the owner can change roles."],
  [404, "Member not found."],
  [409, "Transfer ownership first."],
] as const)("shows the %s action message", async (status, detail) => {
  writeStatus = status;
  writeDetail = detail;
  await render();
  await click("Members");
  await click("Remove Dipak");
  await confirm();
  // Errors are corner cards, never banners inside the page.
  expect(noticeText()).toContain(detail);
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
});
it("hides Organisation after a Personal 404 on a write", async () => {
  writeStatus = 404;
  writeDetail = "No organisation selected.";
  await render();
  await click("Members");
  await click("Remove Dipak");
  await confirm();
  expect(host.textContent).toContain("You are on your personal account");
  expect(
    host.querySelector('nav[aria-label="Organisation sections"]'),
  ).toBeNull();
  expect(host.querySelector('[role="alert"]')).toBeNull();
});
it.each(["/v1/organisation", "/v1/organisation/members"])(
  "hides Organisation for Personal 404 from %s",
  async (path) => {
    const ordinaryFetch = fetchMock.getMockImplementation()! as (
      path: string,
      init?: RequestInit,
    ) => Promise<Response>;
    fetchMock.mockImplementation((url, init) =>
      url === path
        ? Promise.resolve(json({ detail: "No organisation selected." }, 404))
        : ordinaryFetch(url, init),
    );
    await render();
    expect(host.textContent).toContain("You are on your personal account");
    expect(host.querySelector('[role="alert"]')).toBeNull();
  },
);
it("does not invent rows or usage when members cannot load", async () => {
  delete routes["/v1/organisation/members"];
  await render();
  await click("Members");
  expect(host.querySelectorAll('[role="row"]')).toHaveLength(1);
  expect(host.textContent).toContain("Members could not be loaded");
  expect(host.textContent).not.toContain("admin@example.com");
  expect(
    host.querySelector<HTMLInputElement>('input[aria-label="Email to add"]')
      ?.disabled,
  ).toBe(true);
});
it("shows no promised Create/Join buttons on Personal and makes no organisation reads", async () => {
  (
    routes["/v1/me/sales-xray-workspaces"] as { selected_tenant_id: string }
  ).selected_tenant_id = "personal";
  await render();
  expect(host.textContent).toContain("You are on your personal account");
  expect(host.textContent).toContain("To open Directory name");
  expect(host.textContent).not.toMatch(/soon/i);
  expect(host.querySelectorAll("button")).toHaveLength(0);
  expect(
    fetchMock.mock.calls.some(([path]) => path.startsWith("/v1/organisation")),
  ).toBe(false);
});
it("rejects expanded directory responses without the old workspace list", async () => {
  routes["/v1/me/sales-xray-workspaces"] = {
    ...(routes["/v1/me/sales-xray-workspaces"] as object),
    unexpected: true,
  };
  await render();
  expect(host.textContent).toContain("The organisation could not be loaded");
  expect(
    fetchMock.mock.calls.some(([path]) => path === "/v1/me/workspaces"),
  ).toBe(false);
});

const day = (daysAgo: number) =>
  new Date(Date.now() - daysAgo * 86_400_000).toISOString().slice(0, 10);
const deskId = "00000000-0000-4000-8000-000000000005";
const testId = "00000000-0000-4000-8000-000000000006";
function activityRoutes(activeDays = [0]) {
  const person = (
    id: string,
    name: string,
    email: string,
    role = "member",
  ) => ({
    ...active,
    person_id: id,
    name,
    email,
    role,
  });
  routes["/v1/organisation/members"] = {
    members: [
      person(ownerId, "Admin", "admin@fictional-studio.in", "owner"),
      person(deskId, "Admin", "desk@fictional-mail.in"),
      person(memberId, "Dipak", "dipak@fictional-studio.in"),
      person(testId, "Quinn Fixture", "qa-quinn@example.test"),
    ],
  };
  (routes["/v1/organisation"] as { member_count: number }).member_count = 4;
  routes["/v1/organisation/activity?days=30"] = {
    // Usage-ledger totals deliberately disagree; Overview must not use them.
    members: [
      {
        person_id: ownerId,
        calls: 2,
        minutes: 9,
        reports_ready: 0,
        last_call_at: null,
      },
    ],
    calls: activeDays.map((ago, index) => ({
      id: `00000000-0000-4000-8000-0000000001${String(index).padStart(2, "0")}`,
      owner_person_id: ownerId,
      owner_name: "Admin",
      label: index === 0 ? null : "Fictional follow-up",
      created_at: `${day(ago)}T09:30:00Z`,
      duration_seconds: 252,
      state: index === 0 ? "report_ready" : "processing",
      has_report: index === 0,
    })),
    per_day: activeDays.map((ago, index) => ({
      date: day(ago),
      calls: 1,
      recorded_minutes: 4.2,
      reports_ready: index === 0 ? 1 : 0,
    })),
    per_rep: [
      {
        person_id: ownerId,
        name: "Admin",
        calls: activeDays.length,
        recorded_minutes: 4.2 * activeDays.length,
        reports_ready: 1,
      },
    ],
  };
}
const kpi = (label: string) =>
  [...host.querySelectorAll("dt")].find((node) => node.textContent === label)
    ?.parentElement?.textContent;

it("reconciles every Overview figure with the calls it lists", async () => {
  activityRoutes();
  await render();
  expect(kpi("Calls")).toBe("Calls1call saved");
  expect(kpi("Minutes recorded")).toBe(
    "Minutes recorded4length of those calls",
  );
  expect(kpi("Reports ready")).toBe("Reports ready1of 1 call");
  expect(kpi("People with calls")).toBe("People with calls1of 4 members");
  expect(host.textContent).not.toContain("2 calls");
  const rows = host.querySelectorAll('[aria-label="Team calls"] a[role="row"]');
  expect(rows).toHaveLength(1);
  expect(rows[0].querySelector("[data-unnamed]")?.textContent).toMatch(
    /^Sales call · \S/,
  );
  expect(rows[0].textContent).toContain("Report ready");
  // One sparse day is not a trend in the figure strip.
  expect(host.querySelector('dl [role="img"]')).toBeNull();
});

it("lists active people first and folds quiet and test accounts away", async () => {
  activityRoutes();
  await render();
  const people = () =>
    [...host.querySelectorAll('[aria-labelledby="org-people"] li')].map(
      (item) => item.textContent,
    );
  expect(people()).toHaveLength(1);
  expect(people()[0]).toContain("1 call");
  // Two people share a name, so each shows the email that tells them apart.
  expect(people()[0]).toContain("admin@fictional-studio.in");
  expect(host.textContent).not.toContain("Dipak");
  await click("3 more people with no calls or test accounts");
  expect(people()).toHaveLength(4);
  expect(people()[1]).toContain("desk@fictional-mail.in");
  expect(people().at(-1)).toContain("Quinn FixtureTest");
  expect(host.textContent).toContain("No calls");
});

it("draws a 30-day bar only with at least three active days", async () => {
  activityRoutes([0, 3, 9]);
  await render();
  expect(
    host.querySelector('[aria-label="Calls per day over the last 30 days"]')
      ?.children,
  ).toHaveLength(30);
  expect(kpi("Reports ready")).toBe("Reports ready1of 3 calls");
  expect(host.textContent).toContain("Analysis in progress");
});

it("shows each person's calls in each of the last four weeks, oldest first", async () => {
  activityRoutes([0, 3, 9]);
  await render();
  const bars = host.querySelector(
    '[aria-labelledby="org-people"] [role="img"]',
  );
  expect(bars?.getAttribute("aria-label")).toBe(
    "Admin: 0, 0, 1, 2 calls per week, oldest first; this week 2",
  );
  expect(bars?.querySelectorAll("i")).toHaveLength(4);
  expect(bars?.querySelectorAll("i[data-zero]")).toHaveLength(2);
  expect(host.textContent).toContain("Bars: each of the last 4 weeks");
});

it("keeps the share bar when the server lists fewer calls than it counts", async () => {
  activityRoutes([0, 3, 9]);
  const activity = routes["/v1/organisation/activity?days=30"] as {
    calls: unknown[];
  };
  activity.calls = activity.calls.slice(0, 2);
  await render();
  expect(
    host.querySelector('[aria-labelledby="org-people"] [role="img"]'),
  ).toBeNull();
  expect(host.textContent).not.toContain("Bars: each of the last 4 weeks");
});

it("scopes Overview to the member's own calls without team figures", async () => {
  activityRoutes();
  org().role = "member";
  await render();
  expect(host.textContent).toContain("Your calls");
  expect(kpi("People with calls")).toBeUndefined();
  expect(host.querySelector('[aria-labelledby="org-people"]')).toBeNull();
});

it("keeps the Overview's shape while activity loads", async () => {
  activityRoutes();
  const serve = fetchMock.getMockImplementation() as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((path: string, init?: RequestInit) =>
    path === "/v1/organisation/activity?days=30"
      ? new Promise<Response>(() => {})
      : serve(path, init),
  );
  await render();
  const loading = host.querySelector('[aria-label="Loading activity"]')!;
  // Four figure tiles, eight call rows and four people, as when loaded.
  expect(loading.querySelectorAll('[class*="kpi"]')).toHaveLength(4);
  expect(loading.querySelectorAll('[class*="boneRow"]')).toHaveLength(12);
});

it("explains an activity route that this server does not have", async () => {
  await render();
  expect(host.textContent).toContain(
    "Activity is not available on this server yet",
  );
  expect(host.textContent).not.toMatch(/coming soon/i);
});

const RECEIPTS = "/v1/conversation/acquisition/organisation/activity";
const alexId = "024f088d-0a56-4a14-9b20-8030bca6df9a";
const zoeId = "017e41d8-11bc-4e5e-8fb0-9f054b6faded";
function receiptRoutes() {
  activityRoutes();
  const directory = routes["/v1/organisation/members"] as {
    members: Array<Record<string, unknown>>;
  };
  directory.members.push(
    {
      ...active,
      person_id: alexId,
      name: "Alex",
      email: "alex@fictional-studio.in",
      role: "member",
    },
    {
      ...active,
      person_id: zoeId,
      name: "Zoe",
      email: "zoe@fictional-studio.in",
      role: "member",
    },
  );
  routes[RECEIPTS] = receiptFixture();
}
const receiptRows = () =>
  [
    ...host.querySelectorAll(
      '[aria-label="Calls analysed by person"] [role="row"]',
    ),
  ]
    .slice(1)
    .map((row) =>
      [...row.querySelectorAll('[role="cell"]')].map((cell) =>
        cell.textContent?.trim(),
      ),
    );
const analysed = () => host.querySelector('[aria-labelledby="org-analysed"]');

it("shows owners the organisation's calls analysed with each person in API order", async () => {
  receiptRoutes();
  await render();
  expect(analysed()?.querySelector("h2")?.textContent).toBe("Calls analysed6");
  expect(analysed()?.textContent).toContain("+2 on the previous 30 days (4)");
  expect(analysed()?.querySelector("figcaption")?.textContent).toBe(
    "6 calls5 min of calls analysed",
  );
  expect(analysed()?.querySelectorAll('button[aria-label*=": "]')).toHaveLength(
    30,
  );
  // Same-name people are told apart: a current member by email, a former
  // member by that label. Minutes come only from the response's seconds.
  expect(receiptRows()).toEqual([
    ["ALAlexalex@fictional-studio.in", "1", "<1 min", "0"],
    ["ALAlexFormer member", "0", "0 min", "1"],
    ["ZOZoe", "5", "5 min", "2"],
    ["M*m***@example.test", "0", "0 min", "1"],
  ]);
  expect(analysed()?.textContent).toContain("including people who have left");
  // The saved-call figures above keep their own definition.
  expect(kpi("Calls")).toBe("Calls1call saved");
});

it("shows zero analyses and no people for a quiet organisation", async () => {
  receiptRoutes();
  const empty = receiptFixture();
  empty.days = empty.days.map((day) => ({
    ...day,
    analysed: 0,
    analysed_seconds: 0,
  }));
  empty.analysed_last_30_days = 0;
  empty.analysed_previous_30_days = 0;
  empty.people = [];
  routes[RECEIPTS] = empty;
  await render();
  expect(analysed()?.querySelector("h2")?.textContent).toBe("Calls analysed0");
  expect(analysed()?.textContent).toContain(
    "No calls analysed in the last 30 days.",
  );
  expect(analysed()?.textContent).toContain(
    "Nobody in the organisation has a finished analysis in the last 60 days.",
  );
  expect(analysed()?.querySelector("figure")).toBeNull();
});

it("never reads organisation receipts for a member", async () => {
  receiptRoutes();
  org().role = "member";
  await render();
  expect(fetchMock.mock.calls.some(([path]) => path === RECEIPTS)).toBe(false);
  expect(analysed()).toBeNull();
  expect(host.textContent).not.toContain("Calls analysed");
});

it("gives a server without the receipt read one quiet line", async () => {
  activityRoutes();
  await render();
  expect(analysed()).toBeNull();
  expect(host.textContent).toContain(
    "Calls analysed across the organisation show here once this server has the latest update.",
  );
  expect(host.textContent).not.toMatch(/coming soon/i);
});

it("rejects inconsistent receipts and recovers with Try again", async () => {
  receiptRoutes();
  routes[RECEIPTS] = { ...receiptFixture(), analysed_last_30_days: 7 };
  await render();
  expect(analysed()?.textContent).toContain(
    "Calls analysed could not be loaded",
  );
  expect(receiptRows()).toEqual([]);
  routes[RECEIPTS] = receiptFixture();
  await act(async () =>
    analysed()!.querySelector<HTMLButtonElement>("button")!.click(),
  );
  expect(receiptRows()).toHaveLength(4);
});

it("hides receipts and refreshes access when the role is gone", async () => {
  receiptRoutes();
  const serve = fetchMock.getMockImplementation() as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation(async (path: string, init?: RequestInit) =>
    path === RECEIPTS
      ? json(
          { detail: "An active organisation owner or admin is required." },
          403,
        )
      : serve(path, init),
  );
  await render();
  expect(analysed()).toBeNull();
  expect(accessRetry).toHaveBeenCalledTimes(1);
  expect(
    fetchMock.mock.calls.filter(([path]) => path === RECEIPTS),
  ).toHaveLength(1);
});

it("drops the old organisation's late receipts after a workspace switch", async () => {
  receiptRoutes();
  const serve = fetchMock.getMockImplementation() as (
    path: string,
    init?: RequestInit,
  ) => Promise<Response>;
  let resolveOld: ((response: Response) => void) | null = null;
  fetchMock.mockImplementation((path: string, init?: RequestInit) =>
    path === RECEIPTS && resolveOld === null
      ? new Promise<Response>((done) => {
          resolveOld = done;
        })
      : serve(path, init),
  );
  await render();
  const signal = fetchMock.mock.calls.find(([path]) => path === RECEIPTS)![1]
    .signal as AbortSignal;
  const directory = routes["/v1/me/sales-xray-workspaces"] as {
    selected_tenant_id: string;
    workspaces: Array<{ tenant_id: string; name: string }>;
  };
  directory.selected_tenant_id = inviteId;
  directory.workspaces[1].tenant_id = inviteId;
  routes["/v1/organisation"] = {
    ...(routes["/v1/organisation"] as object),
    tenant_id: inviteId,
    name: "Other Fictional Studio",
  };
  const other = receiptFixture();
  other.people = other.people.map((person) => ({
    ...person,
    name: person.name === "Zoe" ? "Other Rep" : person.name,
  }));
  routes[RECEIPTS] = other;
  await render(inviteId);
  expect(signal.aborted).toBe(true);
  await act(async () => resolveOld!(json(receiptFixture())));
  expect(host.querySelector("h1")?.textContent).toBe("Other Fictional Studio");
  expect(analysed()?.textContent).toContain("Other Rep");
  expect(analysed()?.textContent).not.toContain("Zoe");
});

it("keeps the selected section in the address for reloads and links", async () => {
  await render();
  await click("Company");
  expect(window.location.search).toBe("?tab=company");
  await click("Overview");
  expect(window.location.search).toBe("");
});

const settingsCalls = () =>
  fetchMock.mock.calls.filter(([path]) => path === "/v1/organisation/settings");
const detailsForm = () =>
  host.querySelector<HTMLFormElement>('form[aria-label="Company details"]');
async function editCompanyName(name: string) {
  await act(async () => {
    const field =
      detailsForm()!.querySelector<HTMLInputElement>('input[name="name"]')!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, name);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const saveDetails = () =>
  act(async () =>
    detailsForm()!.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ),
  );

it.each(["owner", "admin"])(
  "wires %s details saves, fresh-entry persistence and canonical header refresh while preserving domain rights",
  async (role) => {
    org().role = role;
    await render();
    expect(settingsCalls()).toHaveLength(0);
    await click("Company");
    expect(detailsForm()?.querySelectorAll("input")).toHaveLength(8);
    const domainInput = host.querySelector('input[aria-label="Domain to add"]');
    if (role === "owner") {
      expect(button("Save domains").disabled).toBe(false);
      expect(domainInput).not.toBeNull();
    } else {
      expect(button("Save domains")).toBeUndefined();
      expect(domainInput).toBeNull();
      expect(host.textContent).toContain("Only the owner can change domains.");
    }
    await editCompanyName("  Fictional Renamed Studio  ");
    await saveDetails();
    expect(host.querySelector("h1")?.textContent).toBe(
      "Fictional Renamed Studio",
    );
    expect(detailsForm()?.textContent).toContain("Saved.");
    const body = JSON.parse(String(writes()[0][1].body));
    expect(body.team_size).toBe("3-10");
    expect(body.legal_name).toBe("Fictional Limited");
    expect(body.city).toBe("Example City");
    await click("Overview");
    await click("Company");
    expect(
      detailsForm()?.querySelector<HTMLInputElement>('input[name="name"]')
        ?.value,
    ).toBe("Fictional Renamed Studio");
    expect(settingsCalls().filter(([, init]) => !init?.method)).toHaveLength(2);
  },
);
it("gives members a permission explanation without a private GET, draft, Save or directory-role authority", async () => {
  org().role = "member";
  await render();
  await click("Company");
  expect(host.textContent).toContain("Only owners and admins");
  expect(detailsForm()).toBeNull();
  expect(button("Save details")).toBeUndefined();
  expect(settingsCalls()).toHaveLength(0);
  expect(button("Save domains")).toBeUndefined();
});
it.each([401, 403])(
  "clears the form and refreshes existing access after a %i save without changing the header",
  async (status) => {
    await render();
    await click("Company");
    await editCompanyName("Unsaved Fictional Draft");
    writeStatus = status;
    writeDetail = "Access changed";
    await saveDetails();
    expect(detailsForm()).toBeNull();
    expect(host.textContent).not.toContain("Unsaved Fictional Draft");
    expect(host.querySelector("h1")?.textContent).toBe("Authority Closers");
    expect(accessRetry).toHaveBeenCalledOnce();
    expect(settingsCalls()).toHaveLength(2);
  },
);
it("keeps a rejected save's draft and does not rename the header", async () => {
  await render();
  await click("Company");
  await editCompanyName("Unsaved Fictional Draft");
  writeStatus = 422;
  writeDetail = "Invalid details";
  await saveDetails();
  expect(
    detailsForm()?.querySelector<HTMLInputElement>('input[name="name"]')?.value,
  ).toBe("Unsaved Fictional Draft");
  expect(host.querySelector("h1")?.textContent).toBe("Authority Closers");
  expect(detailsForm()?.textContent).not.toContain("Saved.");
});
it.each(["read", "write"])(
  "uses Personal fallback only for the exact settings %s 404",
  async (operation) => {
    await render();
    if (operation === "read") {
      fetchMock.mockResolvedValueOnce(
        json({ detail: "No organisation selected." }, 404),
      );
      await click("Company");
    } else {
      await click("Company");
      writeStatus = 404;
      writeDetail = "No organisation selected.";
      await saveDetails();
    }
    expect(host.textContent).toContain("You are on your personal account");
    expect(detailsForm()).toBeNull();
  },
);
it("shows an unavailable settings route as a retry error instead of Personal or Coming soon", async () => {
  delete routes["/v1/organisation/settings"];
  await render();
  await click("Company");
  expect(host.textContent).toContain("Company details could not be loaded");
  expect(button("Try again")).toBeDefined();
  expect(host.textContent).not.toContain("You are on your personal account");
  expect(detailsForm()).toBeNull();
});
it.each(["session", "organisation"])(
  "does not load settings for a %s tenant mismatch",
  async (mismatch) => {
    if (mismatch === "organisation")
      routes["/v1/organisation"] = {
        ...(routes["/v1/organisation"] as object),
        tenant_id: inviteId,
      };
    await render(mismatch === "session" ? inviteId : tenantId);
    await click("Company");
    expect(detailsForm()).toBeNull();
    expect(settingsCalls()).toHaveLength(0);
  },
);
it("aborts an old details write on session tenant change so it cannot rename the new header", async () => {
  await render();
  await click("Company");
  await editCompanyName("Old Unsaved Fictional Draft");
  const oldSettings = {
    ...(routes["/v1/organisation/settings"] as object),
    name: "Old Saved Fictional Draft",
  };
  let resolve!: (response: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  await saveDetails();
  const signal = writes()[0][1].signal as AbortSignal;
  const directory = routes["/v1/me/sales-xray-workspaces"] as {
    selected_tenant_id: string;
    workspaces: Array<{ tenant_id: string; name: string }>;
  };
  directory.selected_tenant_id = inviteId;
  directory.workspaces[1].tenant_id = inviteId;
  directory.workspaces[1].name = "Other Fictional Studio";
  routes["/v1/organisation"] = {
    ...(routes["/v1/organisation"] as object),
    tenant_id: inviteId,
    name: "Other Fictional Studio",
  };
  routes["/v1/organisation/settings"] = {
    ...(routes["/v1/organisation/settings"] as object),
    tenant_id: inviteId,
    name: "Other Fictional Studio",
  };
  await render(inviteId);
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(json(oldSettings)));
  expect(host.querySelector("h1")?.textContent).toBe("Other Fictional Studio");
  expect(
    detailsForm()?.querySelector<HTMLInputElement>('input[name="name"]')?.value,
  ).toBe("Other Fictional Studio");
  expect(host.textContent).not.toContain("Saved.");
});
