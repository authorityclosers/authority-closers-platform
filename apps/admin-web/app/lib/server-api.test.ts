import { describe, expect, it, vi } from "vitest";

import { normalizeAcademies } from "../platform/platform-data";
import {
  MESSAGES,
  adminRead,
  devEdgeTransport,
  internalTransport,
  read,
  sessionCookieFrom,
} from "./server-api";

const env = {
  AC_INTERNAL_API_HOST: "api.staging.ac.internal.invalid",
  AC_INTERNAL_API_URL: "http://api.staging.ac.internal.invalid:8000",
};
const session = { name: "__Host-ac_session", value: "a".repeat(43) };
const ok = (body: unknown) =>
  vi.fn().mockResolvedValue({
    status: 200,
    body: Buffer.from(JSON.stringify(body)),
  });

describe("server reads", () => {
  it("talks only to the trusted internal API, as the matching Admin host", () => {
    expect(internalTransport(env)?.adminHost).toBe(
      "admin-staging.authorityclosers.com",
    );
    expect(
      internalTransport({
        ...env,
        AC_INTERNAL_API_URL: "http://evil.example:8000",
      }),
    ).toBeNull();
    expect(
      internalTransport({ ...env, AC_INTERNAL_API_HOST: "evil.example" }),
    ).toBeNull();
    expect(internalTransport({})).toBeNull();
  });

  it("forwards exactly one well-formed session cookie and nothing else", () => {
    expect(sessionCookieFrom([session, { name: "other", value: "x" }])).toBe(
      `__Host-ac_session=${"a".repeat(43)}`,
    );
    expect(sessionCookieFrom([session, session])).toBeNull();
    expect(sessionCookieFrom([{ ...session, value: "short" }])).toBeNull();
    expect(sessionCookieFrom([])).toBeNull();
  });

  it("returns data, or a message per failure, and never throws", async () => {
    const get = ok({ tenants: [{ tenant_id: "t1", name: "Acme" }] });
    const result = await adminRead("/v1/platform/tenants", normalizeAcademies, {
      env,
      cookies: [session],
      get,
    });
    expect(result).toEqual({
      ok: true,
      status: 200,
      data: {
        academies: [
          { id: "t1", name: "Acme", status: "unknown", kind: "academy" },
        ],
        nextAfterId: null,
      },
    });
    const [url, host, cookie] = get.mock.calls[0]!;
    expect(String(url)).toBe(
      "http://api.staging.ac.internal.invalid:8000/v1/platform/tenants",
    );
    expect(host).toBe("admin-staging.authorityclosers.com");
    expect(cookie).toContain("__Host-ac_session=");

    expect(
      await adminRead("/v1/x", read.object, {
        env: {},
        cookies: [session],
        get,
      }),
    ).toMatchObject({ ok: false, status: 503, error: MESSAGES.notConnected });
    expect(
      await adminRead("/v1/x", read.object, { env, cookies: [], get }),
    ).toMatchObject({ ok: false, status: 401 });
    const status = (code: number) =>
      vi.fn().mockResolvedValue({ status: code, body: Buffer.from("{}") });
    expect(
      await adminRead("/v1/x", read.object, {
        env,
        cookies: [session],
        get: status(403),
      }),
    ).toMatchObject({ error: MESSAGES.forbidden });
    expect(
      await adminRead("/v1/x", read.object, {
        env,
        cookies: [session],
        get: status(404),
      }),
    ).toMatchObject({ error: MESSAGES.notFound });
    expect(
      await adminRead("/v1/x", read.object, {
        env,
        cookies: [session],
        get: status(500),
      }),
    ).toMatchObject({ error: MESSAGES.reconnecting });
    const broken = vi
      .fn()
      .mockResolvedValue({ status: 200, body: Buffer.from("not json") });
    expect(
      await adminRead("/v1/x", read.object, {
        env,
        cookies: [session],
        get: broken,
      }),
    ).toMatchObject({ ok: false, error: MESSAGES.unreadable });
    const down = vi.fn().mockRejectedValue(new Error("ECONNREFUSED"));
    expect(
      await adminRead("/v1/x", read.object, {
        env,
        cookies: [session],
        get: down,
      }),
    ).toMatchObject({ ok: false, error: MESSAGES.reconnecting });
  });

  it("refuses paths that could leave the admin API", async () => {
    const get = ok({});
    for (const path of [
      "https://evil.example/v1/x",
      "/v1/../internal",
      "//evil/v1",
      "/v2/x",
      "/v1/x#y",
    ])
      expect(
        await adminRead(path, read.object, { env, cookies: [session], get }),
      ).toMatchObject({ ok: false, status: 400 });
    expect(get).not.toHaveBeenCalled();
  });

  it("gives missing fields defaults instead of failing", () => {
    expect(read.string(undefined, "x")).toBe("x");
    expect(read.number("3")).toBe(0);
    expect(read.strings(["a", 1, "b"])).toEqual(["a", "b"]);
    expect(read.object([])).toEqual({});
    expect(normalizeAcademies(null)).toEqual({
      academies: [],
      nextAfterId: null,
    });
  });

  it("in development only, reads through the loopback dev edge as admin-dev", async () => {
    const dev = {
      NODE_ENV: "development",
      AC_ADMIN_DEV_HOST: "admin-dev.authorityclosers.com",
      AC_ADMIN_DEV_EDGE_ORIGIN: "http://127.0.0.1:3017",
    };
    expect(devEdgeTransport(dev)?.adminHost).toBe(
      "admin-dev.authorityclosers.com",
    );
    expect(devEdgeTransport({ ...dev, NODE_ENV: "production" })).toBeNull();
    expect(
      devEdgeTransport({
        ...dev,
        AC_ADMIN_DEV_HOST: "admin.authorityclosers.com",
      }),
    ).toBeNull();
    expect(
      devEdgeTransport({
        ...dev,
        AC_ADMIN_DEV_EDGE_ORIGIN: "http://10.0.0.5:3017",
      }),
    ).toBeNull();
    expect(
      devEdgeTransport({
        ...dev,
        AC_ADMIN_DEV_EDGE_ORIGIN: "https://127.0.0.1:3017",
      }),
    ).toBeNull();
    expect(internalTransport(dev)?.origin.toString()).toBe(
      "http://127.0.0.1:3017/",
    );
    const get = ok({ email: "x" });
    const devCookie = { name: "ac_session", value: "d".repeat(43) };
    expect(
      await adminRead("/v1/me", read.object, {
        env: dev,
        cookies: [devCookie],
        get,
      }),
    ).toMatchObject({ ok: true });
    expect(get.mock.calls[0]![1]).toBe("admin-dev.authorityclosers.com");
    expect(get.mock.calls[0]![2]).toBe(`ac_session=${"d".repeat(43)}`);
    // Production transports never accept the development cookie name.
    expect(
      await adminRead("/v1/me", read.object, {
        env,
        cookies: [devCookie],
        get,
      }),
    ).toMatchObject({ ok: false, status: 401 });
    // admin-dev reads the dev live API: its session wins over older ones.
    const liveCookie = {
      name: "__Host-ac_live_session",
      value: "l".repeat(43),
    };
    expect(
      await adminRead("/v1/me", read.object, {
        env: dev,
        cookies: [devCookie, session, liveCookie],
        get,
      }),
    ).toMatchObject({ ok: true });
    expect(get.mock.calls.at(-1)![2]).toBe(
      `__Host-ac_live_session=${"l".repeat(43)}`,
    );
    expect(
      await adminRead("/v1/me", read.object, {
        env,
        cookies: [liveCookie],
        get,
      }),
    ).toMatchObject({ ok: false, status: 401 });
  });
});
