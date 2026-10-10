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
  organisationDetailFields,
  parseOrganisationSettings,
  readOrganisationSettings,
  saveOrganisationSettings,
  parseReceiptActivity,
  readReceiptActivity,
  ReceiptActivityError,
} from "./organisation-api";
import { receiptFixture } from "./receipt-activity.fixture";

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

const settings = {
  tenant_id: person,
  name: "Fictional Studio",
  legal_name: "Fictional Limited",
  gstin: "FICTIONAL",
  address: "123 Example Street",
  industry: "Training",
  team_size: "3-10",
  website: "https://example.test",
  city: "Example City",
  logo_url: null,
};
const details = Object.fromEntries(
  organisationDetailFields.map((field) => [field, settings[field]]),
);
const key = "11111111-1111-4111-8111-111111111111";

it("parses the exact settings contract and editable empty optional strings", () => {
  expect(parseOrganisationSettings(settings, person)).toEqual(settings);
  const empty = {
    ...settings,
    ...Object.fromEntries(
      organisationDetailFields.slice(1).map((field) => [field, ""]),
    ),
  };
  expect(parseOrganisationSettings(empty, person)).toEqual(empty);
  expect(
    parseOrganisationSettings(
      { ...settings, logo_url: "/v1/organisation/logo/fictional" },
      person,
    ).logo_url,
  ).toBe("/v1/organisation/logo/fictional");
});

it.each(organisationDetailFields)(
  "rejects missing and non-string %s",
  (field) => {
    const missing = { ...settings } as Record<string, unknown>;
    delete missing[field];
    expect(() => parseOrganisationSettings(missing, person)).toThrow();
    expect(() =>
      parseOrganisationSettings({ ...settings, [field]: 3 }, person),
    ).toThrow();
  },
);
it.each([
  null,
  [],
  {},
  { ...settings, extra: true },
  { ...settings, tenant_id: invite },
  { ...settings, tenant_id: "bad" },
  { ...settings, logo_url: 1 },
  { ...settings, logo_url: undefined },
])("rejects invalid settings or a different tenant: %j", (payload) => {
  expect(() => parseOrganisationSettings(payload, person)).toThrow(
    "Invalid organisation settings response.",
  );
});

it("reads with a signal and saves exactly eight fields using the caller's retry key", async () => {
  const fetchMock = vi.fn(async () => json(settings));
  vi.stubGlobal("fetch", fetchMock);
  const controller = new AbortController();
  expect(await readOrganisationSettings(person, controller.signal)).toEqual(
    settings,
  );
  await saveOrganisationSettings(person, settings, key, controller.signal);
  await saveOrganisationSettings(person, settings, key, controller.signal);
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
  for (const [path, init] of calls) {
    expect(path).toBe("/v1/organisation/settings");
    expect(init).toMatchObject({
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    expect(new Headers(init.headers).get("Accept")).toBe("application/json");
  }
  expect(new Headers(calls[0][1].headers).has("Idempotency-Key")).toBe(false);
  for (const [, init] of calls.slice(1)) {
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual(details);
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json",
    );
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe(key);
  }
});

it.each([
  "",
  key.toUpperCase().replace("11111111", "ABCDEFAB"),
  key.replace("4111", "5111"),
  key.replace("8111", "7111"),
])(
  "rejects a non-canonical UUIDv4 key before calling the server",
  async (badKey) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      saveOrganisationSettings(person, settings, badKey),
    ).rejects.toThrow("UUIDv4");
    expect(fetchMock).not.toHaveBeenCalled();
  },
);
it.each([401, 403, 404, 409, 422, 500])(
  "preserves settings HTTP %i for reads and writes",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Fictional error" }, status)),
    );
    for (const action of [
      () => readOrganisationSettings(person),
      () => saveOrganisationSettings(person, settings, key),
    ])
      await expect(action()).rejects.toMatchObject({
        status,
        message: "Fictional error",
      });
  },
);
it("preserves network errors for the settings consumer", async () => {
  const error = new TypeError("Network unavailable");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
  await expect(readOrganisationSettings(person)).rejects.toBe(error);
  await expect(saveOrganisationSettings(person, settings, key)).rejects.toBe(
    error,
  );
});

it("reads the complete fictional receipt response from the acquisition route", async () => {
  const fetchMock = vi.fn(async () => json(receiptFixture()));
  vi.stubGlobal("fetch", fetchMock);
  const value = await readReceiptActivity();
  expect(fetchMock).toHaveBeenCalledWith(
    "/v1/conversation/acquisition/organisation/activity",
    expect.objectContaining({ credentials: "same-origin", cache: "no-store" }),
  );
  expect(value?.days).toHaveLength(30);
  expect(value?.days.at(-1)).toEqual({
    date: "2026-09-29",
    analysed: 3,
    analysedSeconds: 65,
  });
  expect(value?.analysedLast30Days).toBe(6);
  expect(value?.analysedPrevious30Days).toBe(4);
  // The API's order is kept, including two people who share a name.
  expect(value?.people.map((item) => [item.name, item.analysed])).toEqual([
    ["Alex", 1],
    ["Alex", 0],
    ["Zoe", 5],
    ["m***@example.test", 0],
  ]);
  expect(value?.people[2]).toMatchObject({
    analysedSeconds: 305,
    previous: 2,
  });
});

it("reads an organisation with no analyses as zeros, not an error", () => {
  const empty = receiptFixture();
  empty.days = empty.days.map((day) => ({
    ...day,
    analysed: 0,
    analysed_seconds: 0,
  }));
  empty.analysed_last_30_days = 0;
  empty.analysed_previous_30_days = 0;
  empty.people = [];
  expect(parseReceiptActivity(empty)).toMatchObject({
    analysedLast30Days: 0,
    analysedPrevious30Days: 0,
    people: [],
  });
});

it("returns null when this server does not serve the receipt read", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({ detail: "Not Found" }, 404)),
  );
  await expect(readReceiptActivity()).resolves.toBeNull();
});

it.each([401, 403, 500])(
  "keeps receipt HTTP %i for the access and retry states",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json({ detail: "Fictional" }, status)),
    );
    await expect(readReceiptActivity()).rejects.toMatchObject({ status });
  },
);

type Fixture = ReturnType<typeof receiptFixture>;
it.each<[string, (data: Fixture) => unknown]>([
  ["an extra field", (data) => ({ ...data, scores: [] })],
  [
    "a missing field",
    (data) =>
      Object.fromEntries(
        Object.entries(data).filter(([key]) => key !== "people"),
      ),
  ],
  ["another timezone", (data) => ({ ...data, timezone: "UTC" })],
  ["29 days", (data) => ({ ...data, days: data.days.slice(1) })],
  [
    "days out of order",
    (data) => ({ ...data, days: [...data.days].reverse() }),
  ],
  [
    "an extra day field",
    (data) => ({
      ...data,
      days: data.days.map((day, index) => (index ? day : { ...day, score: 1 })),
    }),
  ],
  [
    "a negative count",
    (data) => ({
      ...data,
      people: data.people.map((person, index) =>
        index ? person : { ...person, analysed_previous_30_days: -1 },
      ),
    }),
  ],
  [
    "a person id that is not a UUID",
    (data) => ({
      ...data,
      people: data.people.map((person, index) =>
        index ? person : { ...person, person_id: "alex" },
      ),
    }),
  ],
  [
    "the same person twice",
    (data) => ({ ...data, people: [...data.people, data.people[0]] }),
  ],
  [
    "a total that disagrees with its days",
    (data) => ({ ...data, analysed_last_30_days: 7 }),
  ],
  [
    "people seconds that disagree with the days",
    (data) => ({
      ...data,
      people: data.people.map((person, index) =>
        index ? person : { ...person, analysed_seconds_last_30_days: 16 },
      ),
    }),
  ],
  [
    "a previous total that disagrees with its people",
    (data) => ({ ...data, analysed_previous_30_days: 5 }),
  ],
])("rejects a receipt response with %s", (_name, change) => {
  expect(() => parseReceiptActivity(change(receiptFixture()))).toThrow(
    ReceiptActivityError,
  );
});
