import { afterEach, expect, it, vi } from "vitest";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import {
  request as nativeRequest,
  type ClientRequest,
  type IncomingMessage,
  type RequestOptions,
} from "node:http";
import {
  isStagingAdminRequest,
  isCoachApiRequest,
  proxyDevelopmentAdminApi,
} from "./dev-api-proxy";
import {
  fetchLocalStudioPreviewWire,
  studioPreviewRequestKind,
} from "../../../../packages/typescript/operations-web/src/local-studio-preview-transport";

vi.mock("node:http", async () => ({
  ...(await vi.importActual("node:http")),
  request: vi.fn(),
}));

function nativeResponse(
  body: string | null,
  headers: Record<string, string>,
  status = 200,
) {
  const source = new PassThrough();
  const incoming = source as unknown as IncomingMessage;
  Object.assign(incoming, {
    statusCode: status,
    rawHeaders: Object.entries(headers).flat(),
  });
  const outgoing = new EventEmitter() as ClientRequest;
  const ended = vi.fn();
  let sentOptions: RequestOptions | undefined;
  vi.mocked(nativeRequest).mockImplementation(((
    input: URL,
    options: RequestOptions,
    callback: (message: IncomingMessage) => void,
  ) => {
    sentOptions = options;
    options.signal?.addEventListener(
      "abort",
      () => {
        incoming.destroy();
        outgoing.emit("error", new Error("Aborted"));
      },
      { once: true },
    );
    outgoing.end = (() => {
      ended();
      queueMicrotask(() => {
        callback(incoming);
        if (body !== null) source.end(body);
      });
      return outgoing;
    }) as ClientRequest["end"];
    return outgoing;
  }) as typeof nativeRequest);
  return { incoming, ended, options: () => sentOptions };
}

const origin = "http://coach.localhost:3102";
const id = "11111111-1111-4111-8111-111111111111";
const path = `/v1/admin/studio/programs/${id}/videos/${id}/versions/${id}/preview`;
const environment = {
  AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
  AC_DEV_ADMIN_API_ORIGIN: "http://127.0.0.1:8000",
  AC_DEV_OPERATIONS_SURFACE: "coach",
  AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: origin,
  AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED: "true",
};
const request = (suffix = "/bytes", init: RequestInit = {}) =>
  new Request(origin + path + suffix, {
    ...init,
    headers: { origin, ...init.headers },
  });
afterEach(() => {
  vi.mocked(nativeRequest).mockReset();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it("keeps preview out of both remote staging bridges", () => {
  for (const check of [isStagingAdminRequest, isCoachApiRequest])
    for (const suffix of ["", "/bytes"])
      expect(check(new URL(origin + path + suffix), "GET")).toBe(false);
});
it.each(["?tenant=x", "/bytes?key=x", "/bytes/", "/bytes#fragment", "/source"])(
  "rejects path/scope variations %s",
  (suffix) => {
    expect(
      studioPreviewRequestKind(new URL(origin + path + suffix), "GET"),
    ).toBeNull();
  },
);
it.each(["POST", "PUT", "PATCH", "DELETE"])(
  "rejects preview mutation %s",
  (method) => {
    expect(
      studioPreviewRequestKind(new URL(origin + path + "/bytes"), method),
    ).toBeNull();
  },
);
it("forwards only the exact preview and selected session, range and workspace", async () => {
  const fetcher = vi.fn<typeof fetch>(
    async () => new Response("abcd", { status: 206 }),
  );
  const result = await proxyDevelopmentAdminApi(
    request("/bytes", {
      headers: {
        range: "bytes=0-3",
        cookie: "ac_session=local-session; unrelated=private",
      },
    }),
    fetcher,
    environment,
    "development",
  );
  expect(result.status).toBe(206);
  expect(await result.text()).toBe("abcd");
  expect(String(fetcher.mock.calls[0][0])).toBe(
    `http://127.0.0.1:8000${path}/bytes`,
  );
  const headers = new Headers(fetcher.mock.calls[0][1]?.headers);
  expect(headers.get("cookie")).toBe("ac_session=local-session");
  expect(headers.get("range")).toBe("bytes=0-3");
  expect(headers.get("origin")).toBe(origin);
});
it("allows descriptor authority checks but blocks bytes when pipeline is disabled", async () => {
  const fetcher = vi.fn(async () => new Response(null, { status: 503 }));
  const disabled = {
    ...environment,
    AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED: "false",
  };
  expect(
    (
      await proxyDevelopmentAdminApi(
        request(""),
        fetcher,
        disabled,
        "development",
      )
    ).status,
  ).toBe(503);
  expect(fetcher).toHaveBeenCalledOnce();
  expect(
    (
      await proxyDevelopmentAdminApi(
        request(),
        fetcher,
        disabled,
        "development",
      )
    ).status,
  ).toBe(503);
  expect(fetcher).toHaveBeenCalledOnce();
});
it.each(["bytes=0-1,4-5", "bytes=-100", "garbage"])(
  "rejects unsupported Range %s before transport",
  async (range) => {
    const fetcher = vi.fn();
    expect(
      (
        await proxyDevelopmentAdminApi(
          request("/bytes", { headers: { range } }),
          fetcher,
          environment,
          "development",
        )
      ).status,
    ).toBe(416);
    expect(fetcher).not.toHaveBeenCalled();
  },
);
it.each<Record<string, string>>([
  { authorization: "Bearer invalid" },
  { "content-length": "1" },
  { "content-encoding": "gzip" },
])("rejects credential/body overrides %j", async (headers) => {
  const fetcher = vi.fn();
  expect(
    (
      await proxyDevelopmentAdminApi(
        request("/bytes", { headers }),
        fetcher,
        environment,
        "development",
      )
    ).status,
  ).toBe(400);
  expect(fetcher).not.toHaveBeenCalled();
});
it("streams the native preview response without JSON buffering or cookie leakage", async () => {
  nativeResponse(
    "abcd",
    {
      "content-type": "video/mp4",
      "content-length": "4",
      "content-range": "bytes 0-3/100",
      "set-cookie": "forbidden",
      location: "https://external.test/",
    },
    206,
  );
  const result = await fetchLocalStudioPreviewWire(
    `http://127.0.0.1:8000${path}/bytes`,
    { headers: { origin, host: "malicious", "x-forwarded-host": "malicious" } },
  );
  expect(String(vi.mocked(nativeRequest).mock.calls[0][0])).toBe(
    `http://127.0.0.1:8000${path}/bytes`,
  );
  const sent = new Headers(
    (vi.mocked(nativeRequest).mock.calls[0][1] as RequestOptions)
      .headers as Record<string, string>,
  );
  expect(sent.get("host")).toBe("coach.localhost:3102");
  expect(sent.has("x-forwarded-host")).toBe(false);
  expect(result.headers.get("cache-control")).toBe("private, no-store");
  expect(result.headers.has("set-cookie")).toBe(false);
  expect(result.headers.has("location")).toBe(false);
  expect(await result.text()).toBe("abcd");
});
it.each([
  "https://127.0.0.1:8000",
  "http://example.test:8000",
  "http://127.0.0.1:9000",
])("rejects noncanonical native transport %s", async (base) => {
  await expect(
    fetchLocalStudioPreviewWire(base + path + "/bytes", {
      headers: { origin },
    }),
  ).rejects.toThrow();
});
it("cancels upstream when the consumer closes playback", async () => {
  const transport = nativeResponse(null, {
    "content-type": "video/mp4",
    "content-length": "10",
  });
  const result = await fetchLocalStudioPreviewWire(
    `http://127.0.0.1:8000${path}/bytes`,
    { headers: { origin } },
  );
  await result.body!.cancel();
  expect(transport.options()?.signal?.aborted).toBe(true);
  expect(transport.incoming.destroyed).toBe(true);
});
it("rejects successful non-video responses", async () => {
  nativeResponse("html", {
    "content-type": "text/html",
    "content-length": "4",
  });
  await expect(
    fetchLocalStudioPreviewWire(`http://127.0.0.1:8000${path}/bytes`, {
      headers: { origin },
    }),
  ).rejects.toThrow();
});

it("never follows native redirects", async () => {
  const transport = nativeResponse(
    "",
    { location: "https://external.test/" },
    302,
  );
  await expect(
    fetchLocalStudioPreviewWire(`http://127.0.0.1:8000${path}/bytes`, {
      headers: { origin },
    }),
  ).rejects.toThrow("does not follow redirects");
  expect(transport.incoming.destroyed).toBe(true);
  expect(nativeRequest).toHaveBeenCalledOnce();
});
