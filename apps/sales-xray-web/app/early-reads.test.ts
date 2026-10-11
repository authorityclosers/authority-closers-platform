// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
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
function boot(path: string) {
  window.history.replaceState(null, "", path);
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
    `${A}/submissions?include_owners=true`,
  ]);
  expect(earlyReadsFor("/analysis/calls/")).toContain(
    `${A}/submissions?include_owners=true`,
  );
  const id = "0000000A-0000-4000-8000-000000000500";
  expect(earlyReadsFor(`/analysis/calls/${id}`)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    `${A}/entry`,
    `${A}/session`,
    `${A}/submissions/${id.toLowerCase()}`,
  ]);
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
});

it("answers the page's read from the early one, once", async () => {
  boot("/analysis/calls");
  const url = `${A}/submissions?include_owners=true`;
  const first = await earlyFetch(url, { method: "GET" });
  expect(await first.json()).toEqual({ url });
  expect(network).toHaveBeenCalledTimes(3);
  // A later read (a refresh) asks the server again.
  await earlyFetch(url, { method: "GET" });
  expect(network).toHaveBeenCalledTimes(4);
});

it("keeps the answer for the next reader when the first is cancelled (double mount)", async () => {
  boot("/analysis/calls");
  const url = `${A}/submissions?include_owners=true`;
  const cancelled = new AbortController();
  const read = earlyFetch(url, { signal: cancelled.signal });
  cancelled.abort();
  await expect(read).rejects.toMatchObject({ name: "AbortError" });
  const second = await earlyFetch(url, {});
  expect(await second.json()).toEqual({ url });
  expect(network).toHaveBeenCalledTimes(3);
});

it("gives every reader its own copy and keeps the server's status", async () => {
  window.history.replaceState(null, "", "/dashboard");
  (window as EarlyWindow).__sxEarly = {
    [`${A}/forbidden`]: {
      at: Date.now(),
      p: Promise.resolve(Response.json({}, { status: 403 })),
    },
  };
  const both = await Promise.all([
    earlyFetch(`${A}/forbidden`),
    earlyFetch(`${A}/forbidden`),
  ]);
  expect(both.map((response) => response.status)).toEqual([403, 403]);
  expect(network).not.toHaveBeenCalled();
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
  window.history.replaceState(null, "", "/analysis/calls");
  new Function(earlyReadsScript())();
  // The first early read (/v1/me/workspaces) failed: the app asks again.
  const response = await earlyFetch("/v1/me/workspaces");
  expect(response.status).toBe(200);
  expect(network).toHaveBeenCalledTimes(4);
});
