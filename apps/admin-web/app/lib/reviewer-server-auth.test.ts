import { createServer } from "node:http";
import { expect, it, vi } from "vitest";

import { requestReviewerServerIdentity, resolveReviewerServerContext } from "./reviewer-server-auth";

const base = {
  internalApiUrl: "http://api.staging.ac.internal.invalid:8000",
  internalApiHost: "api.staging.ac.internal.invalid",
  adminAppUrl: "https://admin-staging.authorityclosers.com",
};

it("does not call the internal API with the normal Admin cookie", async () => {
  const fetcher = vi.fn<typeof fetch>();
  await expect(resolveReviewerServerContext({ ...base, production: true, cookieHeader: "__Host-ac_session=" + "a".repeat(43), fetcher })).resolves.toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
});

it("admits a verified dedicated reviewer cookie from the internal reviewer projection", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ person_id: "11111111-1111-4111-8111-111111111111", email: "reviewer@example.com", display_name: "Reviewer", expires_at_epoch: 1_800_000_000 }));
  await expect(resolveReviewerServerContext({ ...base, production: true, cookieHeader: "__Host-ac_reviewer_session=" + "r".repeat(43), fetcher })).resolves.toMatchObject({ source: "verified-server-reviewer-session", actorId: "11111111-1111-4111-8111-111111111111" });
  expect(fetcher).toHaveBeenCalledWith(new URL("http://api.staging.ac.internal.invalid:8000/v1/reviewer/me"), expect.objectContaining({ headers: expect.objectContaining({ cookie: "__Host-ac_reviewer_session=" + "r".repeat(43), host: "admin-staging.authorityclosers.com" }) }));
});

it("fails closed when the configured Admin origin is not trusted", async () => {
  const fetcher = vi.fn<typeof fetch>();
  await expect(resolveReviewerServerContext({ ...base, adminAppUrl: "http://127.0.0.1:3001", production: true, cookieHeader: "__Host-ac_reviewer_session=" + "r".repeat(43), fetcher })).resolves.toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
});

it("preserves the canonical Admin Host on the native loopback transport", async () => {
  let observedHost: string | undefined;
  let observedCookie: string | undefined;
  const server = createServer((request, response) => {
    observedHost = request.headers.host;
    observedCookie = request.headers.cookie;
    response.writeHead(200, { "content-type": "application/json" });
    response.end(JSON.stringify({ person_id: "11111111-1111-4111-8111-111111111111", email: "reviewer@example.com", display_name: "Reviewer", expires_at_epoch: 1_800_000_000 }));
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });

  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("loopback test server did not expose a port");
    const cookie = "__Host-ac_reviewer_session=" + "r".repeat(43);
    const response = await requestReviewerServerIdentity(new URL(`http://127.0.0.1:${address.port}/v1/reviewer/me`), "admin-staging.authorityclosers.com", cookie);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({ email: "reviewer@example.com" });
    expect(observedHost).toBe("admin-staging.authorityclosers.com");
    expect(observedCookie).toBe(cookie);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
