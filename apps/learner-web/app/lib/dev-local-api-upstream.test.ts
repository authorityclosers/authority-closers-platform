import { createServer, type RequestListener, type Server } from "node:http";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchDevelopmentLocalApiUpstream } from "./dev-local-api-upstream";

async function listeningServer(
  handler: RequestListener,
): Promise<{ server: Server; origin: string }> {
  const server = createServer(handler);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("Test server did not expose a TCP address.");
  }
  return { server, origin: `http://learner.localhost:${address.port}` };
}

async function closeServer(server: Server): Promise<void> {
  if (!server.listening) return;
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("development local API upstream transport", () => {
  it("bypasses unavailable .localhost DNS while preserving the canonical Host", async () => {
    let observedHost: string | undefined;
    let observedAddress: string | undefined;
    let observedForwarded: string | undefined;
    let observedEncoding: string | undefined;
    let observedBody = "";
    const { server, origin } = await listeningServer((request, response) => {
      observedHost = request.headers.host;
      observedAddress = request.socket.remoteAddress;
      const forwarded = request.headers["x-forwarded-host"];
      observedForwarded = typeof forwarded === "string" ? forwarded : undefined;
      const encoding = request.headers["accept-encoding"];
      observedEncoding = typeof encoding === "string" ? encoding : undefined;
      request.setEncoding("utf8");
      request.on("data", (chunk: string) => {
        observedBody += chunk;
      });
      request.on("end", () => {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({ accepted: true }));
      });
    });

    try {
      const response = await fetchDevelopmentLocalApiUpstream(
        `${origin}/v1/me`,
        {
          method: "POST",
          redirect: "manual",
          signal: new AbortController().signal,
          headers: {
            "content-type": "application/json",
            host: "attacker.example",
            "x-forwarded-host": "attacker.example",
          },
          body: JSON.stringify({ local: true }),
        },
      );

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toEqual({ accepted: true });
      expect(observedHost).toBe(new URL(origin).host);
      expect(observedAddress).toBe("127.0.0.1");
      expect(observedForwarded).toBeUndefined();
      expect(observedEncoding).toBe("identity");
      expect(observedBody).toBe(JSON.stringify({ local: true }));
    } finally {
      await closeServer(server);
    }
  });

  it("rejects non-loopback origins before opening a native request", async () => {
    await expect(
      fetchDevelopmentLocalApiUpstream("https://api.example.test/v1/me", {
        redirect: "manual",
        signal: new AbortController().signal,
      }),
    ).rejects.toThrow("Local API upstream is unavailable or cancelled.");
  });

  it("fails closed before native IO when network diagnostics are enabled", async () => {
    vi.stubEnv("NODE_DEBUG", "http");
    let received = false;
    const { server, origin } = await listeningServer((_request, response) => {
      received = true;
      response.writeHead(200);
      response.end("unexpected");
    });
    try {
      await expect(
        fetchDevelopmentLocalApiUpstream(`${origin}/v1/me`, {
          redirect: "manual",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow("Local API upstream is unavailable or cancelled.");
      expect(received).toBe(false);
    } finally {
      await closeServer(server);
    }
  });

  it("sanitizes native transport failures and follows no redirects", async () => {
    const { server, origin } = await listeningServer((_request, response) => {
      response.writeHead(302, { location: "https://evil.example.test" });
      response.end();
    });
    try {
      const response = await fetchDevelopmentLocalApiUpstream(
        `${origin}/v1/me`,
        { redirect: "manual", signal: new AbortController().signal },
      );
      expect(response.status).toBe(302);
      expect(response.headers.get("location")).toBe(
        "https://evil.example.test",
      );
    } finally {
      await closeServer(server);
    }
  });

  it("fails closed when an upstream ignores identity encoding", async () => {
    const { server, origin } = await listeningServer((_request, response) => {
      response.writeHead(200, {
        "content-encoding": "gzip",
        "content-type": "application/json",
      });
      response.end();
    });
    try {
      await expect(
        fetchDevelopmentLocalApiUpstream(`${origin}/v1/me`, {
          redirect: "manual",
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow("Local API upstream is unavailable or cancelled.");
    } finally {
      await closeServer(server);
    }
  });
});
