import { request as httpRequest, type ClientRequest } from "node:http";
import { createHash } from "node:crypto";
import { assertDevelopmentMediaNativePrivacy } from "./dev-media-native-privacy";
import {
  isLocalAvatarObjectUrl,
  MAX_LOCAL_AVATAR_BYTES,
} from "./local-avatar-url";
import { LOCAL_SANDBOX_ORIGIN } from "./local-sandbox";

const deny = (status: number) =>
  Response.json(
    { detail: "Local profile image upload is unavailable. Try again." },
    { status, headers: { "cache-control": "no-store" } },
  );

/** Exact local transport only; canonical API intent, checksum and ownership remain authoritative. */
export async function proxyLocalSandboxAvatarUpload(
  request: Request,
): Promise<Response> {
  if (
    process.env.NODE_ENV !== "development" ||
    process.env.AC_DEV_LOCAL_SANDBOX_ENABLED !== "true"
  )
    return deny(404);
  try {
    assertDevelopmentMediaNativePrivacy();
  } catch {
    return deny(503);
  }
  if (
    (process.env.AC_DEV_API_ORIGIN ??
      process.env.AC_API_URL ??
      "http://127.0.0.1:8000") !== "http://127.0.0.1:8000" ||
    process.env.AC_DEV_AUTH_BRIDGE_ENABLED === "true"
  )
    return deny(403);
  const url = new URL(request.url);
  const host = "learner.localhost:3100";
  const requestHost = request.headers.get("host");
  const localOrigin =
    (url.origin === LOCAL_SANDBOX_ORIGIN &&
      (requestHost === null || requestHost === host)) ||
    (["http://127.0.0.1:3100", "http://localhost:3100"].includes(url.origin) &&
      requestHost === host);
  const cookies = (request.headers.get("cookie") ?? "")
    .split(";")
    .map((value) => value.trim())
    .filter((value) => value.startsWith("ac_session="));
  const type = request.headers.get("content-type");
  const rawLength = request.headers.get("content-length") ?? "";
  const length = Number(rawLength);
  const checksum = request.headers.get("x-content-sha256") ?? "";
  if (
    !localOrigin ||
    request.method !== "PUT" ||
    !isLocalAvatarObjectUrl(url, "upload") ||
    request.headers.get("origin") !== LOCAL_SANDBOX_ORIGIN ||
    request.headers.get("sec-fetch-site") === "cross-site" ||
    (request.headers.has("x-forwarded-host") &&
      request.headers.get("x-forwarded-host") !== host) ||
    (request.headers.has("x-forwarded-proto") &&
      request.headers.get("x-forwarded-proto") !== "http") ||
    cookies.length !== 1 ||
    !/^ac_session=[A-Za-z0-9_-]{43,512}$/.test(cookies[0]) ||
    !["image/jpeg", "image/png", "image/webp"].includes(type ?? "") ||
    request.headers.has("content-encoding") ||
    !/^[1-9]\d*$/.test(rawLength) ||
    !Number.isSafeInteger(length) ||
    length > MAX_LOCAL_AVATAR_BYTES ||
    !/^[0-9a-f]{64}$/.test(checksum)
  )
    return deny(403);

  const reader = request.body?.getReader();
  if (!reader) return deny(400);
  let aborted = false;
  const abortRead = () => {
    aborted = true;
    void reader.cancel().catch(() => undefined);
  };
  const deadline = setTimeout(abortRead, 30_000);
  request.signal.addEventListener("abort", abortRead, { once: true });
  const chunks: Uint8Array[] = [];
  let observed = 0;
  try {
    if (request.signal.aborted) abortRead();
    while (!aborted) {
      const chunk = await reader.read();
      if (chunk.done) break;
      observed += chunk.value.byteLength;
      if (observed > length || observed > MAX_LOCAL_AVATAR_BYTES) {
        await reader.cancel();
        return deny(413);
      }
      chunks.push(chunk.value);
    }
    if (aborted) return deny(504);
    if (observed !== length) return deny(400);
  } catch {
    return deny(aborted ? 504 : 400);
  } finally {
    clearTimeout(deadline);
    request.signal.removeEventListener("abort", abortRead);
    reader.releaseLock();
  }
  const body = Buffer.concat(chunks, length);
  if (createHash("sha256").update(body).digest("hex") !== checksum)
    return deny(400);
  try {
    assertDevelopmentMediaNativePrivacy();
  } catch {
    return deny(503);
  }

  return new Promise<Response>((resolve) => {
    let upstream: ClientRequest | undefined;
    let done = false;
    const finish = (status: number) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      request.signal.removeEventListener("abort", abort);
      upstream?.destroy();
      resolve(
        status === 204
          ? new Response(null, {
              status,
              headers: { "cache-control": "no-store" },
            })
          : deny(status),
      );
    };
    const abort = () => finish(504);
    const timer = setTimeout(abort, 30_000);
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
          method: "PUT",
          path: url.pathname + url.search,
          headers: {
            origin: LOCAL_SANDBOX_ORIGIN,
            cookie: cookies[0],
            "content-type": type!,
            "content-length": String(body.byteLength),
            "x-content-sha256": checksum,
            "accept-encoding": "identity",
          },
        },
        (response) => {
          response.on("error", () => finish(502));
          const status = response.statusCode ?? 502;
          // Never copy diagnostic bodies, redirects, cookies or headers from upload responses.
          response.destroy();
          finish(
            [204, 400, 401, 403, 404, 409, 410, 413, 422, 503].includes(status)
              ? status
              : 502,
          );
        },
      );
      upstream.once("error", () => finish(502));
      upstream.setTimeout(30_000, abort);
      if (request.signal.aborted) abort();
      else upstream.end(body);
    } catch {
      finish(502);
    }
  });
}
