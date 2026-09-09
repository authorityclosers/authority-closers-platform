import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxy as coachProxy } from "../../../coach-web/proxy";
import { proxy as adminProxy } from "../../proxy";
import * as serverAuth from "@ac/operations-web/server-auth";
import { coachAppOrigin } from "@ac/operations-web/origins";
import {
  isCoachApiRequest,
  isStagingAdminRequest,
  proxyDevelopmentAdminApi,
} from "@ac/operations-web/dev-proxy";
const id = "11111111-1111-4111-8111-111111111111";
const origin = "http://coach.localhost:3102";
const environment = {
  AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
  AC_DEV_OPERATIONS_SURFACE: "coach",
  AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: origin,
  AC_DEV_ADMIN_API_ORIGIN: "http://127.0.0.1:8000",
};
describe("separate Coach surface", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });
  it("allows only the canonical workspace GET, never mutation or query selectors", () => {
    expect(isCoachApiRequest(new URL("/v1/me/workspaces", origin), "GET")).toBe(
      true,
    );
    expect(
      isCoachApiRequest(new URL("/v1/me/workspaces", origin), "POST"),
    ).toBe(false);
    expect(
      isCoachApiRequest(
        new URL("/v1/me/workspaces?person_id=" + id, origin),
        "GET",
      ),
    ).toBe(false);
  });
  it.each([adminProxy, coachProxy])(
    "uses a relative no-store login redirect behind an HTTP reverse proxy %#",
    async (proxy) => {
      vi.stubEnv("NODE_ENV", "production");
      vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "true");
      vi.spyOn(serverAuth, "resolveAdminServerContext").mockResolvedValue(null);
      const response = await proxy(
        new NextRequest(
          "http://internal.invalid:3002/people?secret=synthetic",
          {
            headers: {
              host: "coach.authorityclosers.com",
              "x-forwarded-proto": "https",
              "x-forwarded-host": "evil.test",
            },
          },
        ),
      );
      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toBe("/login");
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("x-middleware-next")).toBeNull();
    },
  );
  it("does not admit Platform Admin-only authority to Coach pages", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.spyOn(serverAuth, "resolveAdminServerContext").mockResolvedValue({
      source: "verified-server-session",
      authenticated: true,
      adminSurfaceAuthorized: true,
      actorId: id,
      tenantId: id,
      permissions: ["admin_surface"],
      studioCapabilities: [],
    });
    const response = await coachProxy(
      new NextRequest("https://coach.authorityclosers.com/studio/programs"),
    );
    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
  it("moves legacy Studio navigation without forwarding private query strings or cookies", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("AC_COACH_APP_URL", "https://coach.authorityclosers.com");
    const response = await adminProxy(
      new NextRequest(
        "https://admin.authorityclosers.com/studio/programs?token=synthetic",
        { headers: { cookie: "__Host-ac_session=synthetic" } },
      ),
    );
    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe(
      "https://coach.authorityclosers.com/studio/programs",
    );
    expect(response.headers.get("set-cookie")).toBeNull();
    const rejected = await adminProxy(
      new NextRequest("https://admin.authorityclosers.com/studio/programs", {
        method: "POST",
      }),
    );
    expect(rejected.status).toBe(405);
    expect(rejected.headers.get("location")).toBeNull();
  });
  it.each([
    "https://evil.test",
    "https://coach.authorityclosers.com@evil.test",
    "https://coach.authorityclosers.com/path",
    "https://*.authorityclosers.com",
    "http://coach.localhost:3102",
  ])("rejects invalid production target %s", (value) =>
    expect(coachAppOrigin(value, "production")).toBeNull(),
  );
  it("allows the exact configured release origins only", () => {
    expect(
      coachAppOrigin("https://coach.authorityclosers.com", "production"),
    ).toBe("https://coach.authorityclosers.com");
    expect(
      coachAppOrigin(
        "https://coach-staging.authorityclosers.com",
        "production",
      ),
    ).toBe("https://coach-staging.authorityclosers.com");
  });
  it.each([
    ["POST", `/v1/admin/studio/program-versions/${id}/modules`],
    ["POST", `/v1/admin/studio/program-versions/${id}/revision`],
    ["PATCH", `/v1/admin/studio/program-versions/${id}/modules/${id}`],
    [
      "POST",
      `/v1/admin/studio/program-versions/${id}/modules/${id}/activities`,
    ],
    ["PATCH", `/v1/admin/studio/program-versions/${id}/activities/${id}`],
  ])("permits only explicit authoring method %s %s", (method, path) => {
    expect(isCoachApiRequest(new URL(path, origin), method)).toBe(true);
    expect(isStagingAdminRequest(new URL(path, origin), method)).toBe(true);
    expect(
      isCoachApiRequest(new URL(path + "?override=1", origin), method),
    ).toBe(false);
    expect(isCoachApiRequest(new URL(path, origin), "DELETE")).toBe(false);
  });
  it.each([
    "/v1/admin/corrections",
    "/v1/admin/enrollment-grants",
    "/v1/admin/recovery/reconcile",
    `/v1/admin/jobs/${id}/retry`,
    "/v1/auth/password/register",
    "/v1/learning",
  ])("blocks non-Coach route %s without a network request", async (path) => {
    const fetcher = vi.fn();
    const result = await proxyDevelopmentAdminApi(
      new Request(origin + path, { method: "POST", headers: { origin } }),
      fetcher,
      environment,
      "development",
    );
    expect(result.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("does not accept the admin browser origin in the Coach process", async () => {
    const fetcher = vi.fn();
    const result = await proxyDevelopmentAdminApi(
      new Request("http://admin.localhost:3101/v1/me"),
      fetcher,
      environment,
      "development",
    );
    expect(result.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("never enables a development transport in production", async () => {
    const fetcher = vi.fn();
    const result = await proxyDevelopmentAdminApi(
      new Request(origin + "/v1/me"),
      fetcher,
      environment,
      "production",
    );
    expect(result.status).toBe(404);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
