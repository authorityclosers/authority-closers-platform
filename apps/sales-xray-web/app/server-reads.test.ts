import { afterEach, beforeEach, expect, it, vi } from "vitest";

const incoming = vi.hoisted(() => ({ value: new Headers() }));
const api = vi.hoisted(() => ({
  get: null as unknown as (...args: unknown[]) => Promise<unknown>,
}));
vi.mock("next/headers", () => ({ headers: async () => incoming.value }));
vi.mock("./server-get", () => ({
  serverGet: (...args: unknown[]) => api.get(...args),
}));

import {
  serverApiOrigin,
  serverDisplayDates,
  serverReads,
  serverSession,
  SESSION_PATHS,
} from "./server-reads";
import { seededChoices } from "./standalone-studio";

let network: ReturnType<typeof vi.fn>;

/** One API answer, as server-get.ts gives it. */
const json = (body: unknown, status = 200) => ({
  status,
  contentType: "application/json",
  text: JSON.stringify(body),
});

beforeEach(() => {
  incoming.value = new Headers({
    cookie: "ac_session=opaque",
    host: "salesxray-dev.example.test",
  });
  network = vi.fn(async (url: string) =>
    json({ url }, url.includes("/me/") ? 200 : 404),
  );
  api.get = network as unknown as typeof api.get;
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "http://127.0.0.1:8100");
  vi.stubEnv("AC_SALES_XRAY_STATIC_PREVIEW", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

it("reads on the server only with an exact, credential-free API origin", () => {
  expect(
    serverApiOrigin({ AC_CONVERSATION_API_ORIGIN: "http://api:8100" }),
  ).toBe("http://api:8100");
  for (const bad of [
    undefined,
    "",
    "http://user:pass@api:8100",
    "http://api:8100/v1",
    "http://api:8100/?x=1",
    "ftp://api",
    "not a url",
  ])
    expect(serverApiOrigin({ AC_CONVERSATION_API_ORIGIN: bad })).toBeNull();
  expect(
    serverApiOrigin({
      AC_CONVERSATION_API_ORIGIN: "http://api:8100",
      AC_SALES_XRAY_STATIC_PREVIEW: "1",
    }),
  ).toBeNull();
});

it("asks the API as this request (its cookie and host), GET only, together", async () => {
  const reads = await serverReads(["/v1/me/workspaces", "/v1/x/y"]);
  expect(reads).toEqual({
    "/v1/me/workspaces": {
      status: 200,
      body: { url: "http://127.0.0.1:8100/v1/me/workspaces" },
    },
    "/v1/x/y": { status: 404, body: { url: "http://127.0.0.1:8100/v1/x/y" } },
  });
  for (const [, sent, signal] of network.mock.calls) {
    expect(sent).toEqual({
      accept: "application/json",
      cookie: "ac_session=opaque",
      host: "salesxray-dev.example.test",
    });
    expect(signal).toBeInstanceOf(AbortSignal);
  }
});

it("keeps a failed or non-JSON read null, never the page", async () => {
  network.mockImplementation(async (url: string) => {
    if (url.endsWith("/a")) throw new Error("refused");
    return { status: 200, contentType: "text/html", text: "<html>" };
  });
  expect(await serverReads(["/v1/a", "/v1/b"])).toEqual({
    "/v1/a": null,
    "/v1/b": { status: 200, body: null },
  });
});

it("leaves reading to the browser without a session cookie, a sane host, an origin or a full page load", async () => {
  incoming.value = new Headers({ host: "salesxray-dev.example.test" });
  expect(await serverReads(["/v1/me/workspaces"])).toBeNull();
  incoming.value = new Headers({ cookie: "a=b", host: "evil host/x" });
  expect(await serverReads(["/v1/me/workspaces"])).toBeNull();
  // An in-app navigation or prefetch (not the document): the browser reads.
  incoming.value = new Headers({
    cookie: "a=b",
    host: "ok.test",
    "sec-fetch-dest": "empty",
  });
  expect(await serverReads(["/v1/me/workspaces"])).toBeNull();
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "");
  incoming.value = new Headers({ cookie: "a=b", host: "ok.test" });
  expect(await serverReads(["/v1/me/workspaces"])).toBeNull();
  expect(network).not.toHaveBeenCalled();
  // A full page load reads.
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "http://127.0.0.1:8100");
  incoming.value = new Headers({
    cookie: "a=b",
    host: "ok.test",
    "sec-fetch-dest": "document",
  });
  expect(await serverReads(["/v1/me/workspaces"])).not.toBeNull();
});

it("starts the app ready only from a full, selected server session", async () => {
  const identity = {
    person_id: "person-1",
    session_id: "session-1",
    selected_tenant_id: null,
    workspaces: [],
  };
  const directory = {
    selected_tenant_id: "tenant-1",
    workspaces: [
      {
        tenant_id: "tenant-1",
        kind: "organisation",
        name: "Fictional Org",
        role: "owner",
        sales_xray_enabled: true,
      },
    ],
  };
  network.mockImplementation(async (url: string) =>
    json(url.endsWith(SESSION_PATHS[0]) ? identity : directory),
  );
  const session = await serverSession();
  expect(seededChoices(session)).toMatchObject({
    person_id: "person-1",
    session_id: "session-1",
    selected_tenant_id: "tenant-1",
  });
  // No selection yet (the browser picks Personal), a bad shape, or no
  // session: the app checks in the browser as before.
  expect(
    seededChoices({
      identity,
      directory: { ...directory, selected_tenant_id: null },
    }),
  ).toBeNull();
  expect(seededChoices({ identity: { nope: 1 }, directory })).toBeNull();
  expect(seededChoices(null)).toBeNull();
  network.mockImplementation(async () => json({}, 401));
  expect(await serverSession()).toBeNull();
});

it("writes dates in the request's language and India time where it draws data", async () => {
  incoming.value = new Headers({ "accept-language": "en-GB,en;q=0.8" });
  expect(await serverDisplayDates()).toMatchObject({
    locale: "en-GB",
    timeZone: "Asia/Kolkata",
  });
  vi.stubEnv("AC_CONVERSATION_API_ORIGIN", "");
  expect(await serverDisplayDates()).toBeNull();
});
