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
let accessRetry: ReturnType<typeof vi.fn<() => void>>;
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
beforeEach(() => {
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

it.each([0, 2_700])(
  "shows Unlimited organisation usage with %i available seconds",
  async (available) => {
    routes["/v1/conversation/acquisition/session"] = {
      allowance: {
        allowance_seconds: 3_600,
        committed_seconds: 1_200,
        available_seconds: available,
        unlimited: true,
      },
    };
    await render();
    await click("Usage & credits");
    const stat = [...host.querySelectorAll("span")].find(
      (node) => node.textContent === "Your minutes",
    )!.parentElement!;
    expect(stat.textContent).toContain("Unlimited");
    expect(stat.textContent).toContain("20 min used or reserved");
    expect(stat.textContent).not.toContain("left");
    expect(stat.querySelector("i")).toBeNull();
  },
);

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
    expect(button("Save").disabled).toBe(role !== "owner");
    expect(
      host.querySelector<HTMLInputElement>('input[aria-label="Domain to add"]')
        ?.disabled,
    ).toBe(role !== "owner");
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
  expect(button("Save").disabled).toBe(true);
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
