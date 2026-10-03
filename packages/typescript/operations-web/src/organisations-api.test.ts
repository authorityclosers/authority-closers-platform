import { expect, it, vi } from "vitest";
import { z } from "zod";
import { AdminApiProblem } from "./admin-api";
import {
  loadPlatformOrganisations,
  platformOrganisationsSchema,
  organisationMemberSchema,
  organisationMembersSchema,
  organisationOwnerTransferSchema,
  loadOrganisationMembers,
  changePlatformOrganisation,
  type OrganisationCommand,
} from "./organisations-api";

const organisation = {
  tenant_id: "11111111-1111-4111-8111-111111111111",
  name: "Fictional Example Organisation",
  member_count: 0,
  created_at: "2026-10-02T00:00:00Z",
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });

it.each([{ organisations: [organisation] }, { organisations: [] }])(
  "loads a valid directory: %j",
  async (payload) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(payload));
    const signal = new AbortController().signal;
    await expect(
      loadPlatformOrganisations({ fetcher, signal }),
    ).resolves.toEqual(payload);
    expect(platformOrganisationsSchema.parse(payload)).toEqual(payload);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith(
      "/v1/platform/organisations",
      {
        method: "GET",
        headers: { accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        signal,
      },
    );
  },
);

it.each([
  null,
  {},
  { organisations: [], extra: true },
  { organisations: [{ ...organisation, extra: true }] },
  ...[
    { tenant_id: "invalid" },
    { member_count: -1 },
    { member_count: 1.5 },
    { member_count: "1" },
    { name: "" },
    { created_at: "" },
  ].map((invalid) => ({ organisations: [{ ...organisation, ...invalid }] })),
])("rejects malformed directory payloads: %j", async (payload) => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(payload));
  await expect(loadPlatformOrganisations({ fetcher })).rejects.toBeInstanceOf(
    z.ZodError,
  );
});

it.each([
  [401, "Fictional session expired."],
  [403, "Organisation access denied."],
  [404, "Fictional organisation directory not found."],
  [409, "Organisation changed. Reload and try again."],
] as const)("preserves the server problem for %i", async (status, detail) => {
  const problem = {
    code: "fictional_problem",
    title: "Rejected",
    detail,
    request_id: "fictional-request",
  };
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(json(problem, status));
  const error = await loadPlatformOrganisations({ fetcher }).catch((e) => e);
  expect(error).toBeInstanceOf(AdminApiProblem);
  expect(error).toMatchObject({
    status,
    code: problem.code,
    title: problem.title,
    message: detail,
    requestId: problem.request_id,
  });
});

it("propagates transport failures and rejects invalid success JSON", async () => {
  const failure = new TypeError("Fictional network failure");
  const fetcher = vi.fn<typeof fetch>().mockRejectedValue(failure);
  await expect(loadPlatformOrganisations({ fetcher })).rejects.toBe(failure);
  fetcher.mockResolvedValue(new Response("invalid JSON"));
  await expect(loadPlatformOrganisations({ fetcher })).rejects.toBeInstanceOf(
    z.ZodError,
  );
});

const member = {
  person_id: "22222222-2222-4222-8222-222222222222",
  invite_id: null,
  name: "Avery Example",
  email: "avery@example.test",
  role: "member",
  status: "active",
  joined_at: "2026-10-01T00:00:00Z",
  last_active_at: null,
  minutes_used_30d: 3.5,
  calls_30d: 1,
};
const invite = {
  ...member,
  person_id: null,
  invite_id: organisation.tenant_id,
  name: null,
  role: "admin",
  status: "invited",
  joined_at: null,
};

it("reads active and invited member rows with nullable fields", async () => {
  const payload = { members: [member, invite] };
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(json(payload));
  const signal = new AbortController().signal;
  await expect(
    loadOrganisationMembers(organisation.tenant_id, { fetcher, signal }),
  ).resolves.toEqual(payload);
  expect(fetcher).toHaveBeenCalledWith(
    `/v1/platform/organisations/${organisation.tenant_id}/members`,
    expect.objectContaining({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal,
    }),
  );
});

it.each([
  { ...member, extra: true },
  { ...member, role: "support" },
  { ...member, status: "pending" },
  { ...member, person_id: "not-a-uuid" },
  { ...member, joined_at: "yesterday" },
  { ...member, minutes_used_30d: -1 },
  { ...member, calls_30d: 0.5 },
])("rejects invalid or extended member rows: %j", (payload) => {
  expect(() => organisationMemberSchema.parse(payload)).toThrow(z.ZodError);
});
it("rejects extra fields in member and transfer envelopes", () => {
  expect(() =>
    organisationMembersSchema.parse({ members: [member], extra: true }),
  ).toThrow(z.ZodError);
  expect(() =>
    organisationOwnerTransferSchema.parse({
      owner: member,
      former_owner: member,
      extra: true,
    }),
  ).toThrow(z.ZodError);
  expect(() =>
    organisationOwnerTransferSchema.parse({
      owner: { ...member, extra: true },
      former_owner: member,
    }),
  ).toThrow(z.ZodError);
});

const commands: Array<[OrganisationCommand, string, string, object, unknown]> =
  [
    [
      {
        kind: "add",
        email: member.email,
        role: "admin",
        reason: "Fictional staff request",
      },
      "/members",
      "POST",
      { email: member.email, role: "admin" },
      invite,
    ],
    [
      {
        kind: "role",
        person_id: member.person_id,
        role: "admin",
        reason: "Fictional role request",
      },
      `/members/${member.person_id}`,
      "PATCH",
      { role: "admin" },
      { ...member, role: "admin" },
    ],
    [
      {
        kind: "remove",
        person_id: member.person_id,
        reason: "Fictional removal request",
      },
      `/members/${member.person_id}`,
      "DELETE",
      {},
      undefined,
    ],
    [
      {
        kind: "transfer",
        person_id: member.person_id,
        reason: "Fictional owner request",
      },
      "/owner",
      "POST",
      { person_id: member.person_id },
      {
        owner: { ...member, role: "owner" },
        former_owner: {
          ...member,
          person_id: organisation.tenant_id,
          role: "admin",
        },
      },
    ],
    [
      {
        kind: "revoke",
        invite_id: organisation.tenant_id,
        reason: "Fictional invite request",
      },
      `/invites/${organisation.tenant_id}`,
      "DELETE",
      {},
      undefined,
    ],
  ];

it.each(commands)(
  "dispatches $kind with a new UUIDv4 and parses its outcome",
  async (command, path, method, fields, result) => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockImplementation(async () =>
        result === undefined
          ? new Response(null, { status: 204 })
          : json(result),
      );
    for (let attempt = 0; attempt < 2; attempt++) {
      await expect(
        changePlatformOrganisation(organisation.tenant_id, command, {
          fetcher,
        }),
      ).resolves.toEqual(result);
    }
    const keys = fetcher.mock.calls.map(([url, init]) => {
      expect(url).toBe(
        `/v1/platform/organisations/${organisation.tenant_id}${path}`,
      );
      expect(init).toMatchObject({
        method,
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
      expect(JSON.parse(init!.body as string)).toEqual({
        reason: command.reason,
        ...fields,
      });
      const headers = new Headers(init!.headers);
      expect(headers.get("content-type")).toBe("application/json");
      const key = headers.get("Idempotency-Key")!;
      expect(z.uuidv4().parse(key)).toBe(key);
      return key;
    });
    expect(new Set(keys).size).toBe(2);
  },
);

it.each(
  commands.flatMap(([command]) =>
    [403, 404, 409].map((status) => ({ command, status })),
  ),
)(
  "preserves $status messages for $command.kind",
  async ({ command, status }) => {
    const detail = `Fictional ${command.kind} rejection ${status}.`;
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      json(
        {
          code: "fictional_conflict",
          title: "Rejected",
          detail,
          request_id: "example-request",
        },
        status,
      ),
    );
    await expect(
      changePlatformOrganisation(organisation.tenant_id, command, { fetcher }),
    ).rejects.toMatchObject({
      status,
      message: detail,
      requestId: "example-request",
    });
  },
);

it.each(["", " ", "ab", "a".repeat(201)])(
  "refuses invalid reason before dispatch",
  async (reason) => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(
      changePlatformOrganisation(
        organisation.tenant_id,
        { ...commands[0][0], reason },
        { fetcher },
      ),
    ).rejects.toBeInstanceOf(z.ZodError);
    expect(fetcher).not.toHaveBeenCalled();
  },
);
it("rejects malformed mutation responses and unknown member envelopes", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(json({ ...member, extra: true }));
  await expect(
    changePlatformOrganisation(organisation.tenant_id, commands[0][0], {
      fetcher,
    }),
  ).rejects.toBeInstanceOf(z.ZodError);
  fetcher.mockResolvedValue(json({ members: [member], extra: true }));
  await expect(
    loadOrganisationMembers(organisation.tenant_id, { fetcher }),
  ).rejects.toBeInstanceOf(z.ZodError);
});
