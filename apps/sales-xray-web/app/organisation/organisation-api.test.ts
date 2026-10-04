import { afterEach, expect, it, vi } from "vitest";
import {
  addMember,
  changeRole,
  removeMember,
  transferOwnership,
  revokeInvite,
  parseOrganisation,
  parseMembers,
  readMembers,
  readOrganisation,
  OrgApiError,
  noOrganisationSelected,
} from "./organisation-api";

const person = "00000000-0000-4000-8000-000000000001";
const invite = "00000000-0000-4000-8000-000000000002";
const organisation = {
  tenant_id: person,
  name: "Example team",
  role: "owner",
  verified_domains: [],
  auto_join: false,
  member_count: 1,
};
const active = {
  person_id: person,
  invite_id: null,
  name: "Alex",
  email: "alex@example.com",
  role: "member",
  status: "active",
  joined_at: "2026-09-01T12:00:00Z",
  last_active_at: null,
  minutes_used_30d: 1.25,
  calls_30d: 0,
};
const invited = {
  ...active,
  person_id: null,
  invite_id: invite,
  status: "invited",
  name: null,
  joined_at: null,
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());

it("strictly parses active and invited identities, nullable fields and zero usage", () => {
  const rows = parseMembers({ members: [active, invited] });
  expect(rows[0]).toMatchObject({
    personId: person,
    inviteId: null,
    calls30d: 0,
    minutesUsed30d: 1.25,
  });
  expect(rows[1]).toMatchObject({
    personId: null,
    inviteId: invite,
    status: "invited",
    name: null,
  });
  expect(
    parseMembers({ members: [{ ...active, email: null }] })[0].email,
  ).toBeNull();
  expect(parseMembers({ members: [] })).toEqual([]);
  expect(parseOrganisation(organisation)).toMatchObject({
    name: "Example team",
    memberCount: 1,
    role: "owner",
  });
});

it.each([
  { person_id: null },
  { invite_id: invite },
  { person_id: "" },
  { role: "superadmin" },
  { status: "removed" },
  { extra: true },
  { email: 7 },
  { name: undefined },
  { joined_at: "yesterday" },
  { last_active_at: 42 },
  { minutes_used_30d: -1 },
  { minutes_used_30d: "2" },
  { calls_30d: 1.5 },
  { calls_30d: Infinity },
])("rejects malformed active rows: %j", (change) => {
  expect(() => parseMembers({ members: [{ ...active, ...change }] })).toThrow();
});
it.each([
  { person_id: person },
  { invite_id: null },
  { invite_id: "" },
  { role: "owner" },
])("rejects malformed invited rows: %j", (change) => {
  expect(() =>
    parseMembers({ members: [{ ...invited, ...change }] }),
  ).toThrow();
});
it.each([
  null,
  [],
  {},
  { members: null },
  { members: [active], extra: true },
  { members: [active, active] },
])("rejects invalid or duplicate member collections: %j", (data) => {
  expect(() => parseMembers(data)).toThrow();
});
it.each([
  { role: "unknown" },
  { member_count: "1" },
  { member_count: -1 },
  { member_count: 1.5 },
  { auto_join: 1 },
  { verified_domains: [4] },
  { extra: true },
])("rejects invalid organisation fields: %j", (change) => {
  expect(() => parseOrganisation({ ...organisation, ...change })).toThrow();
});
it("uses the strict parsers for real reads", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(json(organisation))
    .mockResolvedValueOnce(json({ members: [active, invited] }));
  vi.stubGlobal("fetch", fetchMock);
  expect((await readOrganisation()).name).toBe("Example team");
  expect(await readMembers()).toHaveLength(2);
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    "/v1/organisation",
    "/v1/organisation/members",
  ]);
  expect(fetchMock.mock.calls[0][1]).toMatchObject({
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
  });
});

const actions = [
  [
    "add",
    () => addMember("new@example.com", "member"),
    "/members",
    "POST",
    { email: "new@example.com", role: "member" },
  ],
  [
    "role",
    () => changeRole(person, "admin"),
    `/members/${person}`,
    "PATCH",
    { role: "admin" },
  ],
  [
    "remove",
    () => removeMember(person),
    `/members/${person}`,
    "DELETE",
    undefined,
  ],
  [
    "transfer",
    () => transferOwnership(person),
    "/owner",
    "POST",
    { person_id: person },
  ],
  [
    "revoke",
    () => revokeInvite(invite),
    `/invites/${invite}`,
    "DELETE",
    undefined,
  ],
] as const;
it("sends every write with its contract body and a distinct UUIDv4", async () => {
  const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  for (const [, action] of actions) await action();
  const keys = new Set<string>();
  actions.forEach(([, , path, method, body], index) => {
    const [url, init] = fetchMock.mock.calls[index] as unknown as [
      string,
      RequestInit,
    ];
    expect(url).toBe(`/v1/organisation${path}`);
    expect(init.method).toBe(method);
    expect(init.body ? JSON.parse(String(init.body)) : undefined).toEqual(body);
    const key = new Headers(init.headers).get("Idempotency-Key")!;
    expect(key).toMatch(
      /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/,
    );
    keys.add(key);
  });
  expect(keys.size).toBe(actions.length);
});
it.each(actions)(
  "preserves 403, 404 and 409 messages for %s",
  async (_, action) => {
    for (const [status, detail] of [
      [403, "Owner permission is required."],
      [404, "No organisation selected."],
      [409, "Transfer ownership first."],
    ] as const) {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => json({ detail }, status)),
      );
      await expect(action()).rejects.toMatchObject({ status, message: detail });
    }
  },
);
it("only treats the exact Personal response as no organisation", () => {
  expect(
    noOrganisationSelected(new OrgApiError(404, "No organisation selected.")),
  ).toBe(true);
  expect(
    noOrganisationSelected(new OrgApiError(404, "Member not found.")),
  ).toBe(false);
  expect(
    noOrganisationSelected(new OrgApiError(403, "No organisation selected.")),
  ).toBe(false);
});
