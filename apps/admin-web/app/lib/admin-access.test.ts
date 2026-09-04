import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { proxy } from "../../proxy";
import {
  evaluateAdminAccess,
  LOCAL_PREVIEW_ENV,
  normalizeAdminRuntime,
  renderPermissionDeniedDocument,
} from "./admin-access";

const DEPLOYMENT_SESSION_TOKEN = "s".repeat(43);
const ACCESS_JWT = `${"a".repeat(32)}.${"b".repeat(64)}.${"c".repeat(32)}`;

describe("admin route access policy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("denies production without verified server-owned context", () => {
    expect(
      evaluateAdminAccess({
        runtime: "production",
        localPreviewEnabled: true,
        serverContext: null,
      }),
    ).toEqual({
      allowed: false,
      mode: "denied",
      reason: "missing-server-context",
    });
  });

  it("does not accept request-like role assertions as server context", () => {
    expect(
      evaluateAdminAccess({
        runtime: "production",
        localPreviewEnabled: false,
        serverContext: {
          role: "admin",
          query: { role: "admin" },
          headers: { "x-admin-role": "admin" },
        },
      }),
    ).toMatchObject({ allowed: false, reason: "missing-server-context" });
  });

  it("allows only an explicit non-production preview or verified context", () => {
    expect(
      evaluateAdminAccess({
        runtime: "development",
        localPreviewEnabled: false,
        serverContext: null,
      }),
    ).toMatchObject({ allowed: false, reason: "preview-not-enabled" });

    expect(
      evaluateAdminAccess({
        runtime: "test",
        localPreviewEnabled: true,
        serverContext: null,
      }),
    ).toEqual({ allowed: true, mode: "local-preview" });

    expect(
      evaluateAdminAccess({
        runtime: "production",
        localPreviewEnabled: false,
        serverContext: {
          source: "verified-server-session",
          authenticated: true,
          adminSurfaceAuthorized: true,
          actorId: "actor-from-server-session",
          tenantId: "tenant-from-server-session",
          permissions: ["admin_surface"],
        },
      }),
    ).toEqual({ allowed: true, mode: "authenticated" });
  });

  it("treats unknown runtime values as production", () => {
    expect(normalizeAdminRuntime(undefined)).toBe("production");
    expect(normalizeAdminRuntime("preview")).toBe("production");
    expect(normalizeAdminRuntime("development")).toBe("development");
  });

  it("returns a no-store 403 document from the production proxy", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv(LOCAL_PREVIEW_ENV, "1");

    const response = await proxy(
      new NextRequest("https://admin.authorityclosers.test/"),
    );
    const body = await response.text();

    expect(proxy.length).toBe(1);
    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(response.headers.get("content-security-policy")).toContain(
      "form-action 'none'",
    );
    expect(body).toContain("Permission denied / fail closed");
    expect(body).toContain("<main");
    expect(body).not.toContain("<form");
  });

  it("serves health only to the container loopback host", async () => {
    vi.stubEnv("NODE_ENV", "production");

    const internal = await proxy(
      new NextRequest("http://127.0.0.1:3001/healthz"),
    );
    const normalizedRuntimeOrigin = await proxy(
      new NextRequest("http://localhost:3000/healthz", {
        headers: { host: "127.0.0.1:3001" },
      }),
    );
    const external = await proxy(
      new NextRequest("https://admin.authorityclosers.com/healthz"),
    );

    expect(internal.status).toBe(200);
    expect(internal.headers.get("cache-control")).toBe("no-store");
    expect(await internal.json()).toEqual({
      status: "ok",
      service: "authority-closers-admin",
    });
    expect(normalizedRuntimeOrigin.status).toBe(200);
    expect(external.status).toBe(403);
  });

  it("allows an explicitly enabled local preview without request claims", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv(LOCAL_PREVIEW_ENV, "1");

    const response = await proxy(
      new NextRequest("http://localhost:3001/?role=owner", {
        headers: { "x-admin-role": "owner" },
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("opens the development shell only when the complete staging bridge contract is valid", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AC_DEV_ADMIN_AUTH_BRIDGE_ENABLED", "true");
    vi.stubEnv("AC_DEV_ADMIN_AUTH_BRIDGE_ORIGIN", "http://localhost:3001");
    vi.stubEnv(
      "AC_DEV_ADMIN_AUTH_BRIDGE_UPSTREAM_ORIGIN",
      "https://admin-staging.authorityclosers.com",
    );
    vi.stubEnv("AC_DEV_ADMIN_ACCESS_JWT", ACCESS_JWT);

    const valid = await proxy(new NextRequest("http://localhost:3001/"));
    expect(valid.status).toBe(200);
    expect(valid.headers.get("x-middleware-next")).toBe("1");

    vi.stubEnv("AC_DEV_ADMIN_ACCESS_JWT", "malformed");
    const malformed = await proxy(new NextRequest("http://localhost:3001/"));
    expect(malformed.status).toBe(403);
  });

  it("allows production only after the internal API verifies session and admin context", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv(
      "AC_INTERNAL_API_URL",
      "http://api.production.ac.internal.invalid:8000",
    );
    vi.stubEnv("AC_INTERNAL_API_HOST", "api.production.ac.internal.invalid");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockImplementation((input) =>
        Promise.resolve(
          Response.json(
            String(input).endsWith("/me")
              ? {
                  person_id: "11111111-1111-4111-8111-111111111111",
                  email: "admin@authorityclosers.com",
                  display_name: "AC Admin",
                  email_verified_at: "2026-08-30T00:00:00Z",
                  selected_tenant_id: "33333333-3333-4333-8333-333333333333",
                  membership_role: "admin",
                  permissions: ["admin_surface"],
                }
              : {
                  person_id: "11111111-1111-4111-8111-111111111111",
                  session_id: "22222222-2222-4222-8222-222222222222",
                  tenant_id: "33333333-3333-4333-8333-333333333333",
                  membership_role: "admin",
                  permissions: ["admin_surface"],
                },
          ),
        ),
      ),
    );

    const response = await proxy(
      new NextRequest("https://admin.authorityclosers.test/catalog", {
        headers: {
          cookie: `__Host-ac_session=${DEPLOYMENT_SESSION_TOKEN}`,
        },
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("keeps production denied when spoofed claims accompany an API rejection", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv(
      "AC_INTERNAL_API_URL",
      "http://api.production.ac.internal.invalid:8000",
    );
    vi.stubEnv("AC_INTERNAL_API_HOST", "api.production.ac.internal.invalid");
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValue(new Response('{"role":"owner"}', { status: 401 })),
    );

    const response = await proxy(
      new NextRequest("https://admin.authorityclosers.test/?role=owner", {
        headers: {
          cookie: "__Host-ac_session=invalid; role=owner",
          "x-admin-role": "owner",
        },
      }),
    );

    expect(response.status).toBe(403);
    expect(await response.text()).not.toContain("role=owner");
  });

  it("renders a semantic permission boundary document", () => {
    const document = renderPermissionDeniedDocument();

    expect(document).toContain('href="#admin-denied"');
    expect(document).toContain('id="admin-denied"');
    expect(document).toContain("Authenticated admin context required.");
    expect(document).toContain(
      "Client role assertions, request parameters, and headers cannot unlock",
    );
  });
});
