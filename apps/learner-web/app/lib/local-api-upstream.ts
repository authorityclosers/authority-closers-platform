import { request as httpRequest } from "node:http";

import { assertDevelopmentMediaNativePrivacy } from "./dev-media-native-privacy";

const MAX_RESPONSE_BYTES = 8 * 1024 * 1024;
const LOCAL_API_HOST = "learner.localhost:8000";

/**
 * Send the learner's local API request over a numeric loopback socket.
 *
 * Node's fetch does not reliably resolve the package-owned `*.localhost`
 * names on every development host. The API still receives the exact learner
 * Host header, while the socket destination remains the fixed local API.
 * Callers own route admission, request-body bounds, and the abort deadline.
 */
export async function fetchLocalLearnerWire(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  assertDevelopmentMediaNativePrivacy();
  const url = new URL(String(input));
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    url.port !== "8000" ||
    url.hash !== "" ||
    !url.pathname.startsWith("/v1/") ||
    url.username ||
    url.password
  ) {
    throw new Error(
      "Local learner transport requires an uncredentialed numeric HTTP loopback URL on port 8000 under /v1/.",
    );
  }
  if (init?.body != null && !(init.body instanceof ArrayBuffer)) {
    throw new Error(
      "Local learner transport accepts only a bounded ArrayBuffer body.",
    );
  }

  const headers = new Headers(init?.headers);
  for (const name of [
    "connection",
    "content-length",
    "forwarded",
    "host",
    "transfer-encoding",
    "x-forwarded-host",
    "x-forwarded-port",
    "x-forwarded-proto",
  ]) {
    headers.delete(name);
  }
  headers.set("host", LOCAL_API_HOST);
  // The native client does not transparently decode compressed responses, and
  // the proxy deliberately removes content-encoding at its response boundary.
  headers.set("accept-encoding", "identity");

  return new Promise<Response>((resolve, reject) => {
    if (init?.signal?.aborted) {
      reject(init.signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const request = httpRequest(
      url,
      {
        method: init?.method ?? "GET",
        headers: Object.fromEntries(headers),
        agent: false,
        maxHeaderSize: 16 * 1024,
        signal: init?.signal ?? undefined,
      },
      (incoming) => {
        const chunks: Buffer[] = [];
        let size = 0;
        incoming.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > MAX_RESPONSE_BYTES) {
            incoming.destroy(
              new Error("Local learner response exceeded the bounded limit."),
            );
            return;
          }
          chunks.push(chunk);
        });
        incoming.on("error", reject);
        incoming.on("end", () => {
          const responseHeaders = new Headers();
          for (let index = 0; index < incoming.rawHeaders.length; index += 2) {
            const name = incoming.rawHeaders[index];
            if (
              ["connection", "transfer-encoding", "content-length"].includes(
                name.toLowerCase(),
              )
            ) {
              continue;
            }
            responseHeaders.append(name, incoming.rawHeaders[index + 1]);
          }
          responseHeaders.set("cache-control", "private, no-store");
          responseHeaders.set("x-ac-dev-data-mode", "local-learner-sandbox");
          const status = incoming.statusCode ?? 502;
          const body =
            [204, 205, 304].includes(status) || init?.method === "HEAD"
              ? null
              : new Uint8Array(Buffer.concat(chunks));
          resolve(new Response(body, { status, headers: responseHeaders }));
        });
      },
    );
    request.on("error", reject);
    request.end(
      init?.body instanceof ArrayBuffer ? Buffer.from(init.body) : undefined,
    );
  });
}
