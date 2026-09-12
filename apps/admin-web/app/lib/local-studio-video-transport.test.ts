import { createHash } from "node:crypto";
import { ClientRequest, createServer, type RequestListener } from "node:http";
import type { AddressInfo } from "node:net";
import { describe, expect, it, vi } from "vitest";

import {
  fetchLocalStudioVideoWire,
  isStudioVideoByteRequest,
  studioVideoByteLength,
} from "../../../../packages/typescript/operations-web/src/local-studio-video-transport";
import {
  proxyDevelopmentAdminApi,
  isCoachApiRequest,
  isStagingAdminRequest,
} from "./dev-api-proxy";

const path =
  "/v1/admin/studio/programs/11111111-1111-4111-8111-111111111111/video-uploads/22222222-2222-4222-8222-222222222222/bytes";
const origin = "http://coach.localhost:3102";
const checksum = "a".repeat(64);
const maxWireChunkBytes = 1024 ** 2;
function envelope(length: number) {
  return new Headers({
    host: "coach.localhost:3102",
    origin,
    "content-length": String(length),
    "content-type": "video/mp4",
    "x-content-sha256": checksum,
  });
}
function stream(chunks: Uint8Array[], cancel = vi.fn()) {
  return new ReadableStream<Uint8Array>(
    {
      pull(controller) {
        const chunk = chunks.shift();
        if (chunk) controller.enqueue(chunk);
        else controller.close();
      },
      cancel,
    },
    { highWaterMark: 0 },
  );
}
async function serverTest(
  handler: RequestListener,
  run: (url: URL) => Promise<void>,
) {
  const server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    await run(
      new URL(
        path,
        `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
      ),
    );
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
}

describe("local Studio video wire transport", () => {
  it("streams a 24 MiB lecture with bounded pulls and exact bytes over real HTTP", async () => {
    const chunk = new Uint8Array(64 * 1024).fill(37);
    const count = 384;
    let pulls = 0;
    let receivedBytes = 0;
    let maxAhead = 0;
    let receivedDigest = "";
    const expected = createHash("sha256");
    for (let i = 0; i < count; i++) expected.update(chunk);
    const expectedDigest = expected.digest("hex");
    await serverTest(
      (request, response) => {
        expect(request.headers.host).toBe("coach.localhost:3102");
        expect(request.headers["content-length"]).toBe(
          String(chunk.length * count),
        );
        expect(request.headers["transfer-encoding"]).toBeUndefined();
        expect(request.headers["x-content-sha256"]).toBe(expectedDigest);
        const hash = createHash("sha256");
        request.on("data", (bytes: Buffer) => {
          receivedBytes += bytes.length;
          hash.update(bytes);
        });
        request.on("end", () => {
          receivedDigest = hash.digest("hex");
          response.writeHead(204, {
            "set-cookie": "not-forwarded=1",
            "x-ac-upload-bytes": String(receivedBytes),
            "x-ac-upload-sha256": receivedDigest,
          });
          response.end();
        });
      },
      async (url) => {
        const body = new ReadableStream<Uint8Array>(
          {
            pull(controller) {
              maxAhead = Math.max(
                maxAhead,
                pulls * chunk.length - receivedBytes,
              );
              if (pulls++ < count) controller.enqueue(chunk);
              else controller.close();
            },
          },
          { highWaterMark: 0 },
        );
        const headers = envelope(chunk.length * count);
        headers.set("x-content-sha256", expectedDigest);
        const response = await fetchLocalStudioVideoWire(url, {
          method: "PUT",
          headers,
          body,
        });
        expect(response.status).toBe(204);
        expect(response.headers.get("cache-control")).toBe("private, no-store");
        expect(response.headers.has("set-cookie")).toBe(false);
        expect(response.headers.get("x-ac-upload-bytes")).toBe(
          String(receivedBytes),
        );
        expect(response.headers.get("x-ac-upload-sha256")).toBe(expectedDigest);
        expect(receivedBytes).toBe(chunk.length * count);
        expect(receivedDigest).toBe(expectedDigest);
        expect(maxAhead).toBeLessThan(chunk.length * count);
      },
    );
  });

  it("splits one valid large browser chunk into callback-gated bounded wire writes", async () => {
    const bytes = new Uint8Array(2 * maxWireChunkBytes + 17).fill(41);
    const digest = createHash("sha256").update(bytes).digest("hex");
    const originalWrite = ClientRequest.prototype.write;
    let pulls = 0;
    let releaseFirstWrite: () => void = () => undefined;
    let observeFirstWrite: () => void = () => undefined;
    const firstWriteObserved = new Promise<void>((resolve) => {
      observeFirstWrite = resolve;
    });
    const writes = vi
      .spyOn(ClientRequest.prototype, "write")
      .mockImplementation(function (this: ClientRequest, chunk, callback) {
        const written = callback as unknown as (error?: Error | null) => void;
        if (writes.mock.calls.length !== 1)
          return originalWrite.call(this, chunk, "utf8", written);
        return originalWrite.call(
          this,
          chunk,
          "utf8",
          (error?: Error | null) => {
            releaseFirstWrite = () => written(error);
            observeFirstWrite();
          },
        );
      });
    try {
      await serverTest(
        (request, response) => {
          let received = 0;
          const hash = createHash("sha256");
          request.on("data", (chunk: Buffer) => {
            received += chunk.length;
            hash.update(chunk);
          });
          request.on("end", () => {
            response.writeHead(204, {
              "x-ac-upload-bytes": String(received),
              "x-ac-upload-sha256": hash.digest("hex"),
            });
            response.end();
          });
        },
        async (url) => {
          const headers = envelope(bytes.byteLength);
          headers.set("x-content-sha256", digest);
          const transfer = fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers,
            body: new ReadableStream<Uint8Array>(
              {
                pull(controller) {
                  pulls += 1;
                  if (pulls === 1) controller.enqueue(bytes);
                  else controller.close();
                },
              },
              { highWaterMark: 0 },
            ),
          });
          await firstWriteObserved;
          await Promise.resolve();
          expect(writes).toHaveBeenCalledOnce();
          expect(pulls).toBe(1);
          releaseFirstWrite();
          const response = await transfer;
          expect(response.status).toBe(204);
        },
      );
      expect(
        writes.mock.calls.map(([chunk]) => (chunk as Uint8Array).byteLength),
      ).toEqual([maxWireChunkBytes, maxWireChunkBytes, 17]);
    } finally {
      writes.mockRestore();
    }
  });

  it("stops splitting a large chunk after an early permission denial", async () => {
    const cancelled = vi.fn();
    let pulls = 0;
    const writes = vi.spyOn(ClientRequest.prototype, "write");
    try {
      await serverTest(
        (request, response) => {
          request.once("data", () => {
            response.writeHead(403, {
              "content-type": "application/problem+json",
            });
            response.end('{"code":"media_forbidden"}');
          });
        },
        async (url) => {
          const body = new ReadableStream<Uint8Array>({
            pull(controller) {
              if (pulls++ === 0)
                controller.enqueue(new Uint8Array(4 * maxWireChunkBytes));
              else return new Promise(() => undefined);
            },
            cancel: cancelled,
          });
          const response = await fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers: envelope(5 * maxWireChunkBytes),
            body,
          });
          expect(response.status).toBe(403);
          expect(await response.json()).toEqual({ code: "media_forbidden" });
          expect(cancelled).toHaveBeenCalledOnce();
          expect(writes.mock.calls.length).toBeLessThan(4);
          expect(
            writes.mock.calls.every(
              ([chunk]) =>
                (chunk as Uint8Array).byteLength <= maxWireChunkBytes,
            ),
          ).toBe(true);
        },
      );
    } finally {
      writes.mockRestore();
    }
  });

  it.each([302, 200, 204])(
    "rejects unexpected or premature success status %s",
    async (status) => {
      await serverTest(
        (request, response) => {
          request.once("data", () => {
            response.writeHead(status, { location: "http://example.invalid/" });
            response.end();
          });
        },
        async (url) => {
          let pulled = false;
          const body = new ReadableStream<Uint8Array>({
            pull(controller) {
              if (!pulled) {
                pulled = true;
                controller.enqueue(new Uint8Array(10));
              } else return new Promise(() => undefined);
            },
          });
          await expect(
            fetchLocalStudioVideoWire(url, {
              method: "PUT",
              headers: envelope(100),
              body,
            }),
          ).rejects.toMatchObject({ code: "studio_video_response_invalid" });
        },
      );
    },
  );

  it.each([
    ["missing receipt", {}],
    [
      "wrong length",
      { "x-ac-upload-bytes": "9", "x-ac-upload-sha256": checksum },
    ],
    [
      "wrong checksum",
      { "x-ac-upload-bytes": "10", "x-ac-upload-sha256": "b".repeat(64) },
    ],
    [
      "duplicate receipt",
      { "x-ac-upload-bytes": ["10", "10"], "x-ac-upload-sha256": checksum },
    ],
  ])("rejects a completed transfer with %s", async (_name, receipt) => {
    await serverTest(
      (request, response) => {
        request.resume();
        request.on("end", () => {
          response.writeHead(204, receipt);
          response.end();
        });
      },
      async (url) => {
        await expect(
          fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers: envelope(10),
            body: stream([new Uint8Array(10)]),
          }),
        ).rejects.toMatchObject({ code: "studio_video_response_invalid" });
      },
    );
  });

  it("does not accept bare204 after a peer reads only the first lecture frame", async () => {
    let read = 0;
    const size = 2 * 1024 ** 2;
    await serverTest(
      (request, response) => {
        request.once("data", (bytes: Buffer) => {
          read = bytes.length;
          request.pause();
          response.writeHead(204);
          response.end();
        });
      },
      async (url) => {
        await expect(
          fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers: envelope(size),
            body: stream(
              Array.from({ length: 32 }, () => new Uint8Array(64 * 1024)),
            ),
          }),
        ).rejects.toMatchObject({ status: 502 });
        expect(read).toBeGreaterThan(0);
        expect(read).toBeLessThan(size);
      },
    );
  });

  it.each([
    ["short", 10, [new Uint8Array(5)], 400],
    ["empty chunk", 10, [new Uint8Array(0)], 413],
    ["long", 10, [new Uint8Array(11)], 413],
  ] as const)(
    "rejects %s request bytes",
    async (_name, declared, chunks, status) => {
      await serverTest(
        (request) => request.resume(),
        async (url) => {
          await expect(
            fetchLocalStudioVideoWire(url, {
              method: "PUT",
              headers: envelope(declared),
              body: stream([...chunks]),
            }),
          ).rejects.toMatchObject({ status });
        },
      );
    },
  );

  it("rejects a large incoming chunk beyond the declared total before writing", async () => {
    const writes = vi.spyOn(ClientRequest.prototype, "write");
    try {
      await serverTest(
        (request) => request.resume(),
        async (url) => {
          await expect(
            fetchLocalStudioVideoWire(url, {
              method: "PUT",
              headers: envelope(2 * maxWireChunkBytes),
              body: stream([new Uint8Array(2 * maxWireChunkBytes + 1)]),
            }),
          ).rejects.toMatchObject({ status: 413 });
        },
      );
      expect(writes).not.toHaveBeenCalled();
    } finally {
      writes.mockRestore();
    }
  });

  it("rejects an over-declared total after bounded writes of a large chunk", async () => {
    const writes = vi.spyOn(ClientRequest.prototype, "write");
    try {
      await serverTest(
        (request) => request.resume(),
        async (url) => {
          await expect(
            fetchLocalStudioVideoWire(url, {
              method: "PUT",
              headers: envelope(2 * maxWireChunkBytes + 1),
              body: stream([new Uint8Array(2 * maxWireChunkBytes)]),
            }),
          ).rejects.toMatchObject({ status: 400 });
        },
      );
      expect(
        writes.mock.calls.map(([chunk]) => (chunk as Uint8Array).byteLength),
      ).toEqual([maxWireChunkBytes, maxWireChunkBytes]);
    } finally {
      writes.mockRestore();
    }
  });

  it("cancels a stalled source on its idle deadline and releases its slot", async () => {
    const cancelled = vi.fn();
    await serverTest(
      (request) => request.resume(),
      async (url) => {
        for (let attempt = 0; attempt < 3; attempt++) {
          const body = new ReadableStream<Uint8Array>({
            pull: () => new Promise(() => undefined),
            cancel: cancelled,
          });
          await expect(
            fetchLocalStudioVideoWire(
              url,
              { method: "PUT", headers: envelope(10), body },
              { idleMs: 40, totalMs: 200 },
            ),
          ).rejects.toMatchObject({ status: 504 });
        }
        expect(cancelled).toHaveBeenCalledTimes(3);
      },
    );
  });

  it("aborts the socket and source when the browser cancels during splitting", async () => {
    const controller = new AbortController();
    const cancelled = vi.fn();
    const originalWrite = ClientRequest.prototype.write;
    const writes = vi
      .spyOn(ClientRequest.prototype, "write")
      .mockImplementation(function (this: ClientRequest, chunk, callback) {
        const result = originalWrite.call(this, chunk, callback);
        controller.abort();
        return result;
      });
    try {
      await serverTest(
        (request) => request.resume(),
        async (url) => {
          const body = stream(
            [new Uint8Array(3 * maxWireChunkBytes)],
            cancelled,
          );
          await expect(
            fetchLocalStudioVideoWire(url, {
              method: "PUT",
              headers: envelope(3 * maxWireChunkBytes),
              body,
              signal: controller.signal,
            }),
          ).rejects.toMatchObject({ status: 499 });
          expect(cancelled).toHaveBeenCalledOnce();
          expect(writes).toHaveBeenCalledOnce();
        },
      );
    } finally {
      writes.mockRestore();
    }
  });

  it("limits concurrent transfers to two and frees both slots on cancellation", async () => {
    await serverTest(
      (request) => request.resume(),
      async (url) => {
        const controllers = [new AbortController(), new AbortController()];
        const cancelled = vi.fn();
        const transfers = controllers.map((controller) =>
          fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers: envelope(100),
            signal: controller.signal,
            body: new ReadableStream<Uint8Array>({
              pull: () => new Promise(() => undefined),
              cancel: cancelled,
            }),
          }).catch((error: unknown) => error),
        );
        await expect(
          fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers: envelope(100),
            body: stream([new Uint8Array(100)]),
          }),
        ).rejects.toMatchObject({ status: 429 });
        for (const controller of controllers) controller.abort();
        for (const result of await Promise.all(transfers))
          expect(result).toMatchObject({ status: 499 });
        expect(cancelled).toHaveBeenCalledTimes(2);
        await expect(
          fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers: envelope(100),
            body: stream([new Uint8Array(1)]),
          }),
        ).rejects.toMatchObject({ status: 400 });
      },
    );
  });

  it("has a total deadline even while individual chunks keep arriving", async () => {
    await serverTest(
      (request) => request.resume(),
      async (url) => {
        const body = new ReadableStream<Uint8Array>(
          {
            async pull(controller) {
              await new Promise((resolve) => setTimeout(resolve, 10));
              try {
                controller.enqueue(new Uint8Array(1));
              } catch {
                /* cancellation closed the stream */
              }
            },
          },
          { highWaterMark: 0 },
        );
        await expect(
          fetchLocalStudioVideoWire(
            url,
            { method: "PUT", headers: envelope(100000), body },
            { idleMs: 100, totalMs: 160 },
          ),
        ).rejects.toMatchObject({ status: 504 });
      },
    );
  });

  it("times out an API that accepts the complete file but never replies", async () => {
    await serverTest(
      (request) => request.resume(),
      async (url) => {
        await expect(
          fetchLocalStudioVideoWire(
            url,
            {
              method: "PUT",
              headers: envelope(10),
              body: stream([new Uint8Array(10)]),
            },
            { idleMs: 50, totalMs: 250 },
          ),
        ).rejects.toMatchObject({ status: 504 });
      },
    );
  });

  it("rejects a pre-cancelled upload before opening a connection", async () => {
    const connections = vi.fn();
    await serverTest(connections, async (url) => {
      await expect(
        fetchLocalStudioVideoWire(url, {
          method: "PUT",
          headers: envelope(10),
          body: stream([new Uint8Array(10)]),
          signal: AbortSignal.abort(),
        }),
      ).rejects.toMatchObject({ status: 499 });
      expect(connections).not.toHaveBeenCalled();
    });
  });

  it("rejects oversized API replies", async () => {
    await serverTest(
      (request, response) => {
        request.resume();
        request.once("end", () => {
          response.writeHead(400);
          response.end(Buffer.alloc(65 * 1024));
        });
      },
      async (url) => {
        await expect(
          fetchLocalStudioVideoWire(url, {
            method: "PUT",
            headers: envelope(10),
            body: stream([new Uint8Array(10)]),
          }),
        ).rejects.toMatchObject({ code: "studio_video_response_invalid" });
      },
    );
  });

  it.each([
    "https://127.0.0.1:8000",
    "http://localhost:8000",
    "http://192.0.2.1",
    "http://user:password@127.0.0.1:8000",
  ])(
    "rejects non-private destination %s before reading",
    async (destination) => {
      await expect(
        fetchLocalStudioVideoWire(`${destination}${path}`, {
          method: "PUT",
          headers: envelope(10),
          body: stream([new Uint8Array(10)]),
        }),
      ).rejects.toMatchObject({ code: "studio_video_destination_invalid" });
    },
  );

  it.each([
    ["content-length", "10,10"],
    ["content-length", "-1"],
    ["content-length", "0"],
    ["content-type", "application/json"],
    ["x-content-sha256", "A".repeat(64)],
    ["transfer-encoding", "chunked"],
    ["content-encoding", "gzip"],
  ])("rejects malformed %s header", (name, value) => {
    const headers = envelope(10);
    headers.set(name, value);
    expect(() => studioVideoByteLength(headers)).toThrow();
  });
});

const localEnvironment = {
  AC_DEV_LOCAL_SANDBOX_ENABLED: "true",
  AC_DEV_ADMIN_API_ORIGIN: "http://127.0.0.1:8000",
  AC_DEV_OPERATIONS_SURFACE: "coach",
  AC_DEV_LOCAL_SANDBOX_ADMIN_ORIGIN: origin,
  AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED: "true",
};
function uploadRequest(headers = envelope(10)) {
  return new Request(origin + path, {
    method: "PUT",
    headers,
    body: stream([new Uint8Array(10)]),
    duplex: "half",
  } as RequestInit);
}

describe("opt-in local Coach upload route", () => {
  it("does not widen staging bridge routes", () => {
    expect(isStudioVideoByteRequest(new URL(origin + path), "PUT")).toBe(true);
    expect(isCoachApiRequest(new URL(origin + path), "PUT")).toBe(false);
    expect(isStagingAdminRequest(new URL(origin + path), "PUT")).toBe(false);
    for (const suffix of ["?tenant=x", "/", "/complete", "#fragment"])
      expect(
        isStudioVideoByteRequest(new URL(origin + path + suffix), "PUT"),
      ).toBe(false);
  });

  it("forwards a stream only after exact local-origin checks and only local session credentials", async () => {
    const headers = envelope(10);
    headers.set("cookie", "ac_session=synthetic; unrelated=discarded");
    headers.set("x-forwarded-for", "192.0.2.5");
    const fetcher = vi.fn(
      async (_input: RequestInfo | URL, init?: RequestInit) => {
        expect(init?.body).toBeInstanceOf(ReadableStream);
        const outbound = new Headers(init?.headers);
        expect(outbound.get("content-length")).toBe("10");
        expect(outbound.get("x-content-sha256")).toBe(checksum);
        expect(outbound.get("cookie")).toBe("ac_session=synthetic");
        expect(outbound.has("x-forwarded-for")).toBe(false);
        expect(outbound.get("host")).toBe("coach.localhost:3102");
        return new Response(null, { status: 204 });
      },
    );
    expect(
      (
        await proxyDevelopmentAdminApi(
          uploadRequest(headers),
          fetcher,
          localEnvironment,
          "development",
        )
      ).status,
    ).toBe(204);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it.each([undefined, "false", "TRUE"])(
    "stays disabled for flag %s",
    async (flag) => {
      const fetcher = vi.fn();
      expect(
        (
          await proxyDevelopmentAdminApi(
            uploadRequest(),
            fetcher,
            { ...localEnvironment, AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED: flag },
            "development",
          )
        ).status,
      ).toBe(403);
      expect(fetcher).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["origin", "http://learner.localhost:3100"],
    ["host", "admin.localhost:3101"],
    ["authorization", "Bearer synthetic"],
    ["content-length", "10,10"],
  ])("rejects unsafe %s before touching the body", async (name, value) => {
    const headers = envelope(10);
    headers.set(name, value);
    const fetcher = vi.fn();
    const response = await proxyDevelopmentAdminApi(
      uploadRequest(headers),
      fetcher,
      localEnvironment,
      "development",
    );
    expect([400, 403]).toContain(response.status);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("keeps production proxy disabled even with the local upload flag", async () => {
    const fetcher = vi.fn();
    expect(
      (
        await proxyDevelopmentAdminApi(
          uploadRequest(),
          fetcher,
          localEnvironment,
          "production",
        )
      ).status,
    ).toBe(404);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not extend the ordinary one-MiB JSON limit", async () => {
    const fetcher = vi.fn();
    const request = new Request(origin + "/v1/admin/studio/programs", {
      method: "POST",
      headers: { origin, "content-type": "application/json" },
      body: JSON.stringify({ title: "x".repeat(1024 ** 2) }),
    });
    expect(
      (
        await proxyDevelopmentAdminApi(
          request,
          fetcher,
          localEnvironment,
          "development",
        )
      ).status,
    ).toBe(413);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not enable byte uploads in generic local mode", async () => {
    const fetcher = vi.fn();
    expect(
      (
        await proxyDevelopmentAdminApi(
          uploadRequest(),
          fetcher,
          { AC_DEV_STUDIO_VIDEO_UPLOAD_ENABLED: "true" },
          "development",
        )
      ).status,
    ).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
