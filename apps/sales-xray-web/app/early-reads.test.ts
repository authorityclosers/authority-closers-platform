// @vitest-environment happy-dom
import { PERSON_WEEKS } from "./organisation/people/person-data";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  allowEarlyConversationReads,
  dropEarlyReads,
  EARLY_READ_TTL_MS,
  earlyFetch,
  earlyReadsFor,
  earlyReadsScript,
} from "./early-reads";

type EarlyWindow = Window & { __sxEarly?: Record<string, unknown> };
const early = () => (window as EarlyWindow).__sxEarly;
const A = "/v1/conversation/acquisition";

let network: ReturnType<typeof vi.fn>;

/** Run the layout's inline script for an address, as the browser would. */
function boot(path: string, conversation = true) {
  window.history.replaceState(null, "", path);
  allowEarlyConversationReads(conversation);
  new Function(earlyReadsScript())();
}

beforeEach(() => {
  network = vi.fn(async (url: string) =>
    Response.json({ url }, { status: url.includes("forbidden") ? 403 : 200 }),
  );
  vi.stubGlobal("fetch", network);
});

afterEach(() => {
  delete (window as EarlyWindow).__sxEarly;
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("names each page's first reads, exactly as the page asks for them", () => {
  expect(earlyReadsFor("/dashboard")).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    `${A}/submissions/summary`,
    `${A}/activity`,
    `${A}/session`,
    `${A}/submissions?include_owners=true&order=reports_first&include_summary=true&include_leads=true`,
  ]);
  expect(earlyReadsFor("/analysis/calls/")).toContain(
    `${A}/submissions?include_owners=true&order=reports_first&include_summary=true&include_leads=true`,
  );
  const id = "0000000A-0000-4000-8000-000000000500";
  expect(earlyReadsFor(`/analysis/calls/${id}`)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    `${A}/entry`,
    `${A}/session`,
    `${A}/report-settings`,
    `${A}/submissions/${id.toLowerCase()}`,
    `${A}/submissions/${id.toLowerCase()}/transcript`,
    `${A}/submissions/${id.toLowerCase()}/report`,
  ]);
  // A person's profile: the directory and their twelve weeks.
  const person = "0000000A-0000-4000-8000-000000000003";
  expect(earlyReadsFor(`/organisation/people/${person}`)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    "/v1/organisation/members",
    `/v1/organisation/members/${person.toLowerCase()}/activity?weeks=${PERSON_WEEKS}`,
  ]);
  expect(earlyReadsFor("/organisation/people/someone")).toEqual([]);
  // Public pages and unknown addresses start nothing.
  expect(earlyReadsFor("/pricing")).toEqual([]);
  expect(earlyReadsFor("/analysis/calls/not-a-call")).toEqual([]);
});

it("starts the reads from the inline script with the browser's own session", async () => {
  const id = "00000000-0000-4000-8000-000000000500";
  boot(`/analysis/calls/${id}/`);
  expect(network.mock.calls.map(([url]) => url)).toEqual(
    earlyReadsFor(`/analysis/calls/${id}`),
  );
  network.mockClear();
  boot("/dashboard");
  expect(network).toHaveBeenCalledTimes(6);
  for (const [, init] of network.mock.calls)
    expect(init).toMatchObject({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
    });
  boot("/pricing");
  expect(network).toHaveBeenCalledTimes(6);
  network.mockClear();
  boot("/organisation/people/0000000A-0000-4000-8000-000000000003/");
  expect(network.mock.calls.map(([url]) => url)).toEqual(
    earlyReadsFor("/organisation/people/0000000A-0000-4000-8000-000000000003"),
  );
});

it("reads every early answer at once, so no request stays open", async () => {
  const read = vi.fn(async () => "{}");
  network.mockImplementation(async () => ({
    status: 200,
    statusText: "OK",
    headers: new Headers({ "content-type": "application/json" }),
    text: read,
  }));
  boot("/dashboard");
  await vi.waitFor(() => expect(read).toHaveBeenCalledTimes(6));
});

it("keeps the server's headers on the answer it hands out", async () => {
  network.mockImplementation(async () =>
    Response.json({ ok: true }, { headers: { "x-request-id": "req-1" } }),
  );
  boot("/analysis/calls");
  const response = await earlyFetch(
    `${A}/submissions?include_owners=true&order=reports_first&include_summary=true&include_leads=true`,
  );
  expect(response.headers.get("x-request-id")).toBe("req-1");
  expect(response.headers.get("content-type")).toContain("application/json");
  expect(await response.json()).toEqual({ ok: true });
});

it("starts only the session reads until this tab has seen Sales X-Ray on", () => {
  boot("/dashboard", false);
  expect(network.mock.calls.map(([url]) => url)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
  ]);
});

it("answers the page's read from the early one, once", async () => {
  boot("/analysis/calls");
  const url = `${A}/submissions?include_owners=true&order=reports_first&include_summary=true&include_leads=true`;
  const first = await earlyFetch(url, { method: "GET" });
  expect(await first.json()).toEqual({ url });
  expect(network).toHaveBeenCalledTimes(3);
  // A later read (a refresh) asks the server again.
  await earlyFetch(url, { method: "GET" });
  expect(network).toHaveBeenCalledTimes(4);
});

it("keeps the answer for the next reader when the first is cancelled (double mount)", async () => {
  boot("/analysis/calls");
  const url = `${A}/submissions?include_owners=true&order=reports_first&include_summary=true&include_leads=true`;
  const cancelled = new AbortController();
  const read = earlyFetch(url, { signal: cancelled.signal });
  cancelled.abort();
  await expect(read).rejects.toMatchObject({ name: "AbortError" });
  const second = await earlyFetch(url, {});
  expect(await second.json()).toEqual({ url });
  expect(network).toHaveBeenCalledTimes(3);
});

it("gives every reader its own copy", async () => {
  window.history.replaceState(null, "", "/dashboard");
  (window as EarlyWindow).__sxEarly = {
    [`${A}/session`]: {
      at: Date.now(),
      p: Promise.resolve({
        status: 200,
        statusText: "OK",
        headers: [["content-type", "application/json"]],
        body: '{"allowance":null}',
      }),
    },
  };
  const both = await Promise.all([
    earlyFetch(`${A}/session`),
    earlyFetch(`${A}/session`),
  ]);
  expect(await Promise.all(both.map((response) => response.json()))).toEqual([
    { allowance: null },
    { allowance: null },
  ]);
  expect(network).not.toHaveBeenCalled();
});

it("asks the server again rather than serve an early failure or not-ready answer", async () => {
  window.history.replaceState(null, "", "/analysis/calls");
  (window as EarlyWindow).__sxEarly = {
    [`${A}/forbidden`]: {
      at: Date.now(),
      p: Promise.resolve({
        status: 409,
        statusText: "Conflict",
        headers: [],
        body: "{}",
      }),
    },
  };
  const response = await earlyFetch(`${A}/forbidden`);
  expect(network).toHaveBeenCalledTimes(1);
  expect(response.status).toBe(403);
});

it("never serves writes, custom requests, stale or dropped answers", async () => {
  boot("/dashboard");
  const url = `${A}/session`;
  await earlyFetch(url, { method: "POST", body: "{}" });
  expect(network).toHaveBeenCalledTimes(7);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(Date.now() + EARLY_READ_TTL_MS + 1);
  await earlyFetch(url);
  expect(network).toHaveBeenCalledTimes(8);
  vi.useRealTimers();
  boot("/dashboard");
  dropEarlyReads();
  expect(Object.keys(early() ?? {})).toEqual([]);
  await earlyFetch(`${A}/activity`);
  expect(network).toHaveBeenCalledTimes(15);
});

it("falls back to the server when the early read itself failed", async () => {
  network.mockRejectedValueOnce(new TypeError("offline"));
  boot("/analysis/calls");
  // The first early read (/v1/me/workspaces) failed: the app asks again.
  const response = await earlyFetch("/v1/me/workspaces");
  expect(response.status).toBe(200);
  expect(network).toHaveBeenCalledTimes(4);
});
