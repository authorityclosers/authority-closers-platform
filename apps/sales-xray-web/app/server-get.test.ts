// @vitest-environment node
import { createServer, type IncomingHttpHeaders } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, expect, it } from "vitest";

import { MAX_ANSWER_BYTES, serverGet } from "./server-get";

let stop: (() => void) | null = null;

afterEach(() => {
  stop?.();
  stop = null;
});

type Reply = { status: number; type?: string; body: string };

/** A real local API stand-in; the handler sees each request's headers. */
async function serve(
  handler: (headers: IncomingHttpHeaders, path: string) => Reply,
): Promise<string> {
  const server = createServer((request, response) => {
    const reply = handler(request.headers, request.url ?? "");
    response.writeHead(
      reply.status,
      reply.type ? { "content-type": reply.type } : {},
    );
    response.end(reply.body);
  });
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  stop = () => {
    server.closeAllConnections();
    server.close();
  };
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

it("sends the page's own Host header, which fetch() replaces (dev seed reads were 400, 20 Oct)", async () => {
  const seen: IncomingHttpHeaders[] = [];
  const origin = await serve((headers) => {
    seen.push(headers);
    return { status: 200, type: "application/json", body: '{"ok":true}' };
  });
  const answer = await serverGet(
    `${origin}/v1/me/workspaces`,
    {
      accept: "application/json",
      cookie: "ac_session=opaque",
      host: "salesxray-dev.example.test",
    },
    AbortSignal.timeout(2000),
  );
  expect(answer).toEqual({
    status: 200,
    contentType: "application/json",
    text: '{"ok":true}',
  });
  expect(seen[0]).toMatchObject({
    host: "salesxray-dev.example.test",
    cookie: "ac_session=opaque",
    accept: "application/json",
  });
});

it("gives a redirect as its status and refuses an oversized or cancelled read", async () => {
  const origin = await serve((_, path) =>
    path === "/moved"
      ? { status: 302, body: "" }
      : { status: 200, body: "x".repeat(MAX_ANSWER_BYTES + 1) },
  );
  expect(
    (await serverGet(`${origin}/moved`, {}, AbortSignal.timeout(2000))).status,
  ).toBe(302);
  await expect(
    serverGet(`${origin}/big`, {}, AbortSignal.timeout(5000)),
  ).rejects.toThrow();
  await expect(
    serverGet(`${origin}/moved`, {}, AbortSignal.abort()),
  ).rejects.toThrow();
});
