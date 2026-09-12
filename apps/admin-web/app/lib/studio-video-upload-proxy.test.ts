import { afterEach, expect, it, vi } from "vitest";
import {
  isCoachApiRequest,
  isStagingAdminRequest,
  proxyDevelopmentAdminApi,
} from "./dev-api-proxy";
const origin = "http://coach.localhost:3102";
const program = "11111111-1111-4111-8111-111111111111";
const upload = "22222222-2222-4222-8222-222222222222";
const prefix = `/v1/admin/studio/programs/${program}`;
const capability = `${prefix}/video-upload-capability`;
const complete = `${prefix}/video-uploads/${upload}/complete`;
const environment = {
  AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
  AC_DEV_ADMIN_API_ORIGIN: "http://127.0.0.1:8000",
  AC_DEV_OPERATIONS_SURFACE: "coach",
  AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: origin,
  AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED: "true",
};
function request(path = complete, init: RequestInit = {}) {
  return new Request(origin + path, {
    method: "POST",
    ...init,
    headers: { origin, "idempotency-key": "same-completion", ...init.headers },
  });
}
afterEach(() => vi.useRealTimers());
it("does not widen either remote staging allowlist", () => {
  for (const predicate of [isCoachApiRequest, isStagingAdminRequest]) {
    expect(predicate(new URL(origin + complete), "POST")).toBe(false);
    expect(predicate(new URL(origin + capability), "GET")).toBe(false);
  }
});
it("forwards only exact enabled same-origin bodyless completion", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(Response.json({ state: "processing" }, { status: 202 }));
  const result = await proxyDevelopmentAdminApi(
    request(),
    fetcher,
    environment,
    "development",
  );
  expect(result.status).toBe(202);
  expect(String(fetcher.mock.calls[0][0])).toBe(
    `http://127.0.0.1:8000${complete}`,
  );
  const headers = new Headers(fetcher.mock.calls[0][1].headers);
  expect(headers.get("host")).toBe("coach.localhost:3102");
  expect(headers.get("idempotency-key")).toBe("same-completion");
});
it.each(["?tenant=x", "/", "/extra"])(
  "rejects completion scope/path suffix %s",
  async (suffix) => {
    const fetcher = vi.fn();
    expect(
      (
        await proxyDevelopmentAdminApi(
          request(complete + suffix),
          fetcher,
          environment,
          "development",
        )
      ).status,
    ).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  },
);
it.each<RequestInit>([
  { body: "{}" },
  { headers: { "idempotency-key": "" } },
  { headers: { "content-encoding": "gzip" } },
  { headers: { authorization: "Bearer forbidden" } },
])("rejects nonempty completion or credential overrides %#", async (init) => {
  const fetcher = vi.fn();
  expect(
    (
      await proxyDevelopmentAdminApi(
        request(complete, init),
        fetcher,
        environment,
        "development",
      )
    ).status,
  ).toBe(400);
  expect(fetcher).not.toHaveBeenCalled();
});
it("disables completion with the local flag off but preserves the fresh authority check on capability", async () => {
  const disabled = {
    ...environment,
    AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED: "false",
  };
  const fetcher = vi.fn().mockResolvedValueOnce(
    Response.json({
      available: true,
      max_source_bytes: 1000,
      accepted_content_types: ["video/mp4", "video/webm"],
      reason: null,
    }),
  );
  expect(
    (
      await proxyDevelopmentAdminApi(
        request(),
        fetcher,
        disabled,
        "development",
      )
    ).status,
  ).toBe(403);
  expect(fetcher).not.toHaveBeenCalled();
  const result = await proxyDevelopmentAdminApi(
    request(capability, { method: "GET" }),
    fetcher,
    disabled,
    "development",
  );
  expect(await result.json()).toMatchObject({
    available: false,
    max_source_bytes: null,
    reason: "not_configured",
  });
  expect(fetcher).toHaveBeenCalledOnce();
  fetcher.mockResolvedValueOnce(new Response(null, { status: 403 }));
  expect(
    (
      await proxyDevelopmentAdminApi(
        request(capability, { method: "GET" }),
        fetcher,
        disabled,
        "development",
      )
    ).status,
  ).toBe(403);
});
it("allows a bounded scan longer than normal JSON calls and cancels at its own deadline", async () => {
  vi.useFakeTimers();
  let upstreamSignal: AbortSignal | undefined;
  const fetcher = vi.fn(
    (_url, init) =>
      new Promise<Response>((_resolve, reject) => {
        upstreamSignal = init.signal;
        init.signal.addEventListener("abort", () =>
          reject(new Error("deadline")),
        );
      }),
  );
  const pending = proxyDevelopmentAdminApi(
    request(),
    fetcher,
    environment,
    "development",
  );
  await vi.advanceTimersByTimeAsync(15_000);
  expect(upstreamSignal?.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(180_000);
  expect((await pending).status).toBe(504);
});
