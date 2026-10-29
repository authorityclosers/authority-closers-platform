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
      plan_name: null,
      paid_seats: 0,
      complimentary_seats: 4,
      pending_invites: 1,
      minutes_30d: 12.5,
      calls_30d: 3,
    },
  ],
};
const grantId = "55555555-5555-4555-8555-555555555555";
const seatView = (grants: unknown[] = [], can_grant = false) => ({
  seats: {
    paid_seats: 0,
    complimentary_seats: grants.length ? 4 : 0,
    total_seats: grants.length ? 4 : 0,
    active_members: 2,
    pending_invites: 1,
    seats_available: grants.length ? 1 : 0,
  },
  plan: null,
  grants,
  can_grant,
  earliest_until: "2026-10-30",
  latest_until: "2029-11-03",
});
const liveGrant = {
  id: grantId,
  kind: "grant",
  seats: 4,
  until: "2027-01-31",
  supersedes_grant_id: null,
  reason: "Fictional founding client",
  granted_by: "owner@example.test",
  created_at: "2026-10-30T01:30:00+00:00",
  live: true,
};
let seats = seatView();
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
  seats = seatView();
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
      if (init?.method === "GET")
        return Response.json(
          path === "/v1/platform/organisations"
            ? directory
            : String(path).endsWith("/seats")
              ? seats
              : members,
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
/** The small "unavailable" card a failed read shows (never an alert banner). */
function unavailable() {
  return container.querySelector('section[role="status"]')?.textContent ?? "";
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
    expect(unavailable()).toContain("is unavailable");
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
    expect(unavailable()).toContain(detail);
    expect(container.querySelector('[role="alert"]')).toBeNull();
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
  expect(unavailable()).toContain("is unavailable");
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

it("opens a member's days from their name; an invitation has none", async () => {
  await openMembers();
  const links = [
    ...container.querySelectorAll<HTMLAnchorElement>('a[href^="/sellers/"]'),
  ].map((link) => [link.getAttribute("href"), link.textContent]);
  expect(links).toEqual([
    [`/sellers/${ownerId}`, "Robin Example"],
    [`/sellers/${person}`, "Avery Example"],
  ]);
});

it("lists each organisation's plan, seats taken, free seats and use", async () => {
  await mount();
  const row = container.querySelector("tbody tr")!;
  const cells = [...row.querySelectorAll("td")].map((cell) => cell.textContent);
  expect(cells).toEqual([
    "Example Sales Team",
    "No paid plan",
    "3 of 4",
    "4",
    "2",
    "3",
    "12.5",
    expect.stringContaining("2026"),
  ]);
});

it("shows seats to every reader but only the owner may give them", async () => {
  seats = seatView([liveGrant], false);
  await openMembers();
  expect(container.textContent).toContain("Owner gives free seats");
  expect(container.textContent).toContain("Fictional founding client");
  expect(container.textContent).toContain("31 Jan 2027");
  expect(container.textContent).toContain(
    "Only the owner gives, changes or ends free seats.",
  );
  expect(
    [...container.querySelectorAll("button")].some((item) =>
      ["Give free seats", "Change", "End"].includes(
        item.textContent?.trim() ?? "",
      ),
    ),
  ).toBe(false);
});

it("the owner reviews seats before and after, then gives them with one key", async () => {
  seats = seatView([], true);
  const saved = seatView([liveGrant], true);
  mutate.mockImplementation(async () => Response.json(saved));
  await openMembers();
  await act(async () => button("Give free seats").click());
  const input = (label: string) =>
    container.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
  await fill(input("Free seats"), "4");
  await fill(input("Last day they count"), "2027-01-31");
  expect(button("Review").disabled).toBe(true);
  await fill(input("Reason for the free seats"), "Fictional founding client");
  await act(async () => button("Review").click());
  const confirm = container.querySelector(
    '[aria-label="Confirm the free seats"]',
  )!;
  expect(confirm.textContent).toContain("Seats now: 0 seats (0 paid, 0 free)");
  expect(confirm.textContent).toContain(
    "Seats after: 4 seats (0 paid, 4 free)",
  );
  // Two members and an invite against four seats: nobody waits.
  expect(confirm.textContent).not.toContain("No one is removed");
  expect(mutate).not.toHaveBeenCalled();
  await act(async () => button("Give 4 seats until 31 Jan 2027").click());
  expect(mutate).toHaveBeenCalledOnce();
  const [url, init] = mutate.mock.calls[0];
  expect(url).toBe(base + "/seat-grants");
  expect(init!.method).toBe("POST");
  expect(JSON.parse(init!.body as string)).toEqual({
    seats: 4,
    until: "2027-01-31",
    reason: "Fictional founding client",
  });
  expect(new Headers(init!.headers).get("Idempotency-Key")).toMatch(
    /^[a-f0-9-]{36}$/,
  );
  expect(container.textContent).toContain("Seats saved.");
});

it("the owner ends a live grant without a date and is warned nobody is removed", async () => {
  seats = {
    ...seatView([liveGrant], true),
  };
  mutate.mockImplementation(async () => Response.json(seatView([], true)));
  await openMembers();
  await act(async () => button("End").click());
  await fill(
    container.querySelector<HTMLInputElement>(
      'input[aria-label="Reason for the free seats"]',
    )!,
    "Fictional move to paid",
  );
  await act(async () => button("Review").click());
  expect(container.textContent).toContain("No one is removed");
  await act(async () => button("End 4 seats").click());
  expect(JSON.parse(mutate.mock.calls[0][1]!.body as string)).toEqual({
    seats: 0,
    reason: "Fictional move to paid",
    supersedes_grant_id: grantId,
  });
});

it("keeps the owner's entry and shows the server's refusal", async () => {
  seats = seatView([], true);
  mutate.mockImplementation(async () =>
    Response.json(
      { detail: "Only the owner (Suyash) can give complimentary seats." },
      { status: 403 },
    ),
  );
  await openMembers();
  await act(async () => button("Give free seats").click());
  await fill(
    container.querySelector<HTMLInputElement>(
      'input[aria-label="Reason for the free seats"]',
    )!,
    "Fictional founding client",
  );
  await act(async () => button("Review").click());
  await act(async () =>
    [...container.querySelectorAll("button")]
      .find((item) => item.textContent?.startsWith("Give 4 seats"))!
      .click(),
  );
  expect(container.querySelector('[role="alert"]')?.textContent).toBe(
    "Only the owner (Suyash) can give complimentary seats.",
  );
});
