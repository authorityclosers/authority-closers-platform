// Node-only: importing node:https also prevents this transport entering a client bundle.
import { request as httpsRequest } from "node:https";
import type { ClientRequest, IncomingMessage } from "node:http";
import { Readable } from "node:stream";
import { assertDevelopmentMediaNativePrivacy } from "./dev-media-native-privacy";
import {
  DEVELOPMENT_MEDIA_STAGING_ORIGIN,
  isDevelopmentMediaRange,
  readDevelopmentMediaSource,
} from "./dev-media-transport";

const REQUEST_HEADERS = new Set([
  "accept",
  "accept-encoding",
  "cookie",
  "origin",
  "range",
]);
const RESPONSE_HEADERS = [
  "accept-ranges",
  "content-encoding",
  "content-length",
  "content-range",
  "content-type",
  "etag",
];
const unavailable = () =>
  new Error("Local media upstream is unavailable or cancelled.");

/**
 * Media-only HTTPS transport, deliberately outside Next's patched fetch/HMR cache.
 * Metadata validation only withholds transport; the upstream still authenticates
 * the original session cookie and signed URL. The caller owns header/read/total
 * deadlines through the required signal and validates status, MIME and byte limits.
 */
export async function fetchDevelopmentMediaUpstream(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  let source: string;
  let method: string;
  let headers: Headers;
  let signal: AbortSignal;
  try {
    assertDevelopmentMediaNativePrivacy();
    if (typeof window !== "undefined") throw unavailable();
    const original = input instanceof Request ? input : null;
    source = original ? original.url : String(input);
    method = init.method ?? original?.method ?? "GET";
    headers = new Headers(init.headers ?? original?.headers);
    const candidateSignal = init.signal ?? original?.signal;
    if (
      !readDevelopmentMediaSource(source) ||
      !["GET", "HEAD"].includes(method) ||
      init.body != null ||
      original?.body != null ||
      (init.redirect !== undefined && init.redirect !== "manual") ||
      !candidateSignal ||
      candidateSignal.aborted ||
      !isDevelopmentMediaRange(headers.get("range")) ||
      headers.get("origin") !== DEVELOPMENT_MEDIA_STAGING_ORIGIN ||
      headers.get("accept-encoding") !== "identity" ||
      !/^__Host-ac_session=[A-Za-z0-9_-]{43,512}$/.test(
        headers.get("cookie") ?? "",
      ) ||
      [...headers].some(
        ([name, value]) => !REQUEST_HEADERS.has(name) || value.length > 1024,
      )
    )
      throw unavailable();
    signal = candidateSignal;
  } catch {
    throw unavailable();
  }

  return new Promise<Response>((resolve, reject) => {
    let request: ClientRequest | undefined;
    let response: IncomingMessage | undefined;
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let output: ReadableStreamDefaultController<Uint8Array> | undefined;
    let settled = false;
    let finished = false;
    const cleanup = () => signal.removeEventListener("abort", abort);
    const stop = () => {
      void reader?.cancel().catch(() => undefined);
      response?.destroy();
      request?.destroy();
    };
    const abort = () => {
      if (finished) return;
      finished = true;
      cleanup();
      const error = unavailable();
      if (settled) output?.error(error);
      else reject(error);
      stop();
    };
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) {
      abort();
      return;
    }
    try {
      request = httpsRequest(
        source,
        {
          method,
          headers: Object.fromEntries(headers),
          // No pooled credential-bearing connection, redirects, decompression,
          // global fetch, framework tracing, or development response caching.
          agent: false,
          maxHeaderSize: 16 * 1024,
        },
        (incoming) => {
          response = incoming;
          if (finished) {
            incoming.destroy();
            return;
          }
          incoming.on("error", abort); // Never expose native URL-bearing errors.
          try {
            const status = incoming.statusCode ?? 0;
            if (status < 200 || status > 599) throw unavailable();
            const outputHeaders = new Headers();
            for (const name of RESPONSE_HEADERS) {
              const value = incoming.headers[name];
              if (typeof value === "string") outputHeaders.set(name, value);
              else if (value !== undefined) throw unavailable();
            }
            if (method === "HEAD" || [204, 205, 304].includes(status)) {
              const result = new Response(null, {
                status,
                headers: outputHeaders,
              });
              finished = true;
              cleanup();
              stop();
              settled = true;
              resolve(result);
              return;
            }
            // Explicit byte-size strategy: the default counts chunks and can
            // otherwise multiply a Node byte high-water mark into a large queue.
            reader = (
              Readable.toWeb(incoming, {
                strategy: {
                  highWaterMark: 64 * 1024,
                  size: (chunk: Uint8Array) => chunk.byteLength,
                },
              }) as ReadableStream<Uint8Array>
            ).getReader();
            const body = new ReadableStream<Uint8Array>(
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
                    } else controller.enqueue(chunk.value);
                  } catch {
                    abort();
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
            const result = new Response(body, {
              status,
              headers: outputHeaders,
            });
            settled = true;
            resolve(result);
          } catch {
            abort();
          }
        },
      );
      request.on("error", abort);
      request.end();
    } catch {
      abort();
    }
  });
}
