import { expect, it } from "vitest";
import {
  contextSchema,
  meSchema,
  membershipRoleSchema,
} from "./admin-identity";

const personId = "11111111-1111-4111-8111-111111111111";
const sessionId = "22222222-2222-4222-8222-222222222222";
const tenantId = "33333333-3333-4333-8333-333333333333";

it("accepts member in strict /v1/me and /v1/context identity payloads", () => {
  expect(membershipRoleSchema.parse("member")).toBe("member");
  expect(
    meSchema.parse({
      person_id: personId,
      email: "member@example.test",
      display_name: null,
      email_verified_at: "2026-09-30T08:00:00Z",
      selected_tenant_id: tenantId,
      membership_role: "member",
      permissions: [],
    }).membership_role,
  ).toBe("member");
  expect(
    contextSchema.parse({
      person_id: personId,
      session_id: sessionId,
      tenant_id: tenantId,
      membership_role: "member",
      permissions: [],
    }).membership_role,
  ).toBe("member");
});
