import {
  request as httpRequest,
  type ClientRequest,
  type IncomingMessage,
} from "node:http";
import { Readable } from "node:stream";
import { assertDevelopmentMediaNativePrivacy } from "./dev-media-native-privacy";
import { isDevelopmentMediaRange } from "./dev-media-transport";
import { LOCAL_SANDBOX_ORIGIN } from "./local-sandbox";
import {
  isLocalAvatarObjectUrl,
  LOCAL_AVATAR_READ_PREFIX,
  MAX_LOCAL_AVATAR_BYTES,
} from "./local-avatar-url";

const deny = (status: number) =>
  Response.json(
    { detail: "Local media is unavailable. Refresh the lesson and try again." },
    { status, headers: { "cache-control": "no-store" } },
  );

/** Native loopback streaming, outside Next fetch/HMR caches and URL diagnostics. */
export async function proxyLocalSandboxMedia(
  request: Request,
): Promise<Response> {
  try {
    assertDevelopmentMediaNativePrivacy();
  } catch {
    return deny(503);
  }
  if (
    process.env.NODE_ENV !== "development" ||
    process.env.AC_DEV_LOCAL_SANDBOX_ENABLED !== "true"
  )
    return deny(404);
  const incoming = new URL(request.url);
  const expectedHost = "learner.localhost:3100";
  const host = request.headers.get("host");
  // Next's installed Node adapter constructs request.url from its loopback
  // bind address. Require the exact browser Host as well in that case; never
  // trust a forwarded host to turn a remote/unknown request into local access.
  const localRequestOrigin =
    (incoming.origin === LOCAL_SANDBOX_ORIGIN &&
      (host === null || host === expectedHost)) ||
    (["http://127.0.0.1:3100", "http://localhost:3100"].includes(
      incoming.origin,
    ) &&
      host === expectedHost);
  const isAvatar = incoming.pathname.startsWith(LOCAL_AVATAR_READ_PREFIX);
  const prefix = isAvatar ? LOCAL_AVATAR_READ_PREFIX : "/v1/media/playback/";
  const cookie = (request.headers.get("cookie") ?? "")
    .split(";")
    .map((value) => value.trim())
    .filter((value) => value.startsWith("ac_session="));
  let key: string;
  try {
    key = decodeURIComponent(incoming.pathname.slice(prefix.length));
  } catch {
    return deny(400);
  }
  if (
    !localRequestOrigin ||
    (request.headers.has("x-forwarded-host") &&
      request.headers.get("x-forwarded-host") !== expectedHost) ||
    (request.headers.has("x-forwarded-proto") &&
      request.headers.get("x-forwarded-proto") !== "http") ||
    !incoming.pathname.startsWith(prefix) ||
    (isAvatar && !isLocalAvatarObjectUrl(incoming, "read")) ||
    incoming.username ||
    incoming.password ||
    incoming.hash ||
    !["GET", "HEAD"].includes(request.method) ||
    !/^\?token=AC-MEDIA\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/.test(
      incoming.search,
    ) ||
    incoming.search.length > 4103 ||
    key.length > 512 ||
    !key.startsWith("tenants/") ||
    key.includes("..") ||
    key
      .split("/")
      .some((part) => !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(part)) ||
    encodeURIComponent(key) !== incoming.pathname.slice(prefix.length) ||
    cookie.length !== 1 ||
    !/^ac_session=[A-Za-z0-9_-]{43,512}$/.test(cookie[0]) ||
    (request.headers.has("origin") &&
      request.headers.get("origin") !== LOCAL_SANDBOX_ORIGIN) ||
    request.headers.get("sec-fetch-site") === "cross-site" ||
    !isDevelopmentMediaRange(request.headers.get("range"))
  )
    return deny(403);

  return new Promise<Response>((resolve) => {
    let responded = false;
    let finished = false;
    let upstream: ClientRequest | undefined;
    let stream: IncomingMessage | undefined;
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let output: ReadableStreamDefaultController<Uint8Array> | undefined;
    const clean = () => {
      clearTimeout(deadline);
      request.signal.removeEventListener("abort", abort);
    };
    const stop = () => {
      void reader?.cancel().catch(() => undefined);
      stream?.destroy();
      upstream?.destroy();
    };
    const fail = (status: number) => {
      if (finished) return;
      finished = true;
      clean();
      if (responded)
        output?.error(
          new Error("Local media stream unavailable or cancelled."),
        );
      else {
        responded = true;
        resolve(deny(status));
      }
      stop();
    };
    const abort = () => fail(504);
    const deadline = setTimeout(abort, 120_000);
    request.signal.addEventListener("abort", abort, { once: true });
    if (request.signal.aborted) {
      abort();
      return;
    }
    try {
      upstream = httpRequest(
        {
          hostname: "127.0.0.1",
          port: 8000,
          agent: false,
          maxHeaderSize: 16 * 1024,
          path: incoming.pathname + incoming.search,
          method: request.method,
          headers: {
            origin: LOCAL_SANDBOX_ORIGIN,
            cookie: cookie[0],
            "accept-encoding": "identity",
            ...(request.headers.has("range")
              ? { range: request.headers.get("range")! }
              : {}),
          },
        },
        (response) => {
          stream = response;
          if (finished) {
            response.destroy();
            return;
          }
          // Native errors must not cross the boundary into Next diagnostics.
          response.on("error", () => fail(502));
          try {
            const status = response.statusCode ?? 502;
            const rawLength = response.headers["content-length"];
            const length = Number(rawLength);
            if (
              ![200, 206, 400, 401, 403, 404, 410, 416].includes(status) ||
              typeof rawLength !== "string" ||
              !/^(0|[1-9]\d*)$/.test(rawLength) ||
              !Number.isSafeInteger(length) ||
              length < 0 ||
              length > (isAvatar ? MAX_LOCAL_AVATAR_BYTES : 128 * 1024 * 1024)
            ) {
              fail(502);
              return;
            }
            if (status >= 400) {
              // Never forward API error bodies that could contain diagnostics.
              const denied = deny(status);
              const range = response.headers["content-range"];
              if (
                status === 416 &&
                typeof range === "string" &&
                /^bytes \*\/\d+$/.test(range)
              )
                denied.headers.set("content-range", range);
              finished = true;
              clean();
              stop();
              responded = true;
              resolve(
                request.method === "HEAD"
                  ? new Response(null, { status, headers: denied.headers })
                  : denied,
              );
              return;
            }
            const mime = String(response.headers["content-type"] ?? "")
              .split(";", 1)[0]
              .trim()
              .toLowerCase();
            if (
              !(
                isAvatar
                  ? ["image/webp"]
                  : [
                      "video/mp4",
                      "video/mp2t",
                      "text/vtt",
                      "application/vnd.apple.mpegurl",
                      "application/x-mpegurl",
                    ]
              ).includes(mime) ||
              (response.headers["content-encoding"] !== undefined &&
                response.headers["content-encoding"] !== "identity")
            ) {
              fail(502);
              return;
            }
            const headers = new Headers({
              "cache-control": "private, no-store",
              "x-content-type-options": "nosniff",
            });
            for (const name of [
              "content-type",
              "content-length",
              "content-range",
              "accept-ranges",
              "etag",
            ]) {
              const value = response.headers[name];
              if (typeof value === "string") headers.set(name, value);
            }
            if (request.method === "HEAD") {
              finished = true;
              clean();
              stop();
              responded = true;
              resolve(new Response(null, { status, headers }));
              return;
            }
            reader = (
              Readable.toWeb(response, {
                strategy: {
                  highWaterMark: 64 * 1024,
                  size: (chunk: Uint8Array) => chunk.byteLength,
                },
              }) as ReadableStream<Uint8Array>
            ).getReader();
            let observedBytes = 0;
            const body = new ReadableStream<Uint8Array>(
              {
                start(controller) {
                  output = controller;
                },
                async pull(controller) {
                  if (finished) return;
                  try {
                    const item = await reader!.read();
                    if (finished) return;
                    if (item.done) {
                      if (observedBytes !== length) {
                        fail(502);
                        return;
                      }
                      finished = true;
                      clean();
                      reader!.releaseLock();
                      controller.close();
                    } else {
                      observedBytes += item.value.byteLength;
                      if (observedBytes > length) {
                        fail(502);
                        return;
                      }
                      controller.enqueue(item.value);
                    }
                  } catch {
                    fail(502);
                  }
                },
                cancel() {
                  if (finished) return;
                  finished = true;
                  clean();
                  stop();
                },
              },
              { highWaterMark: 0 },
            );
            responded = true;
            resolve(new Response(body, { status, headers }));
          } catch {
            fail(502);
          }
        },
      );
      upstream.once("error", () => fail(502));
      upstream.setTimeout(30_000, abort);
      if (request.signal.aborted) abort();
      else upstream.end();
    } catch {
      fail(502);
    }
  });
}
