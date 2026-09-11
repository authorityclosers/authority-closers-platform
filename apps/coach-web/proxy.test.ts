import { NextRequest } from "next/server";
// The pinned Next 16.3.3 version still exports the middleware-named helper.
import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveAdminServerContext } from "@ac/operations-web/server-auth";
import { config, proxy } from "./proxy";

vi.mock("@ac/operations-web/server-auth", () => ({
  resolveAdminServerContext: vi.fn(),
}));

const program = "11111111-1111-4111-8111-111111111111";
const upload = "22222222-2222-4222-8222-222222222222";
const uploadPath = `/v1/admin/studio/programs/${program}/video-uploads/${upload}`;
const matches = (url: string) =>
  unstable_doesMiddlewareMatch({ config, nextConfig: {}, url });

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetAllMocks();
});

describe("Coach video upload routing", () => {
  it.each(["/bytes", "/bytes/", "/bytes?unexpected=query"])(
    "does not clone the raw upload body at %s",
    (suffix) => {
      expect(matches(uploadPath + suffix)).toBe(false);
    },
  );

  it.each([
    "/",
    "/login",
    "/healthz",
    "/studio",
    "/studio/settings",
    `/studio/programs/${program}`,
    "/v1/me",
    "/v1/auth/login",
    `/v1/admin/studio/programs/${program}/video-uploads`,
    uploadPath,
    `${uploadPath}/complete`,
    `${uploadPath}/bytes/extra`,
    `${uploadPath}/bytes-other`,
    `/v1/admin/studio/programs/${program}/videos/${upload}/preview/bytes`,
  ])("preserves Proxy matching for %s", (path) => {
    expect(matches(path)).toBe(true);
  });

  it.each(["/_next/static/chunk.js", "/_next/image", "/favicon.ico"])(
    "preserves the existing asset exclusion for %s",
    (path) => {
      expect(matches(path)).toBe(false);
    },
  );

  it("does not add a page-level authentication bypass: v1 already passed through", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const response = await proxy(
      new NextRequest(`https://coach.authorityclosers.com${uploadPath}/bytes`, {
        method: "PUT",
      }),
    );
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(resolveAdminServerContext).not.toHaveBeenCalled();
  });

  it.each(["coach.authorityclosers.com", "coach-staging.authorityclosers.com"])(
    "still sends signed-out Studio pages on %s to normal login",
    async (host) => {
      vi.stubEnv("NODE_ENV", "production");
      vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "true");
      vi.mocked(resolveAdminServerContext).mockResolvedValue(null);
      const response = await proxy(new NextRequest(`https://${host}/studio`));
      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toBe(`https://${host}/login`);
      expect(resolveAdminServerContext).toHaveBeenCalledOnce();
    },
  );

  it("still rejects a Studio page without a tenant-scoped capability", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.mocked(resolveAdminServerContext).mockResolvedValue({
      source: "verified-server-session",
      authenticated: true,
      adminSurfaceAuthorized: true,
      actorId: "actor",
      tenantId: "tenant",
      permissions: [],
      studioCapabilities: [],
    });
    const response = await proxy(
      new NextRequest("https://coach.authorityclosers.com/studio"),
    );
    expect(response.status).toBe(403);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});
