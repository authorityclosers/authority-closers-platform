// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  appVersion,
  audioFormat,
  deviceClass,
  deviceTier,
  network,
  readBand,
  routeTemplate,
  safePayload,
  screenOf,
  sizeBand,
  TELEMETRY_EVENT_NAMES,
  TelemetryClient,
  waitBand,
  type EventContext,
} from "./telemetry";

const SESSION = "11111111-1111-4111-8111-111111111111";
let calls: Array<{ url: string; body: unknown }>;
let taxonomy: string[] | null;
let ingestStatus: number;

function client(enabled = true, context?: () => EventContext) {
  let n = 0;
  return new TelemetryClient(
    {
      fetch: vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
        const path = String(url);
        calls.push({
          url: path,
          body: init?.body ? JSON.parse(String(init.body)) : null,
        });
        if (path === "/v1/telemetry/taxonomy")
          return taxonomy
            ? Response.json({
                events: taxonomy.map((event_name) => ({ event_name })),
              })
            : new Response("{}", { status: 404 });
        return new Response("{}", { status: ingestStatus });
      }) as unknown as typeof fetch,
      now: () => new Date("2026-10-11T05:00:00Z"),
      id: () => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`,
      ...(context ? { context } : {}),
    },
    enabled,
  );
}

const sent = () =>
  calls
    .filter((call) => call.url === "/v1/telemetry/events")
    .flatMap(
      (call) =>
        (call.body as { events: Array<Record<string, unknown>> }).events,
    );

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  taxonomy = [...TELEMETRY_EVENT_NAMES];
  ingestStatus = 202;
});

afterEach(() => {
  vi.useRealTimers();
});

it("sends typed events in one batch, bound to the signed-in session", async () => {
  const telemetry = client();
  telemetry.track("sx.upload_started", {
    size_band: "under_5mb",
    format: "wav",
  });
  telemetry.setSession(SESSION);
  telemetry.track("sx.clip_played", { kind: "preview" });
  await vi.runAllTimersAsync();
  expect(sent()).toEqual([
    expect.objectContaining({
      event_name: "sx.upload_started",
      event_version: "1.0",
      occurred_at: "2026-10-11T05:00:00.000Z",
      session_id: SESSION,
      route: null,
      payload: { size_band: "under_5mb", format: "wav" },
    }),
    expect.objectContaining({
      event_name: "sx.clip_played",
      payload: { kind: "preview" },
    }),
  ]);
});

it("sends only what the server lists, and nothing when it lists nothing", async () => {
  taxonomy = ["sx.clip_played"];
  const telemetry = client();
  telemetry.setSession(SESSION);
  telemetry.track("sx.mission_started", {});
  telemetry.track("sx.clip_played", { kind: "full" });
  await vi.runAllTimersAsync();
  expect(sent().map((event) => event.event_name)).toEqual(["sx.clip_played"]);

  calls = [];
  taxonomy = null;
  const off = client();
  off.setSession(SESSION);
  off.track("sx.clip_played", { kind: "full" });
  await vi.runAllTimersAsync();
  off.track("sx.clip_played", { kind: "full" });
  await vi.runAllTimersAsync();
  expect(sent()).toEqual([]);
  // The taxonomy is read once; telemetry then stays off for the page.
  expect(calls.filter((call) => call.url.endsWith("taxonomy"))).toHaveLength(1);
});

it("starts no read while the page is being left; sends on exit once the list is known", async () => {
  const telemetry = client();
  telemetry.setSession(SESSION);
  telemetry.track("sx.sign_out", {});
  await telemetry.flush(true);
  expect(calls).toEqual([]);
  await vi.runAllTimersAsync();
  expect(sent().map((event) => event.event_name)).toEqual(["sx.sign_out"]);

  calls = [];
  telemetry.track("sx.sign_out", {});
  await telemetry.flush(true);
  expect(calls.map((call) => call.url)).toEqual(["/v1/telemetry/events"]);
});

it("switches off for the page when the server refuses a batch (no consent policy yet)", async () => {
  ingestStatus = 503;
  const telemetry = client();
  telemetry.setSession(SESSION);
  telemetry.track("sx.sign_out", {});
  await vi.runAllTimersAsync();
  telemetry.track("sx.sign_out", {});
  await vi.runAllTimersAsync();
  expect(
    calls.filter((call) => call.url === "/v1/telemetry/events"),
  ).toHaveLength(1);
});

it("never sends personal or free text payloads", () => {
  expect(safePayload({ kind: "preview", read_ms: 1200 })).toBe(true);
  expect(safePayload({ email: "a" })).toBe(false);
  expect(safePayload({ call_name: "Discovery" })).toBe(false);
  expect(safePayload({ surface: "Asha Menon's call" })).toBe(false);
  expect(safePayload({ code: "a@b.example" })).toBe(false);
  expect(safePayload({ seconds: Number.NaN })).toBe(false);
  const telemetry = client();
  telemetry.setSession(SESSION);
  telemetry.track("sx.prospect_edited", { field: "Ledgerly Pvt Ltd" });
  expect(calls).toEqual([]);
});

it("drops queued events of another session, never re-labelling them", async () => {
  const telemetry = client();
  telemetry.setSession(SESSION);
  telemetry.track("sx.mission_completed", {});
  telemetry.setSession("22222222-2222-4222-8222-222222222222");
  await vi.runAllTimersAsync();
  expect(sent()).toEqual([]);
});

it("stays silent when disabled (server render, tests)", async () => {
  const telemetry = client(false);
  telemetry.setSession(SESSION);
  telemetry.track("sx.clip_played", { kind: "full" });
  await vi.runAllTimersAsync();
  expect(calls).toEqual([]);
});

it("reports sizes, formats and waits in bands, not exact values", () => {
  expect(sizeBand(1_000_000)).toBe("under_5mb");
  expect(sizeBand(12 * 1024 ** 2)).toBe("5_to_20mb");
  expect(sizeBand(30 * 1024 ** 2)).toBe("over_20mb");
  expect(audioFormat("Call with Rohan.MP3")).toBe("mp3");
  expect(audioFormat("call.mpeg")).toBe("mp3");
  expect(audioFormat("call.amr")).toBe("other");
  expect(waitBand(90_000)).toBe("under_2m");
  expect(waitBand(4 * 60_000)).toBe("2_to_5m");
  expect(waitBand(Number.NaN)).toBe("unknown");
});

const CALL = "3F2B7D10-AAAA-4BBB-8CCC-0123456789AB";

it("sends a report's call apart from its payload, with the page, device and app", async () => {
  const telemetry = client(true, () => ({
    route: routeTemplate(`/analysis/calls/${CALL}`),
    device: "phone",
    app: "android",
  }));
  telemetry.setSession(SESSION);
  telemetry.track("sx.section_read", {
    call_id: CALL,
    section: "analysis",
    skill: "d07",
    read_band: "5_30s",
    dwell_ms: 12_400,
  });
  // A malformed id is left off; the event still counts.
  telemetry.track("sx.full_report_requested", {
    call_id: "not-a-call",
    surface: "report",
  });
  await vi.runAllTimersAsync();
  expect(sent()).toEqual([
    expect.objectContaining({
      event_name: "sx.section_read",
      route: "/analysis/calls/[callId]",
      call_id: CALL.toLowerCase(),
      payload: {
        section: "analysis",
        skill: "d07",
        read_band: "5_30s",
        dwell_ms: 12_400,
        device: "phone",
        app: "android",
      },
    }),
    expect.objectContaining({
      event_name: "sx.full_report_requested",
      payload: { surface: "report", device: "phone", app: "android" },
    }),
  ]);
  expect(sent()[1]).not.toHaveProperty("call_id");
  expect(JSON.stringify(sent())).not.toContain(`calls/${CALL}`);
});

it("names pages by their templates, never their ids, and bands reads and screens", () => {
  expect(routeTemplate("/")).toBe("/");
  expect(routeTemplate("/leads/")).toBe("/leads");
  expect(routeTemplate("/prospects/5d1c")).toBe("/prospects/[prospectId]");
  expect(routeTemplate("/settings/lead-rules")).toBe("/settings/[section]");
  expect(routeTemplate("/organisation/people/abc")).toBe(
    "/organisation/people/[personId]",
  );
  expect(routeTemplate("/login")).toBeNull();
  expect(routeTemplate("/analysis/calls/a/b")).toBeNull();
  expect(readBand(4_999)).toBe("under_5s");
  expect(readBand(5_000)).toBe("5_30s");
  expect(readBand(30_000)).toBe("30_120s");
  expect(readBand(120_000)).toBe("over_120s");
  expect(deviceClass(390)).toBe("phone");
  expect(deviceClass(820)).toBe("tablet");
  expect(deviceClass(1440)).toBe("desktop");
});

it("says how capable the device and network are, and the app's version", () => {
  expect(deviceTier(8, 8)).toBe("high");
  expect(deviceTier(8, 4)).toBe("mid");
  expect(deviceTier(4, 8)).toBe("low");
  expect(deviceTier(8, 2)).toBe("low");
  expect(deviceTier(6, undefined)).toBe("mid");
  expect(deviceTier(undefined, undefined)).toBe("unknown");
  expect(network({ effectiveType: "slow-2g", type: "cellular" }, true)).toEqual(
    {
      net: "slow_2g",
      link: "cellular",
    },
  );
  expect(network(undefined, false)).toEqual({
    net: "unknown",
    link: "offline",
  });
  expect(appVersion("Mozilla/5.0 (Linux) SalesXrayApp/0.3.88 Chrome")).toBe(
    "0.3.88",
  );
  expect(appVersion("Mozilla/5.0 Chrome")).toBeNull();
  expect(screenOf("/leads")).toBe("leads");
  expect(screenOf("/leads", "?lead=abc")).toBe("lead");
  expect(screenOf("/analysis/calls/3f2b7d10-aaaa")).toBe("report");
  expect(screenOf("/login")).toBe("other");
});

it("carries where an event ran and stops automatic capture when nothing is recorded", async () => {
  const telemetry = client(true, () => ({
    route: "/leads",
    device: "phone",
    app: "android",
    tier: "low",
    net: "4g",
    link: "wifi",
    appVersion: "0.3.88",
  }));
  telemetry.setSession(SESSION);
  expect(telemetry.active()).toBe(true);
  telemetry.track("sx.screen_viewed", { screen: "leads", nav: "first" });
  await vi.runAllTimersAsync();
  expect(sent()[0]?.payload).toEqual({
    screen: "leads",
    nav: "first",
    device: "phone",
    app: "android",
    tier: "low",
    net: "4g",
    link: "wifi",
    app_version: "0.3.88",
  });

  // The server lists nothing for someone who turned it off: capture stops,
  // until Settings, Privacy asks again.
  calls = [];
  taxonomy = [];
  const off = client(true);
  off.setSession(SESSION);
  off.track("sx.sign_out", {});
  await vi.runAllTimersAsync();
  expect(off.active()).toBe(false);
  off.refresh();
  expect(off.active()).toBe(true);
});

it("says whether this person is recorded only once the server has answered", async () => {
  const telemetry = client(true);
  // Nobody signed in yet: unknown, so the phone app is told nothing.
  expect(await telemetry.collecting()).toBeNull();
  telemetry.setSession(SESSION);
  expect(await telemetry.collecting()).toBe(true);

  taxonomy = [];
  const off = client(true);
  off.setSession(SESSION);
  expect(await off.collecting()).toBe(false);

  // No answer (an error, offline) decides nothing, and the next ask reads again.
  taxonomy = null;
  const failing = client(true);
  failing.setSession(SESSION);
  expect(await failing.collecting()).toBeNull();
  taxonomy = ["sx.app_launch"];
  expect(await failing.collecting()).toBe(true);
  await expect(client(false).collecting()).resolves.toBeNull();
});

it("takes the phone app's daily profile, its largest event, with where it ran", async () => {
  const telemetry = client(true, () => ({
    route: "/leads",
    device: "phone",
    app: "android",
    tier: "mid",
    net: "4g",
    link: "cellular",
    appVersion: "1.0.26",
  }));
  telemetry.setSession(SESSION);
  telemetry.track("sx.device_profile", {
    android: 14,
    maker: "xiaomi",
    model_label: "m1906g7g",
    webview: "130",
    ram_tier: "4",
    memory_class: 256,
    low_ram: "no",
    storage_free: "4to16",
    store: "play",
  });
  await vi.runAllTimersAsync();
  expect(Object.keys(sent()[0]?.payload as object)).toHaveLength(15);
});
