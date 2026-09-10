// Node-only: this transport keeps the browser-facing .localhost authority in
// the HTTP Host header while bypassing platform DNS for the local API socket.
import { request as httpRequest } from "node:http";
import type { ClientRequest, IncomingMessage } from "node:http";
import { request as httpsRequest } from "node:https";
import type { LookupFunction } from "node:net";
import { Readable } from "node:stream";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
const unavailable = () =>
  new Error("Local API upstream is unavailable or cancelled.");

function isLoopbackHost(hostname: string): boolean {
  return hostname.endsWith(".localhost") || LOOPBACK_HOSTS.has(hostname);
}

function loopbackLookup(
  hostname: string,
  options: Parameters<LookupFunction>[1],
  callback: Parameters<LookupFunction>[2],
): void {
  // The API origin has already been validated by dev-api-proxy. Keep this
  // transport defensive as well: it must never turn into a general DNS
  // proxy if called independently or after a future refactor.
  if (!isLoopbackHost(hostname)) {
    callback(
      Object.assign(new Error("Only loopback API hosts are supported."), {
        code: "ENOTFOUND",
      }),
      "",
      0,
    );
    return;
  }

  const address =
    hostname === "[::1]" || hostname === "::1" ? "::1" : "127.0.0.1";
  const family = address === "::1" ? 6 : 4;
  if (options.family === 6 && family !== 6) {
    callback(
      Object.assign(
        new Error("The configured loopback family is unavailable."),
        { code: "ENOTFOUND" },
      ),
      "",
      0,
    );
    return;
  }
  if (options.family === 4 && family !== 4) {
    callback(
      Object.assign(
        new Error("The configured loopback family is unavailable."),
        { code: "ENOTFOUND" },
      ),
      "",
      0,
    );
    return;
  }
  if (options.all) {
    callback(null, [{ address, family }]);
  } else {
    callback(null, address, family);
  }
}

function responseHeaders(incoming: IncomingMessage): Headers {
  const headers = new Headers();
  for (const [name, value] of Object.entries(incoming.headers)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) headers.append(name, item);
    } else {
      headers.set(name, value);
    }
  }
  return headers;
}

function bodyBytes(body: BodyInit | null | undefined): Uint8Array | undefined {
  if (body == null) return undefined;
  if (typeof body === "string") return Buffer.from(body);
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (ArrayBuffer.isView(body)) {
    return new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
  }
  throw unavailable();
}

/**
 * Fetch a validated local API origin without asking Windows to resolve a
 * package-owned .localhost name. The URL remains authoritative for Host (and
 * HTTPS SNI); the custom lookup returns only a literal loopback address.
 */
export async function fetchDevelopmentLocalApiUpstream(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  let url: URL;
  let method: string;
  let headers: Headers;
  let signal: AbortSignal;
  let body: Uint8Array | undefined;
  try {
    if (typeof window !== "undefined") throw unavailable();
    const original = input instanceof Request ? input : null;
    url = new URL(original ? original.url : String(input));
    if (
      !["http:", "https:"].includes(url.protocol) ||
      !isLoopbackHost(url.hostname) ||
      url.username ||
      url.password ||
      url.hash
    )
      throw unavailable();
    if (init.redirect !== undefined && init.redirect !== "manual")
      throw unavailable();
    method = init.method ?? original?.method ?? "GET";
    headers = new Headers(init.headers ?? original?.headers);
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
    // http.request normally derives Host from the socket hostname. Because
    // lookup maps that hostname to 127.0.0.1/::1, set it explicitly so the
    // local API still evaluates its canonical allowlisted authority.
    headers.set("host", url.host);
    body = bodyBytes(
      init.body ?? (original?.body ? await original.arrayBuffer() : undefined),
    );
    if (body !== undefined)
      headers.set("content-length", String(body.byteLength));
    const candidateSignal = init.signal ?? original?.signal;
    signal = candidateSignal ?? new AbortController().signal;
  } catch {
    throw unavailable();
  }

  const requestFunction =
    url.protocol === "https:" ? httpsRequest : httpRequest;
  return new Promise<Response>((resolve, reject) => {
    let request: ClientRequest | undefined;
    let incoming: IncomingMessage | undefined;
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let output: ReadableStreamDefaultController<Uint8Array> | undefined;
    let settled = false;
    let finished = false;

    const cleanup = () => {
      signal.removeEventListener("abort", abort);
      request?.removeListener("error", fail);
      incoming?.removeListener("error", fail);
    };
    const stop = () => {
      void reader?.cancel().catch(() => undefined);
      incoming?.destroy();
      request?.destroy();
    };
    const fail = () => {
      if (finished) return;
      finished = true;
      cleanup();
      const error = unavailable();
      if (settled) output?.error(error);
      else reject(error);
      stop();
    };
    const abort = () => fail();

    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) {
      abort();
      return;
    }

    try {
      request = requestFunction(
        url,
        {
          method,
          headers: Object.fromEntries(headers),
          // Do not reuse a connection that may carry another local request's
          // authority or cookies. The proxy owns the timeout via signal.
          agent: false,
          lookup: loopbackLookup,
          maxHeaderSize: 32 * 1024,
        },
        (response) => {
          incoming = response;
          response.once("error", fail);
          if (finished) {
            response.destroy();
            return;
          }
          try {
            const status = response.statusCode ?? 0;
            if (status < 200 || status > 599) throw unavailable();
            const headers = responseHeaders(response);
            if (
              method.toUpperCase() === "HEAD" ||
              [204, 205, 304].includes(status)
            ) {
              finished = true;
              cleanup();
              response.resume();
              stop();
              settled = true;
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
            const bodyStream = new ReadableStream<Uint8Array>(
              {
                start(controller) {
                  output = controller;
                },
                async pull(controller) {
                  if (finished) return;
                  try {
                    const chunk = await reader!.read();
                    if (finished) return;
                    if (chunk.done) {
                      finished = true;
                      cleanup();
                      reader!.releaseLock();
                      controller.close();
                    } else {
                      controller.enqueue(chunk.value);
                    }
                  } catch {
                    fail();
                  }
                },
                cancel() {
                  if (finished) return;
                  finished = true;
                  cleanup();
                  stop();
                },
              },
              { highWaterMark: 0 },
            );
            settled = true;
            resolve(new Response(bodyStream, { status, headers }));
          } catch {
            fail();
          }
        },
      );
      request.once("error", fail);
      request.end(body ? Buffer.from(body) : undefined);
    } catch {
      fail();
    }
  });
}
