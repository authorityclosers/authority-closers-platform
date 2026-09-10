// @vitest-environment node
import { EventEmitter } from "node:events";
import { PassThrough, Readable } from "node:stream";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const wire = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("node:http", () => ({ request: wire.request }));
import { proxyLocalSandboxMedia } from "./local-media-upstream";

const origin = "http://learner.localhost:3100";
const path = `/v1/media/playback/${encodeURIComponent("tenants/t/media/video/a/v/original.mp4")}?token=AC-MEDIA.fixture.${"s".repeat(43)}`;
const cookie = `ac_session=${"c".repeat(43)}`;
let request: EventEmitter & {
  end: ReturnType<typeof vi.fn>;
  destroy: ReturnType<typeof vi.fn>;
  setTimeout: ReturnType<typeof vi.fn>;
};
let response: PassThrough & {
  statusCode: number;
  headers: Record<string, string>;
};

beforeEach(() => {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AC_DEV_LOCAL_SANDBOX_ENABLED", "true");
  vi.stubEnv("NODE_DEBUG", "");
  response = Object.assign(new PassThrough(), {
    statusCode: 206,
    headers: {
      "content-type": "video/mp4",
      "content-length": "4",
      "content-range": "bytes 0-3/4",
    },
  });
  request = Object.assign(new EventEmitter(), {
    end: vi.fn(),
    destroy: vi.fn(),
    setTimeout: vi.fn(),
  });
  wire.request.mockReset().mockImplementation((_options, callback) => {
    request.end.mockImplementation(() => {
      callback(response);
      response.end("film");
    });
    return request;
  });
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("streams the exact cookie/range to fixed loopback without Next fetch", async () => {
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie, range: "bytes=0-3" } }),
  );
  expect(result.status).toBe(206);
  expect(await result.text()).toBe("film");
  expect(result.headers.get("cache-control")).toBe("private, no-store");
  expect(wire.request.mock.calls[0][0]).toMatchObject({
    hostname: "127.0.0.1",
    port: 8000,
    path,
    headers: { cookie, range: "bytes=0-3" },
  });
});
it.each([
  [origin + path, {}],
  [origin + path, { cookie: cookie + "; " + cookie }],
  [origin + path, { cookie, origin: "https://remote.example" }],
  [origin + path, { cookie, "sec-fetch-site": "cross-site" }],
  ["http://evil.example" + path, { cookie }],
  [origin + path + "&other=1", { cookie }],
  [origin + path, { cookie, host: "evil.example" }],
  [origin + path, { cookie, "x-forwarded-host": "evil.example" }],
  [origin + path, { cookie, "x-forwarded-proto": "https" }],
  ["http://127.0.0.1:3100" + path, { cookie }],
  ["http://127.0.0.1:3101" + path, { cookie, host: "learner.localhost:3100" }],
])(
  "refuses invalid source or session envelope before transport",
  async (url, headers) => {
    const result = await proxyLocalSandboxMedia(
      new Request(url as string, { headers: headers as HeadersInit }),
    );
    expect(result.status).toBe(403);
    expect(wire.request).not.toHaveBeenCalled();
  },
);
it.each(["http://127.0.0.1:3100", "http://localhost:3100"])(
  "accepts Next's exact bind-origin %s only with the exact browser Host",
  async (bindOrigin) => {
    const result = await proxyLocalSandboxMedia(
      new Request(bindOrigin + path, {
        headers: {
          cookie,
          host: "learner.localhost:3100",
          "x-forwarded-host": "learner.localhost:3100",
          "x-forwarded-proto": "http",
        },
      }),
    );
    expect(result.status).toBe(206);
    expect(await result.text()).toBe("film");
  },
);
it("never enables in production and refuses native HTTP diagnostics", async () => {
  vi.stubEnv("NODE_ENV", "production");
  expect(
    (await proxyLocalSandboxMedia(new Request(origin + path))).status,
  ).toBe(404);
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("NODE_DEBUG", "http");
  expect(
    (await proxyLocalSandboxMedia(new Request(origin + path))).status,
  ).toBe(503);
  expect(wire.request).not.toHaveBeenCalled();
});
it("does not forward redirects or oversized payloads", async () => {
  response.statusCode = 302;
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  expect(result.status).toBe(502);
  expect(await result.text()).not.toContain("token");
});

it.each([
  ["content-length", "134217729"],
  ["content-length", ""],
  ["content-length", "-1"],
  ["content-type", "text/html"],
  ["content-encoding", "gzip"],
])("rejects invalid bounded response metadata %s", async (name, value) => {
  response.headers[name] = value;
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  expect(result.status).toBe(502);
  expect(response.destroyed).toBe(true);
});

it("uses a byte-sized 64KiB queue and no pooled upstream connection", async () => {
  const toWeb = vi.spyOn(Readable, "toWeb");
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  expect(await result.text()).toBe("film");
  const strategy = toWeb.mock.calls[0][1]?.strategy;
  expect(strategy?.highWaterMark).toBe(64 * 1024);
  expect(strategy?.size?.(new Uint8Array(37))).toBe(37);
  expect(wire.request.mock.calls[0][0]).toMatchObject({
    agent: false,
    maxHeaderSize: 16 * 1024,
  });
});

it("stops upstream on consumer cancellation", async () => {
  wire.request.mockImplementation((_options, callback) => {
    request.end.mockImplementation(() => callback(response));
    return request;
  });
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  await result.body!.cancel();
  expect(response.destroyed).toBe(true);
  expect(request.destroy).toHaveBeenCalled();
});

it("sanitizes errors after headers instead of propagating native details", async () => {
  wire.request.mockImplementation((_options, callback) => {
    request.end.mockImplementation(() => callback(response));
    return request;
  });
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  const read = result.text();
  response.destroy(new Error("SYNTHETIC_PRIVATE_TOKEN_MUST_NOT_ESCAPE"));
  await expect(read).rejects.toThrow(
    "Local media stream unavailable or cancelled.",
  );
  expect(request.destroy).toHaveBeenCalled();
});

it("refuses truncated bodies without returning success", async () => {
  response.headers["content-length"] = "12";
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  await expect(result.text()).rejects.toThrow(
    "Local media stream unavailable or cancelled.",
  );
});

it("does not forward upstream error bodies", async () => {
  response.statusCode = 403;
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  expect(result.status).toBe(403);
  expect(await result.text()).not.toContain("film");
  expect(response.destroyed).toBe(true);
});

it("ends HEAD without allocating or reading a streaming body", async () => {
  const toWeb = vi.spyOn(Readable, "toWeb");
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, { method: "HEAD", headers: { cookie } }),
  );
  expect(result.body).toBeNull();
  expect(toWeb).not.toHaveBeenCalled();
  expect(request.destroy).toHaveBeenCalled();
});

it("rejects an already cancelled request before creating transport", async () => {
  const controller = new AbortController();
  controller.abort();
  const result = await proxyLocalSandboxMedia(
    new Request(origin + path, {
      headers: { cookie },
      signal: controller.signal,
    }),
  );
  expect(result.status).toBe(504);
  expect(wire.request).not.toHaveBeenCalled();
});

it("times out a header stall and cancels the native request", async () => {
  wire.request.mockImplementation(() => request);
  const pending = proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  expect(request.setTimeout.mock.calls[0][0]).toBe(30_000);
  request.setTimeout.mock.calls[0][1]();
  expect((await pending).status).toBe(504);
  expect(request.destroy).toHaveBeenCalled();
});

it("has an independent total transfer deadline", async () => {
  vi.useFakeTimers();
  wire.request.mockImplementation(() => request);
  const pending = proxyLocalSandboxMedia(
    new Request(origin + path, { headers: { cookie } }),
  );
  await vi.advanceTimersByTimeAsync(120_000);
  expect((await pending).status).toBe(504);
  expect(request.destroy).toHaveBeenCalled();
});

const avatarId = "11111111-1111-4111-8111-111111111111";
const avatarPath = `/v1/media/read/${encodeURIComponent(`tenants/${avatarId}/media/avatar/${avatarId}/${avatarId}/original/avatar/512`)}?token=AC-MEDIA.fixture.${"s".repeat(43)}`;
it.each(["GET", "HEAD"])(
  "serves authenticated bounded WebP avatar %s using private native transport",
  async (method) => {
    response.statusCode = 200;
    response.headers["content-type"] = "image/webp";
    const result = await proxyLocalSandboxMedia(
      new Request(origin + avatarPath, { method, headers: { cookie } }),
    );
    expect(result.status).toBe(200);
    expect(result.headers.get("cache-control")).toBe("private, no-store");
    expect(wire.request.mock.calls[0][0].path).toBe(avatarPath);
    if (method === "GET") expect(await result.text()).toBe("film");
    else expect(result.body).toBeNull();
  },
);
it.each([
  ["content-type", "video/mp4"],
  ["content-type", "image/svg+xml"],
  ["content-length", "5242881"],
])("rejects non-avatar delivery metadata", async (name, value) => {
  response.headers["content-type"] = "image/webp";
  response.headers[name] = value;
  expect(
    (
      await proxyLocalSandboxMedia(
        new Request(origin + avatarPath, { headers: { cookie } }),
      )
    ).status,
  ).toBe(502);
});
it("never broadens generic private-media read or allows original avatar uploads as delivery", async () => {
  for (const candidate of [
    avatarPath.replace("avatar%2F", "video%2F"),
    avatarPath.replace("%2Favatar%2F512", ""),
  ]) {
    expect(
      (
        await proxyLocalSandboxMedia(
          new Request(origin + candidate, { headers: { cookie } }),
        )
      ).status,
    ).toBe(403);
  }
  expect(wire.request).not.toHaveBeenCalled();
});
