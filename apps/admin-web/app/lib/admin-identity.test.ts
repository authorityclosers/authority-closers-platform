import { describe, expect, it } from "vitest";
import { verifyAdminIdentity } from "./admin-identity";

const person = "11111111-1111-4111-8111-111111111111";
const session = "22222222-2222-4222-8222-222222222222";
const tenant = "33333333-3333-4333-8333-333333333333";
const program = "44444444-4444-4444-8444-444444444444";
const me = {
  person_id: person,
  email: "coach@example.test",
  display_name: "Coach",
  email_verified_at: "2026-09-07T00:00:00Z",
  selected_tenant_id: tenant,
  membership_role: "learner",
  permissions: [],
};
const context = {
  person_id: person,
  session_id: session,
  tenant_id: tenant,
  membership_role: "learner",
  permissions: [],
};
const capability = {
  permission: "catalog_read",
  scope_kind: "program",
  tenant_id: tenant,
  program_id: program,
};
const access = {
  person_id: person,
  session_id: session,
  tenant_id: tenant,
  studio_capabilities: [capability],
};

describe("canonical Studio admission", () => {
  it("admits assigned learner scope without changing role or generic permissions", () => {
    const identity = verifyAdminIdentity(me, context, access);
    expect(identity?.context.membership_role).toBe("learner");
    expect(identity?.context.permissions).toEqual([]);
    expect(identity?.studioCapabilities).toEqual([capability]);
  });
  it("keeps legacy admin admission when no explicit capabilities are assigned", () => {
    const legacy = { membership_role: "admin", permissions: ["admin_surface"] };
    expect(
      verifyAdminIdentity(
        { ...me, ...legacy },
        { ...context, ...legacy },
        { ...access, studio_capabilities: [] },
      ),
    ).not.toBeNull();
  });
  it.each([
    { ...access, studio_capabilities: [] },
    { ...access, session_id: program },
    { ...access, person_id: program },
    { ...access, tenant_id: program },
    { ...access, studio_capabilities: [{ ...capability, tenant_id: program }] },
    { ...access, studio_capabilities: [{ ...capability, program_id: null }] },
    {
      ...access,
      studio_capabilities: [{ ...capability, scope_kind: "tenant" }],
    },
    {
      ...access,
      studio_capabilities: [
        { ...capability, permission: "platform_catalog_read" },
      ],
    },
    {
      ...access,
      studio_capabilities: [{ ...capability, permission: "enrollment_grant" }],
    },
    { ...access, studio_capabilities: [capability, capability] },
  ])("denies invalid, cross-context, or absent Studio access", (invalid) => {
    expect(verifyAdminIdentity(me, context, invalid)).toBeNull();
  });
  it("requires unchanged strict identity payloads and matching generic permissions", () => {
    expect(
      verifyAdminIdentity({ ...me, studio_capabilities: [] }, context, access),
    ).toBeNull();
    expect(
      verifyAdminIdentity(
        me,
        { ...context, permissions: ["admin_surface"] },
        access,
      ),
    ).toBeNull();
    expect(
      verifyAdminIdentity(me, { ...context, membership_role: "admin" }, access),
    ).toBeNull();
  });
});
