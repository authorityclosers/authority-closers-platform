// @vitest-environment node
import { createHash } from "node:crypto";
import { EventEmitter } from "node:events";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const wire = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("node:http", () => ({ request: wire.request }));
import { proxyLocalSandboxAvatarUpload } from "./local-avatar-upstream";
import {
  isLocalSandboxAvatarUploadUrl,
  MAX_LOCAL_AVATAR_BYTES,
} from "./local-avatar-url";

const origin = "http://learner.localhost:3100";
const uuid = "11111111-1111-4111-8111-111111111111";
const key = `tenants/${uuid}/media/avatar/${uuid}/${uuid}/original`;
const path = `/v1/media/local-avatar-upload/${encodeURIComponent(key)}?token=AC-MEDIA.fixture.${"s".repeat(43)}`;
const body = "synthetic-avatar-not-real-person";
const checksum = createHash("sha256").update(body).digest("hex");
const cookie = `ac_session=${"c".repeat(43)}`;
let upstream: EventEmitter & {
  end: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
  setTimeout: ReturnType<typeof vi.fn>;
};
let response: EventEmitter & {
  statusCode: number;
  destroy: ReturnType<typeof vi.fn>;
};
const request = (
  headers: Record<string, string> = {},
  url = origin + path,
  data: BodyInit = body,
) =>
  new Request(url, {
    method: "PUT",
    body: data,
    headers: {
      origin,
      cookie,
      "content-type": "image/png",
      "content-length": String(body.length),
      "x-content-sha256": checksum,
      ...headers,
    },
  });
beforeEach(() => {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "true");
  vi.stubEnv("NEXT_PUBLIC_AC_LOCAL_SANDBOX_ENABLED", "true");
  vi.stubEnv("NODE_DEBUG", "");
  vi.stubEnv("AC_DEV_API_ORIGIN", "http://127.0.0.1:8000");
  vi.stubEnv("AC_DEV_AUTH_BRIDGE_ENABLED", "false");
  upstream = Object.assign(new EventEmitter(), {
    end: vi.fn(),
    destroy: vi.fn(),
    setTimeout: vi.fn(),
  });
  response = Object.assign(new EventEmitter(), {
    statusCode: 204,
    destroy: vi.fn(),
  });
  wire.request.mockReset().mockImplementation((_options, callback) => {
    upstream.end.mockImplementation(() => callback(response));
    return upstream;
  });
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("sends only verified bounded bytes and exact session to fixed native loopback", async () => {
  const result = await proxyLocalSandboxAvatarUpload(
    request({
      authorization: "Bearer discarded",
      "x-forwarded-for": "discarded",
      cookie: `other=discarded; ${cookie}`,
    }),
  );
  expect(result.status).toBe(204);
  expect(result.body).toBeNull();
  expect(result.headers.get("cache-control")).toBe("no-store");
  expect(wire.request.mock.calls[0][0]).toEqual({
    hostname: "127.0.0.1",
    port: 8000,
    agent: false,
    maxHeaderSize: 16384,
    method: "PUT",
    path,
    headers: {
      origin,
      cookie,
      "content-type": "image/png",
      "content-length": String(body.length),
      "x-content-sha256": checksum,
      "accept-encoding": "identity",
    },
  });
  expect(upstream.end.mock.calls[0][0].toString()).toBe(body);
});
it.each([
  { origin: "https://remote.example" },
  { origin: "" },
  { cookie: "" },
  { cookie: `${cookie}; ${cookie}` },
  { "sec-fetch-site": "cross-site" },
  { host: "remote.example" },
  { "x-forwarded-host": "remote.example" },
  { "x-forwarded-proto": "https" },
  { "content-type": "image/svg+xml" },
  { "content-encoding": "gzip" },
  { "content-length": String(MAX_LOCAL_AVATAR_BYTES + 1) },
  { "content-length": "0" },
  { "content-length": "01" },
  { "x-content-sha256": "invalid" },
] as Record<string, string>[])(
  "rejects invalid upload envelope before native transport: %j",
  async (headers) => {
    expect((await proxyLocalSandboxAvatarUpload(request(headers))).status).toBe(
      403,
    );
    expect(wire.request).not.toHaveBeenCalled();
  },
);
it.each([
  "http://remote.example",
  "http://127.0.0.1:3100",
  "http://localhost:3101",
])("rejects unexpected origin %s", async (source) => {
  expect(
    (await proxyLocalSandboxAvatarUpload(request({}, source + path))).status,
  ).toBe(403);
  expect(wire.request).not.toHaveBeenCalled();
});
it("allows only Next's exact bind origin with exact browser Host", async () => {
  expect(
    (
      await proxyLocalSandboxAvatarUpload(
        request(
          {
            host: "learner.localhost:3100",
            "x-forwarded-host": "learner.localhost:3100",
            "x-forwarded-proto": "http",
          },
          "http://127.0.0.1:3100" + path,
        ),
      )
    ).status,
  ).toBe(204);
});
it.each([
  path + "&subject=other",
  path.replace("original", "original%2Favatar%2F512"),
  path.replace("avatar%2F", "video%2F"),
  path.replace("%2F", "%2f"),
])("rejects noncanonical or broadened object routes", async (candidate) => {
  expect(
    (await proxyLocalSandboxAvatarUpload(request({}, origin + candidate)))
      .status,
  ).toBe(403);
  expect(wire.request).not.toHaveBeenCalled();
});
it.each([
  ["production", "true", "", 404],
  ["development", "false", "", 404],
  ["development", "true", "net", 503],
])(
  "fails closed outside opted-in private native runtime",
  async (mode, enabled, debug, status) => {
    vi.stubEnv("NODE_ENV", String(mode));
    vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", String(enabled));
    vi.stubEnv("NODE_DEBUG", String(debug));
    expect((await proxyLocalSandboxAvatarUpload(request())).status).toBe(
      status,
    );
    expect(wire.request).not.toHaveBeenCalled();
  },
);
it("refuses configured nonexact API or staging bridge mode", async () => {
  vi.stubEnv("AC_DEV_API_ORIGIN", "http://localhost:8000");
  expect((await proxyLocalSandboxAvatarUpload(request())).status).toBe(403);
  vi.stubEnv("AC_DEV_API_ORIGIN", "http://127.0.0.1:8000");
  vi.stubEnv("AC_DEV_AUTH_BRIDGE_ENABLED", "true");
  expect((await proxyLocalSandboxAvatarUpload(request())).status).toBe(403);
  expect(wire.request).not.toHaveBeenCalled();
});
it.each([
  ["short", 400],
  [body + "excess", 413],
])("rejects observed byte-length mismatch", async (data, status) => {
  expect(
    (await proxyLocalSandboxAvatarUpload(request({}, undefined, data))).status,
  ).toBe(status);
  expect(wire.request).not.toHaveBeenCalled();
});
it("checks actual checksum before sending", async () => {
  expect(
    (
      await proxyLocalSandboxAvatarUpload(
        request({ "x-content-sha256": "0".repeat(64) }),
      )
    ).status,
  ).toBe(400);
  expect(wire.request).not.toHaveBeenCalled();
});
it.each([302, 500, 200])(
  "does not accept or forward upstream response %s",
  async (status) => {
    response.statusCode = status;
    const result = await proxyLocalSandboxAvatarUpload(request());
    expect(result.status).toBe(502);
    expect(await result.text()).not.toContain("token");
    expect(response.destroy).toHaveBeenCalled();
  },
);
it("sanitizes upstream denial", async () => {
  response.statusCode = 403;
  expect((await proxyLocalSandboxAvatarUpload(request())).status).toBe(403);
});
it("cancels a stalled body with an independent deadline", async () => {
  vi.useFakeTimers();
  const cancelled = vi.fn();
  const stream = new ReadableStream({ pull() {}, cancel: cancelled });
  const pending = proxyLocalSandboxAvatarUpload(
    new Request(origin + path, {
      method: "PUT",
      headers: request().headers,
      body: stream,
      duplex: "half",
    } as RequestInit),
  );
  await vi.advanceTimersByTimeAsync(30_000);
  expect((await pending).status).toBe(504);
  expect(cancelled).toHaveBeenCalled();
  expect(wire.request).not.toHaveBeenCalled();
});
it("cancels a stalled upstream without diagnostics", async () => {
  wire.request.mockImplementation(() => upstream);
  const pending = proxyLocalSandboxAvatarUpload(request());
  await vi.waitFor(() => expect(upstream.setTimeout).toHaveBeenCalled());
  upstream.setTimeout.mock.calls[0][1]();
  expect((await pending).status).toBe(504);
  expect(upstream.destroy).toHaveBeenCalled();
});
it("client credential opt-in applies only to exact local upload URLs", () => {
  expect(isLocalSandboxAvatarUploadUrl(new URL(origin + path), origin)).toBe(
    true,
  );
  expect(
    isLocalSandboxAvatarUploadUrl(
      new URL(origin + path),
      "https://remote.example",
    ),
  ).toBe(false);
  expect(
    isLocalSandboxAvatarUploadUrl(
      new URL("https://remote.example" + path),
      origin,
    ),
  ).toBe(false);
  expect(
    isLocalSandboxAvatarUploadUrl(new URL(origin + path + "&extra=1"), origin),
  ).toBe(false);
  vi.stubEnv("NODE_ENV", "production");
  expect(isLocalSandboxAvatarUploadUrl(new URL(origin + path), origin)).toBe(
    false,
  );
});
