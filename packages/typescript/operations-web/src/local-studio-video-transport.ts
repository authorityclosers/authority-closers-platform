import { request as httpRequest, type IncomingMessage } from "node:http";

import { assertLocalAdminNativePrivacy } from "./local-admin-transport";

const UUID =
  "[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const BYTE_ROUTE = new RegExp(
  `^/v1/admin/studio/programs/${UUID}/video-uploads/${UUID}/bytes$`,
  "i",
);
const MAX_FILE_BYTES = 8 * 1024 ** 3;
const MAX_WIRE_CHUNK_BYTES = 1024 ** 2;
const MAX_RESPONSE_BYTES = 64 * 1024;
let activeUploads = 0;

export class StudioVideoTransportError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "StudioVideoTransportError";
  }
}

export function isStudioVideoByteRequest(url: URL, method: string): boolean {
  return (
    method === "PUT" &&
    !url.search &&
    !url.hash &&
    BYTE_ROUTE.test(url.pathname)
  );
}

export function studioVideoByteLength(headers: Headers): number {
  const raw = headers.get("content-length") ?? "";
  const size = Number(raw);
  if (
    !/^[1-9][0-9]{0,10}$/.test(raw) ||
    !Number.isSafeInteger(size) ||
    !["video/mp4", "video/webm"].includes(headers.get("content-type") ?? "") ||
    !/^[0-9a-f]{64}$/.test(headers.get("x-content-sha256") ?? "") ||
    headers.has("transfer-encoding") ||
    ![null, "identity"].includes(headers.get("content-encoding"))
  ) {
    throw new StudioVideoTransportError(
      400,
      "studio_video_headers_invalid",
      "The video upload needs an exact file size, type and checksum.",
    );
  }
  if (size > MAX_FILE_BYTES) {
    throw new StudioVideoTransportError(
      413,
      "studio_video_too_large",
      "This video exceeds the upload size limit.",
    );
  }
  return size;
}

/** Dedicated opt-in localhost transport. Never buffers a complete lecture, follows
 * redirects, resolves remote hosts, or treats accepted bytes as a published video.
 * The API still verifies the fresh session, course permission and exact intent.
 */
export async function fetchLocalStudioVideoWire(
  input: RequestInfo | URL,
  init?: RequestInit,
  limits: { idleMs?: number; totalMs?: number } = {},
): Promise<Response> {
  assertLocalAdminNativePrivacy();
  const url = new URL(String(input));
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    url.username ||
    url.password ||
    !isStudioVideoByteRequest(url, init?.method ?? "")
  ) {
    throw new StudioVideoTransportError(
      400,
      "studio_video_destination_invalid",
      "Video bytes require the exact local Studio upload route.",
    );
  }
  const headers = new Headers(init?.headers);
  const length = studioVideoByteLength(headers);
  const origin = headers.get("origin");
  if (
    !["http://coach.localhost:3102", "http://admin.localhost:3101"].includes(
      origin ?? "",
    ) ||
    headers.get("host") !== new URL(origin!).host
  ) {
    throw new StudioVideoTransportError(
      403,
      "studio_video_origin_denied",
      "Video uploads require the current Coach or Admin workspace.",
    );
  }
  if (!(init?.body instanceof ReadableStream)) {
    throw new StudioVideoTransportError(
      400,
      "studio_video_body_required",
      "Choose a video file to upload.",
    );
  }
  const idleMs = limits.idleMs ?? 30_000;
  const totalMs = limits.totalMs ?? 1_800_000;
  if (
    !Number.isFinite(idleMs) ||
    !Number.isFinite(totalMs) ||
    idleMs < 1 ||
    idleMs > 60_000 ||
    totalMs < idleMs ||
    totalMs > 3_600_000
  ) {
    throw new Error("Video transfer deadlines must be bounded.");
  }
  if (activeUploads >= 2) {
    throw new StudioVideoTransportError(
      429,
      "studio_video_busy",
      "Two video uploads are already running. Try again when one finishes.",
    );
  }
  if (init.signal?.aborted) {
    throw new StudioVideoTransportError(
      499,
      "studio_video_cancelled",
      "The video upload was cancelled.",
    );
  }
  const reader =
    init.body.getReader() as ReadableStreamDefaultReader<Uint8Array>;
  activeUploads += 1;
  try {
    return await new Promise<Response>((resolve, reject) => {
      let settled = false;
      let uploadFinished = false;
      let requestFinished = false;
      let upstreamRejected = false;
      let incoming: IncomingMessage | undefined;
      let idleTimer: ReturnType<typeof setTimeout>;
      const request = httpRequest(url, {
        method: "PUT",
        headers: Object.fromEntries(headers),
        agent: false,
      });
      const finish = (error?: Error, response?: Response) => {
        if (settled) return;
        settled = true;
        clearTimeout(idleTimer);
        clearTimeout(totalTimer);
        init.signal?.removeEventListener("abort", cancel);
        // A pending browser read may never resolve after disconnect. cancel()
        // releases that read without retaining a socket or an upload slot.
        void reader.cancel().catch(() => undefined);
        incoming?.destroy();
        request.destroy();
        if (error) reject(error);
        else resolve(response!);
      };
      const timeout = () =>
        finish(
          new StudioVideoTransportError(
            504,
            "studio_video_timeout",
            "The video transfer timed out. Check its status before retrying.",
          ),
        );
      const cancel = () =>
        finish(
          new StudioVideoTransportError(
            499,
            "studio_video_cancelled",
            "The video upload was cancelled.",
          ),
        );
      const touch = () => {
        if (settled) return;
        clearTimeout(idleTimer);
        idleTimer = setTimeout(timeout, idleMs);
      };
      const totalTimer = setTimeout(timeout, totalMs);
      request.on("finish", () => {
        requestFinished = true;
      });
      request.on("error", () =>
        finish(
          new StudioVideoTransportError(
            502,
            "studio_video_unavailable",
            "The local video upload service could not be reached.",
          ),
        ),
      );
      request.on("response", (response) => {
        incoming = response;
        const status = response.statusCode ?? 502;
        if (status !== 204 && (status < 400 || status > 599)) {
          finish(
            new StudioVideoTransportError(
              502,
              "studio_video_response_invalid",
              "The video service returned an unexpected response.",
            ),
          );
          return;
        }
        if (
          status === 204 &&
          (!uploadFinished ||
            !requestFinished ||
            response.headers["x-ac-upload-bytes"] !== String(length) ||
            response.headers["x-ac-upload-sha256"] !==
              headers.get("x-content-sha256"))
        ) {
          finish(
            new StudioVideoTransportError(
              502,
              "studio_video_response_invalid",
              "The video service did not confirm the complete file and checksum.",
            ),
          );
          return;
        }
        if (status >= 400) {
          upstreamRejected = true;
          void reader.cancel().catch(() => undefined);
        }
        const chunks: Buffer[] = [];
        let size = 0;
        touch();
        response.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > MAX_RESPONSE_BYTES) {
            finish(
              new StudioVideoTransportError(
                502,
                "studio_video_response_invalid",
                "The video service response exceeded its size limit.",
              ),
            );
            return;
          }
          chunks.push(chunk);
          touch();
        });
        response.on("error", () =>
          finish(
            new StudioVideoTransportError(
              502,
              "studio_video_response_invalid",
              "The video service response was interrupted.",
            ),
          ),
        );
        response.on("end", () => {
          const resultHeaders = new Headers({
            "cache-control": "private, no-store",
            "x-ac-dev-data-mode": "local-admin-sandbox",
          });
          const contentType = response.headers["content-type"];
          if (
            contentType === "application/json" ||
            contentType === "application/problem+json"
          )
            resultHeaders.set("content-type", contentType);
          if (status === 204) {
            resultHeaders.set("x-ac-upload-bytes", String(length));
            resultHeaders.set(
              "x-ac-upload-sha256",
              headers.get("x-content-sha256")!,
            );
          }
          finish(
            undefined,
            new Response(
              status === 204 ? null : new Uint8Array(Buffer.concat(chunks)),
              { status, headers: resultHeaders },
            ),
          );
        });
      });
      init.signal?.addEventListener("abort", cancel, { once: true });
      if (init.signal?.aborted) cancel();
      touch();
      void (async () => {
        let sent = 0;
        while (!settled && !upstreamRejected) {
          const { done, value } = await reader.read();
          if (settled || upstreamRejected) return;
          touch();
          if (done) {
            if (sent !== length)
              throw new StudioVideoTransportError(
                400,
                "studio_video_length_mismatch",
                "The video transfer ended before the declared file size.",
              );
            uploadFinished = true;
            request.end();
            return;
          }
          if (
            !(value instanceof Uint8Array) ||
            value.byteLength === 0 ||
            sent + value.byteLength > length
          ) {
            throw new StudioVideoTransportError(
              413,
              "studio_video_length_mismatch",
              "The video transfer exceeded its declared size.",
            );
          }
          sent += value.byteLength;
          for (
            let offset = 0;
            offset < value.byteLength;
            offset += MAX_WIRE_CHUNK_BYTES
          ) {
            if (settled || upstreamRejected) return;
            const wireChunk = value.subarray(
              offset,
              Math.min(offset + MAX_WIRE_CHUNK_BYTES, value.byteLength),
            );
            // Wait for each bounded write before sending the next slice or
            // pulling another browser chunk. This applies backpressure in both
            // directions, including a slow API.
            await new Promise<void>((written, failed) =>
              request.write(wireChunk, (error) =>
                error ? failed(error) : written(),
              ),
            );
            if (settled || upstreamRejected) return;
            touch();
          }
        }
      })().catch((error: unknown) =>
        finish(
          error instanceof StudioVideoTransportError
            ? error
            : new StudioVideoTransportError(
                502,
                "studio_video_interrupted",
                "The video transfer was interrupted. Check its status before retrying.",
              ),
        ),
      );
    });
  } finally {
    activeUploads -= 1;
  }
}
