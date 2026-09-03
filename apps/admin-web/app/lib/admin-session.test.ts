import { describe, expect, it } from "vitest";

import { canUseAdminPermission, type AdminSessionState } from "./admin-session";

const readyState: AdminSessionState = {
  status: "ready",
  error: null,
  session: {
    personId: "11111111-1111-4111-8111-111111111111",
    email: "admin@authorityclosers.com",
    displayName: "AC Admin",
    emailVerifiedAt: "2026-08-30T00:00:00Z",
    sessionId: "22222222-2222-4222-8222-222222222222",
    tenantId: "33333333-3333-4333-8333-333333333333",
    membershipRole: "admin",
    permissions: ["admin_surface", "catalog_publish"],
  },
};

describe("admin session boundary", () => {
  it("denies every capability while the product session is loading or rejected", () => {
    const states: AdminSessionState[] = [
      { status: "loading", session: null, error: null },
      { status: "denied", session: null, error: "denied" },
      { status: "error", session: null, error: "unavailable" },
    ];
    for (const state of states) {
      expect(canUseAdminPermission(state, "admin_surface")).toBe(false);
      expect(canUseAdminPermission(state, "catalog_publish")).toBe(false);
    }
  });

  it("requires both admin_surface and the exact capability permission", () => {
    expect(canUseAdminPermission(readyState, "catalog_publish")).toBe(true);
    expect(canUseAdminPermission(readyState, "learning_correct")).toBe(false);
    expect(
      canUseAdminPermission(
        {
          ...readyState,
          session: { ...readyState.session, permissions: ["catalog_publish"] },
        },
        "catalog_publish",
      ),
    ).toBe(false);
  });
});
