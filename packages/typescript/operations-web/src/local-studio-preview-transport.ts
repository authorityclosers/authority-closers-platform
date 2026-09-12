import { request as httpRequest } from "node:http";
import { assertLocalAdminNativePrivacy } from "./local-admin-transport";

const id =
  "[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const route = new RegExp(
  `^/v1/admin/studio/programs/${id}/videos/${id}/versions/${id}/preview(/bytes)?$`,
  "i",
);

export function studioPreviewRequestKind(
  url: URL,
  method: string,
): "descriptor" | "bytes" | null {
  const match = route.exec(url.pathname);
  if (!match || url.search || url.hash || !["GET", "HEAD"].includes(method))
    return null;
  return match[1] ? "bytes" : method === "GET" ? "descriptor" : null;
}

/** The local JSON transport buffers 8 MiB; preview bytes must stream instead. */
export async function fetchLocalStudioPreviewWire(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  assertLocalAdminNativePrivacy();
  const url = new URL(String(input));
  const headers = new Headers(init?.headers);
  const origin = headers.get("origin");
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    url.port !== "8000" ||
    url.username ||
    url.password ||
    studioPreviewRequestKind(url, init?.method ?? "GET") !== "bytes" ||
    init?.body != null ||
    !["http://coach.localhost:3102", "http://admin.localhost:3101"].includes(
      origin ?? "",
    )
  ) {
    throw new Error(
      "Preview transport requires its exact local workspace route.",
    );
  }
  // Keep the socket destination numeric: Windows does not resolve *.localhost
  // for Node even though Chromium does. Native HTTP preserves the trusted Host
  // without resolving a browser hostname or following a redirect.
  for (const name of [
    "host",
    "forwarded",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
  ])
    headers.delete(name);
  headers.set("host", new URL(origin!).host);
  const controller = new AbortController();
  const abort = () => controller.abort(init?.signal?.reason);
  init?.signal?.addEventListener("abort", abort, { once: true });
  if (init?.signal?.aborted) abort();
  const timer = setTimeout(() => controller.abort(), 300_000);
  const headerTimer = setTimeout(() => controller.abort(), 12_000);
  const cleanup = () => {
    clearTimeout(timer);
    clearTimeout(headerTimer);
    init?.signal?.removeEventListener("abort", abort);
  };
  try {
    const response = await new Promise<Response>((resolve, reject) => {
      const outgoing = httpRequest(
        url,
        {
          method: init?.method ?? "GET",
          headers: Object.fromEntries(headers),
          signal: controller.signal,
        },
        (incoming) => {
          incoming.on("error", reject);
          const status = incoming.statusCode ?? 502;
          if (status >= 300 && status < 400) {
            incoming.destroy();
            reject(new Error("Preview transport does not follow redirects."));
            return;
          }
          const receivedHeaders = new Headers();
          for (let index = 0; index < incoming.rawHeaders.length; index += 2) {
            receivedHeaders.append(
              incoming.rawHeaders[index],
              incoming.rawHeaders[index + 1],
            );
          }
          try {
            if (init?.method === "HEAD" || [204, 205, 304].includes(status)) {
              incoming.resume();
              resolve(new Response(null, { status, headers: receivedHeaders }));
            } else {
              const iterator = incoming[Symbol.asyncIterator]();
              let cancelled = false;
              const source = new ReadableStream<Uint8Array>({
                async pull(stream) {
                  try {
                    const chunk = await iterator.next();
                    if (cancelled) return;
                    if (chunk.done) stream.close();
                    else stream.enqueue(new Uint8Array(chunk.value));
                  } catch (failure) {
                    if (!cancelled) stream.error(failure);
                  }
                },
                async cancel() {
                  cancelled = true;
                  incoming.destroy();
                  await iterator.return?.().catch(() => {});
                },
              });
              resolve(
                new Response(source, {
                  status,
                  headers: receivedHeaders,
                }),
              );
            }
          } catch (failure) {
            incoming.destroy();
            reject(failure);
          }
        },
      );
      outgoing.on("error", reject);
      outgoing.end();
    });
    clearTimeout(headerTimer);
    const allowed = new Headers({
      "cache-control": "private, no-store",
      "x-content-type-options": "nosniff",
    });
    for (const name of [
      "content-type",
      "content-length",
      "content-range",
      "accept-ranges",
    ])
      if (response.headers.has(name))
        allowed.set(name, response.headers.get(name)!);
    const media = [200, 206].includes(response.status);
    const length = Number(response.headers.get("content-length"));
    if (
      media &&
      (response.headers.get("content-type")?.split(";", 1)[0] !== "video/mp4" ||
        !Number.isSafeInteger(length) ||
        length < 1 ||
        length > 8 * 1024 ** 3)
    ) {
      controller.abort();
      await response.body?.cancel();
      throw new Error("Invalid preview byte response.");
    }
    if (init?.method === "HEAD" || !response.body) {
      await response.body?.cancel();
      cleanup();
      return new Response(null, { status: response.status, headers: allowed });
    }
    const reader = response.body.getReader();
    const limit = media ? length : 64 * 1024;
    let received = 0;
    const body = new ReadableStream<Uint8Array>({
      async pull(stream) {
        try {
          const result = await reader.read();
          if (result.done) {
            if (media && received !== length)
              throw new Error("Truncated preview response.");
            cleanup();
            reader.releaseLock();
            stream.close();
            return;
          }
          received += result.value.byteLength;
          if (received > limit)
            throw new Error("Preview response exceeded its byte bound.");
          stream.enqueue(result.value);
        } catch (failure) {
          cleanup();
          controller.abort();
          await reader.cancel().catch(() => {});
          stream.error(failure);
        }
      },
      async cancel(reason) {
        cleanup();
        controller.abort(reason);
        await reader.cancel(reason).catch(() => {});
      },
    });
    return new Response(body, { status: response.status, headers: allowed });
  } catch (failure) {
    cleanup();
    controller.abort();
    throw failure;
  }
}
