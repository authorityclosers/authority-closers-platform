import { describe, expect, it, vi } from "vitest";

import { normalizeAcademies } from "../platform/platform-data";
import {
  MESSAGES,
  adminRead,
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
});
