// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as platform from "@ac/operations-web/platform-identity";
import { OrganisationsConsole } from "./organisations-console";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
const tenant = "11111111-1111-4111-8111-111111111111";
const person = "22222222-2222-4222-8222-222222222222";
const ownerId = "33333333-3333-4333-8333-333333333333";
const inviteId = "44444444-4444-4444-8444-444444444444";
const identity: platform.PlatformIdentity = {
  personId: ownerId,
  sessionId: tenant,
  selectedTenantId: null,
  email: "operator@example.test",
  displayName: "Fictional Operator",
  permissions: ["platform_tenants_read", "platform_organisations_manage"],
};
const directory = {
  organisations: [
    {
      tenant_id: tenant,
      name: "Example Sales Team",
      member_count: 2,
      created_at: "2026-10-01T00:00:00Z",
    },
  ],
};
const member = {
  person_id: person,
  invite_id: null,
  name: "Avery Example",
  email: "avery@example.test",
  role: "member",
  status: "active",
  joined_at: "2026-10-01T00:00:00Z",
  last_active_at: "2026-10-02T00:00:00Z",
  minutes_used_30d: 12.5,
  calls_30d: 3,
};
const owner = {
  ...member,
  person_id: ownerId,
  name: "Robin Example",
  email: "robin@example.test",
  role: "owner",
};
const invite = {
  ...member,
  person_id: null,
  invite_id: inviteId,
  name: null,
  email: "invited@example.test",
  status: "invited",
  joined_at: null,
  last_active_at: null,
  minutes_used_30d: 0,
  calls_30d: 0,
};
const members = { members: [owner, member, invite] };
const base = `/v1/platform/organisations/${tenant}`;
let container: HTMLDivElement, root: Root, disposed: boolean;
let mutate = vi.fn<typeof fetch>();
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  disposed = false;
  vi.spyOn(platform, "loadPlatformIdentity").mockResolvedValue(identity);
  mutate = vi.fn().mockResolvedValue(Response.json(member));
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
      if (init?.method === "GET")
        return Response.json(
          path === "/v1/platform/organisations" ? directory : members,
        );
      return mutate(path, init);
    }),
  );
});
afterEach(async () => {
  if (!disposed) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function mount() {
  await act(async () => root.render(<OrganisationsConsole />));
}
function button(text: string) {
  const found = [...container.querySelectorAll("button")].find(
    (element) => element.textContent?.trim() === text,
  );
  if (!found) throw new Error(`Missing button ${text}`);
  return found;
}
async function openMembers() {
  await mount();
  await act(async () => button("Example Sales Team").click());
}
async function fill(
  element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  value: string,
) {
  await act(async () => {
    const prototype =
      element instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : element instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLSelectElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
      element,
      value,
    );
    element.dispatchEvent(
      new Event(element instanceof HTMLSelectElement ? "change" : "input", {
        bubbles: true,
      }),
    );
  });
}
async function reason(value = "Fictional staff request") {
  await fill(container.querySelector("textarea")!, value);
}

it("renders server rows, usage and only the applicable actions", async () => {
  await openMembers();
  for (const text of [
    "Avery Example",
    "avery@example.test",
    "owner",
    "active",
    "invited",
    "12.5",
    "3",
    "Last active",
    "30 days",
  ])
    expect(container.textContent).toContain(text);
  expect(container.querySelectorAll("tbody tr")).toHaveLength(4);
  const ownerRow = [...container.querySelectorAll("tbody tr")].find((row) =>
    row.textContent?.includes("Robin Example"),
  )!;
  expect(ownerRow.querySelector("button")).toBeNull();
  expect(button("Revoke invite")).toBeDefined();
});
it("permits reads but hides all writes without the manage capability", async () => {
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue({
    ...identity,
    permissions: ["platform_tenants_read"],
  });
  await openMembers();
  expect(
    container.querySelector('a[href="/platform/organisations"]'),
  ).not.toBeNull();
  for (const text of [
    "Add by email",
    "Change role",
    "Remove member",
    "Transfer ownership",
    "Revoke invite",
  ])
    expect(container.textContent).not.toContain(text);
});
it.each([
  null,
  {
    ...identity,
    permissions: ["platform_organisations_manage"],
  } as platform.PlatformIdentity,
])(
  "does not request organisation data without read admission",
  async (subject) => {
    vi.mocked(platform.loadPlatformIdentity).mockResolvedValue(subject);
    await mount();
    expect(fetch).not.toHaveBeenCalled();
    expect(
      container.querySelector('a[href="/platform/organisations"]'),
    ).toBeNull();
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  },
);
it("shows empty directory and member states", async () => {
  vi.mocked(fetch).mockResolvedValueOnce(Response.json({ organisations: [] }));
  await mount();
  expect(container.textContent).toContain("No organisations are available.");
  vi.mocked(fetch).mockImplementation(async (path) =>
    Response.json(
      path === "/v1/platform/organisations" ? directory : { members: [] },
    ),
  );
  await act(async () => button("Refresh").click());
  await act(async () => button("Example Sales Team").click());
  expect(container.textContent).toContain(
    "No members or invitations are available.",
  );
});
it.each([403, 404, 409])(
  "shows the exact directory error for HTTP %i",
  async (status) => {
    const detail = `Fictional directory rejection ${status}.`;
    vi.mocked(fetch).mockResolvedValue(Response.json({ detail }, { status }));
    await mount();
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(detail);
    expect(container.querySelector("table")).toBeNull();
  },
);
it("rejects unknown member roles without displaying the rows", async () => {
  vi.mocked(fetch).mockImplementation(async (path) =>
    Response.json(
      path === "/v1/platform/organisations"
        ? directory
        : { members: [{ ...member, role: "support" }] },
    ),
  );
  await openMembers();
  expect(container.textContent).not.toContain(member.name);
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
});

it.each([
  ["Add by email", "/members", "POST"],
  ["Change role", `/members/${person}`, "PATCH"],
  ["Remove member", `/members/${person}`, "DELETE"],
  ["Transfer ownership", "/owner", "POST"],
  ["Revoke invite", `/invites/${inviteId}`, "DELETE"],
])(
  "confirms %s with reason and refreshes both directories after success",
  async (label, path, method) => {
    if (method === "DELETE")
      mutate.mockResolvedValue(new Response(null, { status: 204 }));
    else if (path === "/owner")
      mutate.mockResolvedValue(
        Response.json({
          owner: { ...member, role: "owner" },
          former_owner: { ...owner, role: "admin" },
        }),
      );
    await openMembers();
    await act(async () => button(label).click());
    const confirm = button(`Confirm ${label.toLowerCase()}`);
    expect(confirm.disabled).toBe(true);
    await reason("   ");
    expect(confirm.disabled).toBe(true);
    if (label === "Add by email")
      await fill(
        container.querySelector('input[type="email"]')!,
        "new@example.test",
      );
    await reason(" Fictional staff request ");
    await act(async () => confirm.click());
    expect(mutate).toHaveBeenCalledOnce();
    const [url, init] = mutate.mock.calls[0];
    expect(url).toBe(base + path);
    expect(init!.method).toBe(method);
    expect(JSON.parse(init!.body as string).reason).toBe(
      "Fictional staff request",
    );
    expect(new Headers(init!.headers).get("Idempotency-Key")).toMatch(
      /^[a-f0-9-]{36}$/,
    );
    expect(container.textContent).toContain("Change saved.");
    expect(container.querySelector("form")).toBeNull();
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => url === base + "/members"),
    ).toHaveLength(label === "Add by email" ? 3 : 2);
  },
);
it.each([403, 404, 409])(
  "retains the reason and exact mutation message on HTTP %i",
  async (status) => {
    const detail = `Fictional member rejection ${status}.`;
    mutate.mockImplementation(async () =>
      Response.json({ detail }, { status }),
    );
    await openMembers();
    await act(async () => button("Remove member").click());
    await reason();
    await act(async () => button("Confirm remove member").click());
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(detail);
    expect(container.querySelector("textarea")?.value).toBe(
      "Fictional staff request",
    );
    await act(async () => button("Confirm remove member").click());
    const keys = mutate.mock.calls.map(([, init]) =>
      new Headers(init!.headers).get("Idempotency-Key"),
    );
    expect(new Set(keys).size).toBe(2);
  },
);
it("cancels an action without writing", async () => {
  await openMembers();
  await act(async () => button("Remove member").click());
  await reason();
  await act(async () => button("Cancel").click());
  expect(mutate).not.toHaveBeenCalled();
  expect(container.querySelector("form")).toBeNull();
});
it.each([
  {
    ...identity,
    permissions: ["platform_tenants_read"],
  } as platform.PlatformIdentity,
  { ...identity, sessionId: person },
  null,
])("revalidates identity and grants before dispatch", async (subject) => {
  await openMembers();
  await act(async () => button("Remove member").click());
  await reason();
  vi.mocked(platform.loadPlatformIdentity).mockResolvedValue(subject);
  await act(async () => button("Confirm remove member").click());
  expect(mutate).not.toHaveBeenCalled();
  expect(container.querySelector("form")).toBeNull();
  expect(container.textContent).toContain("Access changed.");
});
it("guards duplicate submit and aborts a pending write on unmount", async () => {
  let writeSignal: AbortSignal | undefined;
  mutate.mockImplementation((_url, init) => {
    writeSignal = init?.signal ?? undefined;
    return new Promise(() => {});
  });
  await openMembers();
  await act(async () => button("Remove member").click());
  await reason();
  const form = container.querySelector("form")!;
  await act(async () => {
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    form.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
  expect(mutate).toHaveBeenCalledOnce();
  expect(button("Refresh").disabled).toBe(true);
  expect(container.querySelector("fieldset")?.disabled).toBe(true);
  await act(async () => root.unmount());
  disposed = true;
  expect(writeSignal?.aborted).toBe(true);
});
