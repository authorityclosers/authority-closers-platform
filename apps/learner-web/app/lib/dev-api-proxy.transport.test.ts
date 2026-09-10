import { createServer, type RequestListener, type Server } from "node:http";
import { afterEach, describe, expect, it, vi } from "vitest";

import { proxyDevelopmentLearnerApi } from "./dev-api-proxy";

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

afterEach(() => vi.unstubAllGlobals());

describe("development learner API proxy transport selection", () => {
  it("uses literal loopback transport for a validated .localhost API origin", async () => {
    let observedHost: string | undefined;
    let observedAddress: string | undefined;
    let observedForwardedHost: string | undefined;
    const { server, origin } = await listeningServer((request, response) => {
      observedHost = request.headers.host;
      observedAddress = request.socket.remoteAddress;
      const forwarded = request.headers["x-forwarded-host"];
      observedForwardedHost =
        typeof forwarded === "string" ? forwarded : undefined;
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ accepted: true }));
    });

    try {
      const response = await proxyDevelopmentLearnerApi(
        new Request("http://localhost:3000/v1/me", {
          headers: {
            origin: "http://localhost:3000",
            host: "localhost:3000",
            "x-forwarded-host": "attacker.example",
          },
        }),
        undefined,
        { AC_DEV_API_ORIGIN: origin },
        "development",
      );

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toEqual({ accepted: true });
      expect(observedHost).toBe(new URL(origin).host);
      expect(observedAddress).toBe("127.0.0.1");
      expect(observedForwardedHost).toBeUndefined();
    } finally {
      await closeServer(server);
    }
  });

  it("keeps staging preview on the normal fetch transport", async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe(
        "https://api-staging.authorityclosers.com/v1/programs?limit=1",
      );
      return Response.json({ items: [] });
    });
    vi.stubGlobal("fetch", fetcher);

    const response = await proxyDevelopmentLearnerApi(
      new Request("http://localhost:3000/v1/programs?limit=1"),
      undefined,
      { AC_DEV_API_ORIGIN: "https://api-staging.authorityclosers.com" },
      "development",
    );

    expect(response.status).toBe(200);
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
