import { describe, expect, it, vi } from "vitest";
import {
  loadOperationsWorkspaces,
  operationsSessionMatches,
  selectOperationsWorkspace,
  type OperationsWorkspaces,
} from "@ac/operations-web/workspaces";

const person = "11111111-1111-4111-8111-111111111111";
const session = "22222222-2222-4222-8222-222222222222";
const tenant = "33333333-3333-4333-8333-333333333333";
const other = "44444444-4444-4444-8444-444444444444";
const choices: OperationsWorkspaces = {
  person_id: person,
  session_id: session,
  selected_tenant_id: null,
  workspaces: [
    { tenant_id: tenant, name: "Synthetic Academy" },
    { tenant_id: other, name: "Second Academy" },
  ],
};
function context() {
  return {
    person_id: person,
    session_id: session,
    tenant_id: tenant,
    membership_role: "admin",
    permissions: ["admin_surface"],
  };
}
function identityFetcher(
  overrides: { context?: object; me?: object; access?: object } = {},
) {
  return vi.fn<typeof fetch>().mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/v1/context")
      return Response.json({ ...context(), ...overrides.context });
    if (path === "/v1/me")
      return Response.json({
        person_id: person,
        email: "synthetic@example.test",
        display_name: "Synthetic",
        email_verified_at: "2026-09-08T00:00:00Z",
        selected_tenant_id: tenant,
        membership_role: "admin",
        permissions: ["admin_surface"],
        ...overrides.me,
      });
    if (path === "/v1/me/studio-access")
      return Response.json({
        person_id: person,
        session_id: session,
        tenant_id: tenant,
        studio_capabilities: [],
        ...overrides.access,
      });
    throw new Error("Unexpected synthetic path");
  });
}
describe("canonical operations workspace selection", () => {
  it("loads only the own-session fixed path, no-store and same-origin", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(choices));
    const signal = new AbortController().signal;
    await expect(
      loadOperationsWorkspaces({ fetcher, signal }),
    ).resolves.toEqual(choices);
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/me/workspaces",
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        signal,
      }),
    );
  });
  it("quietly treats an anonymous401 as no existing session", async () => {
    await expect(
      loadOperationsWorkspaces({
        fetcher: vi
          .fn<typeof fetch>()
          .mockResolvedValue(new Response(null, { status: 401 })),
      }),
    ).resolves.toBeNull();
  });
  it.each([
    { ...choices, person_id: "invalid" },
    { ...choices, session_id: "invalid" },
    { ...choices, workspaces: [choices.workspaces[0], choices.workspaces[0]] },
    { ...choices, workspaces: [{ tenant_id: tenant, name: "" }] },
    {
      ...choices,
      workspaces: [{ tenant_id: tenant, name: "Academy", role: "admin" }],
    },
    { ...choices, access_token: "synthetic-never-display" },
  ])(
    "rejects malformed or authority-shaped workspace payload %#",
    async (payload) => {
      const fetcher = vi
        .fn<typeof fetch>()
        .mockResolvedValue(Response.json(payload));
      await expect(loadOperationsWorkspaces({ fetcher })).rejects.toThrow(
        "workspace could not be verified",
      );
    },
  );
  it("does not display upstream bodies or network error messages", async () => {
    for (const fetcher of [
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response("synthetic-sensitive-marker", { status: 500 }),
        ),
      vi
        .fn<typeof fetch>()
        .mockRejectedValue(new Error("synthetic-sensitive-marker")),
    ]) {
      await expect(loadOperationsWorkspaces({ fetcher })).rejects.toThrow(
        "workspace could not be verified",
      );
    }
  });
  it("selects only an offered workspace and rechecks the canonical identity before admission", async () => {
    const fetcher = identityFetcher();
    const signal = new AbortController().signal;
    const result = await selectOperationsWorkspace(choices, tenant, "admin", {
      fetcher,
      signal,
    });
    expect(result.tenantId).toBe(tenant);
    expect(fetcher.mock.calls.map(([input]) => input)).toEqual([
      "/v1/context",
      "/v1/me",
      "/v1/context",
      "/v1/me/studio-access",
    ]);
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      body: JSON.stringify({ tenant_id: tenant }),
      signal,
    });
    expect(
      fetcher.mock.calls.every(([, init]) => init?.signal === signal),
    ).toBe(true);
  });
  it("rejects an invented tenant before any write", async () => {
    const fetcher = identityFetcher();
    await expect(
      selectOperationsWorkspace(choices, person, "admin", { fetcher }),
    ).rejects.toThrow("listed for your account");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each([{ person_id: other }, { session_id: other }, { tenant_id: other }])(
    "rejects a changed selection response scope %#",
    async (change) => {
      const fetcher = identityFetcher({ context: change });
      await expect(
        selectOperationsWorkspace(choices, tenant, "admin", { fetcher }),
      ).rejects.toThrow();
      expect(fetcher).toHaveBeenCalledTimes(1);
    },
  );
  it("does not turn admin membership into a Coach capability", async () => {
    await expect(
      selectOperationsWorkspace(choices, tenant, "coach", {
        fetcher: identityFetcher(),
      }),
    ).rejects.toThrow("no Academy Studio assignment");
  });
  it("admits a learner with a real exact-program Studio assignment, not Platform Admin", async () => {
    const fetcher = identityFetcher({
      context: { membership_role: "learner", permissions: [] },
      me: { membership_role: "learner", permissions: [] },
      access: {
        studio_capabilities: [
          {
            permission: "catalog_read",
            scope_kind: "program",
            tenant_id: tenant,
            program_id: other,
          },
        ],
      },
    });
    const verified = await selectOperationsWorkspace(choices, tenant, "coach", {
      fetcher,
    });
    expect(operationsSessionMatches(verified, choices, tenant, "coach")).toBe(
      true,
    );
    expect(operationsSessionMatches(verified, choices, tenant, "admin")).toBe(
      false,
    );
    expect(
      operationsSessionMatches(
        { ...verified, personId: other },
        choices,
        tenant,
        "coach",
      ),
    ).toBe(false);
    expect(
      operationsSessionMatches(
        { ...verified, sessionId: other },
        choices,
        tenant,
        "coach",
      ),
    ).toBe(false);
    expect(
      operationsSessionMatches(
        { ...verified, tenantId: other },
        choices,
        tenant,
        "coach",
      ),
    ).toBe(false);
  });
});
