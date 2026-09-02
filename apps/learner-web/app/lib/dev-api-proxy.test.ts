import { describe, expect, it, vi } from "vitest";

import {
  isStagingPublicCatalogPreview,
  isStagingPublicCatalogRequest,
  proxyDevelopmentLearnerApi,
  resolveDevApiTarget,
} from "./dev-api-proxy";

describe("development learner API proxy", () => {
  it("is disabled outside development", () => {
    expect(
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "production",
      ),
    ).toBeNull();
  });

  it("identifies only the exact development staging catalog mode", () => {
    expect(
      isStagingPublicCatalogPreview(
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "development",
      ),
    ).toBe(true);
    expect(
      isStagingPublicCatalogPreview(
        { AC_DEV_API_ORIGIN: "http://localhost:8000" },
        "development",
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogPreview(
        { AC_DEV_API_ORIGIN: "https://api.authorityclosers.com" },
        "development",
      ),
    ).toBe(false);
  });

  it("accepts loopback and the exact staging API but rejects arbitrary and production origins", () => {
    expect(resolveDevApiTarget({}, "development")).toEqual({
      mode: "local",
      origin: "http://127.0.0.1:8000",
    });
    expect(
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "development",
      ),
    ).toEqual({
      mode: "staging-public-catalog",
      origin: "https://api-staging.authorityclosers.com",
    });
    expect(() =>
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://api.authorityclosers.com" },
        "development",
      ),
    ).toThrow("Production and arbitrary remote origins are forbidden");
    expect(() =>
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "https://user:secret@localhost:8000/path" },
        "development",
      ),
    ).toThrow("only a scheme, host, and optional port");
  });

  it("cannot enable a hidden full-access staging proxy mode", () => {
    expect(
      resolveDevApiTarget(
        {
          AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com",
          AC_DEV_STAGING_FULL_ACCESS: "true",
        },
        "development",
      ),
    ).toEqual({
      mode: "staging-public-catalog",
      origin: "https://api-staging.authorityclosers.com",
    });
  });

  it("treats blank optional configuration as unset", () => {
    expect(
      resolveDevApiTarget(
        { AC_DEV_API_ORIGIN: "  ", AC_API_URL: "http://localhost:8000/" },
        "development",
      ),
    ).toEqual({ mode: "local", origin: "http://localhost:8000" });
  });

  it("allows only bounded catalog URLs for remote staging preview", () => {
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=50"),
      ),
    ).toBe(true);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs/free-course"),
      ),
    ).toBe(true);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=500"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=50&limit=51"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs?limit=050"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs/free-course/private"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(new URL("http://localhost:3000/v1/me")),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL("http://localhost:3000/v1/programs/%2F"),
      ),
    ).toBe(false);
    expect(
      isStagingPublicCatalogRequest(
        new URL(`http://localhost:3000/v1/programs/${"a".repeat(121)}`),
      ),
    ).toBe(false);
  });

  it("strips credentials and cookies in the staging catalog mode", async () => {
    const fetcher = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(
          "https://api-staging.authorityclosers.com/v1/programs?limit=50",
        );
        const headers = new Headers(init?.headers);
        expect(headers.has("cookie")).toBe(false);
        expect(headers.has("authorization")).toBe(false);
        expect(headers.has("x-api-key")).toBe(false);
        expect(headers.has("referer")).toBe(false);
        return Response.json(
          { items: [], next_cursor: null },
          {
            headers: {
              "content-encoding": "gzip",
              "set-cookie": "should-not-return=1",
            },
          },
        );
      },
    );
    const result = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=50", {
        headers: {
          authorization: "Bearer secret",
          cookie: "__Host-ac_session=secret",
          "x-api-key": "should-not-forward",
          referer: "http://localhost:3000/private?token=should-not-forward",
        },
      }),
      fetcher,
      { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
      "development",
    );

    expect(result.status).toBe(200);
    expect(result.headers.get("set-cookie")).toBeNull();
    expect(result.headers.get("content-encoding")).toBeNull();
    expect(result.headers.get("x-ac-dev-data-mode")).toBe(
      "staging-public-catalog",
    );
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("does not follow or expose redirects from the staging preview", async () => {
    const fetcher = vi.fn(
      async () =>
        new Response(null, {
          status: 302,
          headers: { location: "https://authorityclosers.com/private" },
        }),
    );
    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=50"),
      fetcher,
      { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
      "development",
    );

    expect(response.status).toBe(502);
    expect(response.headers.get("location")).toBeNull();
  });

  it("does not call upstream when the incoming request is already cancelled", async () => {
    const fetcher = vi.fn();
    const controller = new AbortController();
    controller.abort();

    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=50", {
        signal: controller.signal,
      }),
      fetcher,
      { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
      "development",
    );

    expect(response.status).toBe(504);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("blocks private reads and every mutation before remote staging is called", async () => {
    const fetcher = vi.fn();
    for (const request of [
      new Request("http://localhost:3000/v1/me"),
      new Request("http://localhost:3000/v1/programs", { method: "POST" }),
    ]) {
      const result = await proxyDevelopmentLearnerApi(
        request,
        fetcher,
        { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
        "development",
      );
      expect(result.status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("preserves the browser Origin and cookies for the loopback API", async () => {
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        const headers = new Headers(init?.headers);
        expect(headers.get("origin")).toBe("http://localhost:3000");
        expect(headers.get("cookie")).toBe("local-session=value");
        expect(init?.method).toBe("POST");
        return Response.json({ accepted: true });
      },
    );
    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/enrollments/free", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          cookie: "local-session=value",
          origin: "http://localhost:3000",
        },
        body: JSON.stringify({ program_version_id: "version-1" }),
      }),
      fetcher,
      { AC_DEV_API_ORIGIN: "http://127.0.0.1:8000" },
      "development",
    );
    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
