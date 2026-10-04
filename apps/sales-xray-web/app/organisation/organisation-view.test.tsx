// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { WorkspaceAccessContext } from "../workspace-access";
import { OrganisationView } from "./organisation-view";

vi.mock("../acquisition-shell", () => ({
  AcquisitionShell: ({ children }: { children: ReactNode }) => (
    <main>{children}</main>
  ),
}));
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
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  writeStatus = 204;
  writeDetail = "";
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
async function render() {
  await act(async () =>
    root.render(
      <WorkspaceAccessContext.Provider
        value={{
          status: "ready",
          authenticated: true,
          context: { personId: ownerId, sessionId: "s-1", tenantId },
          retry: () => {},
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
  expect(host.textContent).toContain("Joined");
  expect(host.textContent).toContain("Last active");
  expect(host.textContent).toContain("Admin (you)");
  expect(button("Revoke invite for new")).toBeDefined();
  expect(host.querySelector('select[aria-label="Role for new"]')).toBeNull();
  const cells = [...host.querySelectorAll('[role="row"]')][2].querySelectorAll(
    '[role="cell"]',
  );
  expect(cells[2].textContent).toBe("0");
  expect(cells[3].textContent).toBe("0");
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
    () => click("Revoke invite for new"),
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
    await click("Confirm");
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
  await click("Confirm");
  expect(host.querySelector("header")?.textContent).toContain("you are Admin");
  expect(button("Make Dipak the owner")).toBeUndefined();
  expect(host.querySelector('select[aria-label="Role for Dipak"]')).toBeNull();
  await add();
  await click("Confirm");
  expect(JSON.parse(String(writes()[1][1].body)).role).toBe("member");
});
it("allows admins to add and remove members and revoke member invites only", async () => {
  org().role = "admin";
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
  expect(button("Revoke invite for new").disabled).toBe(false);
});
it("uses the API role and shows members only their own row read-only", async () => {
  org().role = "member";
  await render();
  await click("Members");
  expect(host.querySelector("header")?.textContent).toContain("you are Member");
  expect(host.querySelectorAll('[role="row"]')).toHaveLength(2);
  expect(host.textContent).not.toContain("dipak@example.com");
  expect(host.textContent).not.toContain("new@example.com");
  expect(
    host.querySelector<HTMLInputElement>('input[aria-label="Email to add"]')
      ?.disabled,
  ).toBe(true);
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
  await click("Confirm");
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(detail);
});
it("hides Organisation after a Personal 404 on a write", async () => {
  writeStatus = 404;
  writeDetail = "No organisation selected.";
  await render();
  await click("Members");
  await click("Remove Dipak");
  await click("Confirm");
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
it("keeps personal Create/Join flows Coming soon and makes no organisation reads", async () => {
  (
    routes["/v1/me/sales-xray-workspaces"] as { selected_tenant_id: string }
  ).selected_tenant_id = "personal";
  await render();
  expect(host.textContent).toContain("You are on your personal account");
  expect(button("Create an organisationSoon").disabled).toBe(true);
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
