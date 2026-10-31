// @vitest-environment happy-dom
import { PERSON_WEEKS } from "./organisation/people/person-data";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readLeads } from "./leads/leads-client";

import {
  allowEarlyConversationReads,
  dropEarlyReads,
  EARLY_READ_TTL_MS,
  earlyFetch,
  earlyLeadsList,
  earlyPersonWeeks,
  earlyReadsFor,
  earlyReadsScript,
  forgetSharedReads,
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
  forgetSharedReads();
  delete (window as EarlyWindow).__sxEarly;
  window.sessionStorage.clear();
  window.localStorage.clear();
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
  // A person's profile: the directory first; their twelve weeks wait for the
  // viewer's role (the inline script, below).
  const person = "0000000A-0000-4000-8000-000000000003";
  expect(earlyReadsFor(`/organisation/people/${person}`)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    "/v1/organisation/members",
  ]);
  expect(earlyPersonWeeks(person)).toBe(
    `/v1/organisation/members/${person.toLowerCase()}/activity?weeks=${PERSON_WEEKS}`,
  );
  expect(earlyReadsFor("/organisation/people/someone")).toEqual([]);
  // Leads: the session, then To call's desk.
  expect(earlyReadsFor("/leads")).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    "/v1/lead-desk",
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

it("starts only the session reads until this device has seen Sales X-Ray on", () => {
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
  // Read again at once (another panel on the same screen): shared.
  await earlyFetch(url, { method: "GET" });
  expect(network).toHaveBeenCalledTimes(3);
  // A later read (a refresh) asks the server again.
  const later = Date.now() + EARLY_READ_TTL_MS + 1;
  vi.spyOn(Date, "now").mockReturnValue(later);
  await earlyFetch(url, { method: "GET" });
  expect(network).toHaveBeenCalledTimes(4);
  vi.restoreAllMocks();
});

it("gives the early answer to every reader on the page, not a second request", async () => {
  boot("/dashboard");
  const url = `${A}/submissions/summary`;
  const asked = network.mock.calls.length;
  await earlyFetch(url);
  // Another panel, a few seconds later on a slow phone.
  vi.spyOn(Date, "now").mockReturnValue(Date.now() + 4_000);
  expect(await (await earlyFetch(url)).json()).toEqual({ url });
  expect(network).toHaveBeenCalledTimes(asked);
  vi.restoreAllMocks();
});

it("asks the server again after the workspace changes", async () => {
  boot("/dashboard");
  const url = `${A}/session`;
  const asked = network.mock.calls.length;
  await earlyFetch(url);
  await earlyFetch(url);
  expect(network).toHaveBeenCalledTimes(asked);
  dropEarlyReads();
  await earlyFetch(url);
  expect(network).toHaveBeenCalledTimes(asked + 1);
});

it("asks the server again after a write", async () => {
  boot("/dashboard");
  const url = `${A}/session`;
  const asked = network.mock.calls.length;
  await earlyFetch(url);
  await earlyFetch(url);
  expect(network).toHaveBeenCalledTimes(asked);
  await earlyFetch(`${A}/submissions`, { method: "POST", body: "{}" });
  await earlyFetch(url);
  expect(network).toHaveBeenCalledTimes(asked + 2);
});

it("shares nothing but the page's early answers", async () => {
  const url = `${A}/report-settings`;
  await earlyFetch(url);
  await earlyFetch(url);
  expect(network).toHaveBeenCalledTimes(2);
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

it("starts the desk and All leads' first page once the directory says Sales X-Ray is on", async () => {
  const LIST = "/v1/lead-desk/leads?scope=";
  let directory: unknown = null;
  network.mockImplementation(async (url: string) =>
    Response.json(url === "/v1/me/sales-xray-workspaces" ? directory : { url }),
  );
  const workspace = (role: string | null, sales_xray_enabled = true) => ({
    selected_tenant_id: "cedar",
    workspaces: [
      { tenant_id: "maple", role: "owner", sales_xray_enabled: true },
      { tenant_id: "cedar", role, sales_xray_enabled },
    ],
  });
  const lists = () =>
    network.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.startsWith(LIST));
  const settle = async () => {
    for (let n = 0; n < 5; n++) await new Promise((r) => setTimeout(r, 0));
  };
  const start = async (path: string, conversation = true) => {
    network.mockClear();
    forgetSharedReads();
    delete (window as EarlyWindow).__sxEarly;
    boot(path, conversation);
    await settle();
    return lists();
  };
  directory = workspace("admin");
  expect(await start("/leads")).toEqual([
    `${LIST}team&side=inbound&view=to_call`,
  ]);
  expect(await start("/leads/?view=to_call&theme=dark")).toEqual([
    `${LIST}team&side=inbound&view=to_call`,
  ]);
  directory = workspace("member");
  expect(await start("/leads?tab=all")).toEqual([
    `${LIST}mine&side=inbound&view=to_call`,
  ]);
  // Another view, a filter, a workspace without Sales X-Ray, or a device
  // that has not seen Sales X-Ray on: the page asks for itself.
  for (const path of [
    "/leads?stage=won",
    "/leads?q=Fictional",
    "/leads?tab=all&stage=open",
    "/leads?side=cold",
    "/leads?view=all",
  ])
    expect(await start(path)).toEqual([]);
  // This device's first visit: the desk and the page follow the directory.
  expect(await start("/leads", false)).toEqual([
    `${LIST}mine&side=inbound&view=to_call`,
  ]);
  expect(network.mock.calls.map(([url]) => url)).toEqual([
    "/v1/me/workspaces",
    "/v1/me/sales-xray-workspaces",
    "/v1/lead-desk",
    `${LIST}mine&side=inbound&view=to_call`,
  ]);
  // Sales X-Ray off, or signed out: nothing past the session.
  directory = workspace("owner", false);
  expect(await start("/leads", false)).toEqual([]);
  expect(network).toHaveBeenCalledTimes(2);
  network.mockImplementation(async (url: string) =>
    Response.json(
      { detail: "sign in" },
      { status: url.startsWith("/v1/me/") ? 401 : 200 },
    ),
  );
  expect(await start("/leads", false)).toEqual([]);
  expect(network).toHaveBeenCalledTimes(2);
  network.mockImplementation(async (url: string) =>
    Response.json(url === "/v1/me/sales-xray-workspaces" ? directory : { url }),
  );
  // Dropped (a workspace change) before the directory answered: not started.
  directory = workspace("owner");
  network.mockClear();
  delete (window as EarlyWindow).__sxEarly;
  boot("/leads");
  dropEarlyReads();
  await settle();
  expect(lists()).toEqual([]);
  // The list takes the early answer instead of asking again.
  expect(await start("/leads")).toEqual([earlyLeadsList("owner")]);
  network.mockClear();
  await (await earlyFetch(earlyLeadsList("owner"))).json();
  expect(network).not.toHaveBeenCalled();
});

it("names All leads' first page exactly as the list asks for it", async () => {
  expect(earlyLeadsList("owner")).toBe(
    "/v1/lead-desk/leads?scope=team&side=inbound&view=to_call",
  );
  expect(earlyLeadsList("manager")).toBe(earlyLeadsList("admin"));
  expect(earlyLeadsList("member")).toBe(
    "/v1/lead-desk/leads?scope=mine&side=inbound&view=to_call",
  );
  expect(earlyLeadsList(null)).toBe(earlyLeadsList("member"));
  network.mockImplementation(async () =>
    Response.json({ leads: [], total: 0, next_offset: null, stage_counts: {} }),
  );
  const opening = { side: "inbound", view: "to_call" } as const;
  await readLeads({ scope: "team", more: opening });
  await readLeads({ scope: "mine", more: opening });
  expect(network.mock.calls.map(([url]) => url)).toEqual([
    earlyLeadsList("owner"),
    earlyLeadsList("member"),
  ]);
});

it("starts a teammate's twelve weeks only for a role that sees the team (ux-audit, 31 Oct 2026)", async () => {
  const person = "0000000a-0000-4000-8000-000000000003";
  let directory: unknown = null;
  network.mockImplementation(async (url: string) =>
    Response.json(url === "/v1/me/sales-xray-workspaces" ? directory : { url }),
  );
  const workspace = (role: string) => ({
    selected_tenant_id: "cedar",
    workspaces: [
      { tenant_id: "maple", role: "owner", sales_xray_enabled: true },
      { tenant_id: "cedar", role, sales_xray_enabled: true },
    ],
  });
  const start = async (conversation = true) => {
    network.mockClear();
    forgetSharedReads();
    delete (window as EarlyWindow).__sxEarly;
    boot(`/organisation/people/${person}`, conversation);
    for (let n = 0; n < 5; n++) await new Promise((r) => setTimeout(r, 0));
    return network.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url === earlyPersonWeeks(person));
  };
  // A seller's teammate page: the server would refuse it, so it is never asked.
  directory = workspace("member");
  expect(await start()).toEqual([]);
  for (const role of ["owner", "admin", "manager", "viewer"]) {
    directory = workspace(role);
    expect(await start()).toEqual([earlyPersonWeeks(person)]);
  }
  // This device's first visit: nothing past the session, as before.
  directory = workspace("owner");
  expect(await start(false)).toEqual([]);
});
