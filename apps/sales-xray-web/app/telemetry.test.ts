// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  audioFormat,
  safePayload,
  sizeBand,
  TELEMETRY_EVENT_NAMES,
  TelemetryClient,
  waitBand,
} from "./telemetry";

const SESSION = "11111111-1111-4111-8111-111111111111";
let calls: Array<{ url: string; body: unknown }>;
let taxonomy: string[] | null;
let ingestStatus: number;

function client(enabled = true) {
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
