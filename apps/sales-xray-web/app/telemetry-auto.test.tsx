// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ pathname: "/leads" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
vi.mock("next/web-vitals", () => ({ useReportWebVitals: () => undefined }));
const phone = vi.hoisted(() => ({
  drain: vi.fn(async () => [] as Array<{ name: string; fields: object }>),
  tell: vi.fn(async (on: boolean) => {
    void on;
  }),
}));
vi.mock("./leads/native-phone", () => ({
  drainPhoneTelemetry: phone.drain,
  tellPhoneTelemetry: phone.tell,
}));

import { telemetry } from "./telemetry";
import {
  actionOf,
  endpointOf,
  errorFacts,
  fingerprint,
  syncPhone,
  targetOf,
  TelemetryAuto,
} from "./telemetry-auto";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let now = 0;
let host: HTMLDivElement;

beforeEach(() => {
  now = 1_000;
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.spyOn(telemetry, "active").mockReturnValue(true);
  host = document.createElement("div");
  document.body.append(host);
  window.history.replaceState({}, "", "/leads");
});

afterEach(() => {
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const html = (markup: string) => {
  host.innerHTML = markup;
  return host;
};

it("names key actions from what the tap is on, never from its words", () => {
  html(`
    <ul><li data-lead-row="" data-row-key="L1"><span id="lead">Asha</span>
      <button id="call" aria-label="Call Asha">Call</button>
      <button id="wa" aria-label="WhatsApp">W</button></li></ul>
    <a id="tel" href="tel:+910000000000">Dial</a>
    <div role="tablist"><button id="tab" role="tab">Stages</button></div>
    <nav><a id="nav" href="/calls">Calls</a></nav>
    <a id="report" href="/analysis/calls/abc">Report</a>
    <button id="sheet" aria-haspopup="dialog">Add</button>
    <button id="mine" data-sx-action="outcome_save">Save</button>
    <button id="odd" data-sx-action="whatever">?</button>
    <p id="text">Plain words</p>`);
  const of = (id: string) => actionOf(host.querySelector(`#${id}`));
  expect(of("lead")).toBe("lead_open");
  expect(of("call")).toBe("call_start");
  expect(of("wa")).toBeNull();
  expect(of("tel")).toBe("call_start");
  expect(of("tab")).toBe("tab_switch");
  expect(of("nav")).toBe("nav_switch");
  expect(of("report")).toBe("report_open");
  expect(of("sheet")).toBe("sheet_open");
  expect(of("mine")).toBe("outcome_save");
  expect(of("odd")).toBe("other");
  expect(of("text")).toBeNull();
  expect(targetOf(host.querySelector("#tab")!)).toBe("tab");
  expect(targetOf(host.querySelector("#lead")!)).toBe("row");
  expect(targetOf(host.querySelector("#text")!)).toBe("text");
});

it("takes every id out of an API path and fingerprints errors without their words", () => {
  expect(
    endpointOf("/v1/leads/3f2b7d10-aaaa-4bbb-8ccc-0123456789ab/calls?x=1"),
  ).toBe("v1_leads_id_calls");
  expect(endpointOf("/v1/settings/lead-rules")).toBe("v1_settings_lead_rules");
  expect(endpointOf("/v1/people/asha.menon@example.com")).toBe("v1_people_id");
  expect(fingerprint("abc")).toMatch(/^[0-9a-f]{8}$/);
  const error = new TypeError("Cannot read properties of Asha Menon's lead");
  error.stack =
    "TypeError: Cannot read …\n    at open (https://app.example/_next/static/chunks/page-1a2b.js?v=9:12:34)";
  const facts = errorFacts(error, "https://app.example");
  expect(facts).toEqual({
    error: "typeerror",
    where: fingerprint("typeerror|page-1a2b.js:12"),
    source: "app",
  });
  expect(JSON.stringify(facts)).not.toContain("Asha");
  expect(errorFacts("boom", "https://app.example")).toMatchObject({
    error: "error",
    source: "unknown",
  });
  const extension = new Error("x");
  extension.stack = "Error: x\n at y (chrome-extension://abc/inject.js:1:2)";
  expect(errorFacts(extension, "https://app.example").source).toBe("extension");
});

async function mount() {
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<TelemetryAuto />));
  return root;
}

const tracked = (spy: { mock: { calls: unknown[][] } }, name: string) =>
  spy.mock.calls
    .filter((call: unknown[]) => call[0] === name)
    .map((call: unknown[]) => call[1] as Record<string, unknown>);

it("times a tap on a lead row to the screen settling", async () => {
  const track = vi.spyOn(telemetry, "track");
  html(`<ul><li data-lead-row=""><span id="lead">Asha</span></li></ul>`);
  const root = await mount();
  expect(tracked(track, "sx.screen_viewed")).toEqual([
    { screen: "leads", from: "none", nav: "first" },
  ]);
  expect(tracked(track, "sx.app_start")[0]).toMatchObject({ ms: 1000 });

  const lead = host.querySelector("#lead")!;
  lead.dispatchEvent(
    new PointerEvent("pointerdown", { bubbles: true, composed: true }),
  );
  // The sheet opens in two steps; the screen is settled 150 ms after the last.
  now = 1_400;
  await act(async () => {
    host.append(document.createElement("section"));
  });
  now = 1_900;
  await act(async () => {
    host.append(document.createElement("section"));
  });
  await act(async () => {
    vi.advanceTimersByTime(200);
  });
  const [timing] = tracked(track, "sx.action_timing");
  expect(timing).toMatchObject({
    action: "lead_open",
    result: "settled",
    screen: "leads",
  });
  // From the tap (1,000) to the last change (1,900).
  expect(timing?.ms).toBe(900);

  // A tap that changes nothing in a second is "no_change".
  html(`<div role="tablist"><button id="tab" role="tab">x</button></div>`);
  host
    .querySelector("#tab")!
    .dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  await act(async () => {
    vi.advanceTimersByTime(1_100);
  });
  expect(tracked(track, "sx.action_timing")[1]).toMatchObject({
    action: "tab_switch",
    result: "no_change",
  });
  await act(async () => root.unmount());
});

it("reports a rage tap and a screen change with the time on the last screen", async () => {
  const track = vi.spyOn(telemetry, "track");
  html(`<button id="b">Go</button>`);
  const root = await mount();
  const button = host.querySelector("#b")!;
  for (let index = 0; index < 3; index += 1)
    button.dispatchEvent(
      new MouseEvent("click", { bubbles: true, clientX: 10, clientY: 10 }),
    );
  expect(tracked(track, "sx.tap_issue")).toEqual([
    { kind: "rage", target: "button", screen: "leads" },
  ]);
  now = 6_000;
  nav.pathname = "/calls";
  await act(async () => root.render(<TelemetryAuto />));
  expect(tracked(track, "sx.screen_viewed")[1]).toEqual({
    screen: "calls",
    from: "leads",
    nav: "push",
    stay_ms: 5_000,
  });
  await act(async () => root.unmount());
  nav.pathname = "/leads";
});

it("does nothing for a person the server records nothing for", async () => {
  vi.spyOn(telemetry, "active").mockReturnValue(false);
  const track = vi.spyOn(telemetry, "track");
  html(`<ul><li data-lead-row=""><span id="lead">x</span></li></ul>`);
  const root = await mount();
  host
    .querySelector("#lead")!
    .dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  await act(async () => {
    vi.advanceTimersByTime(11_000);
  });
  expect(tracked(track, "sx.action_timing")).toEqual([]);
  expect(tracked(track, "sx.screen_viewed")).toEqual([]);
  await act(async () => root.unmount());
});

it("tells the phone app the switch once the server answers, and sends its events", async () => {
  const collecting = vi.spyOn(telemetry, "collecting");
  const track = vi.spyOn(telemetry, "track").mockImplementation(() => {});
  phone.tell.mockClear();
  phone.drain.mockClear();

  // Not known yet (nobody signed in): the app is told nothing.
  collecting.mockResolvedValue(null);
  expect(await syncPhone()).toBeNull();
  expect(phone.tell).not.toHaveBeenCalled();

  // Off: the app is told, and nothing it holds is read.
  collecting.mockResolvedValue(false);
  expect(await syncPhone()).toBe(false);
  expect(phone.tell).toHaveBeenLastCalledWith(false);
  expect(phone.drain).not.toHaveBeenCalled();

  // On: only the app's own events go on, under the page's switch.
  collecting.mockResolvedValue(true);
  phone.drain.mockResolvedValue([
    { name: "sx.app_launch", fields: { start: "cold", ms: 2400 } },
    { name: "sx.sign_out", fields: {} },
    { name: "sx.permission_snapshot", fields: { calls: "granted" } },
  ]);
  expect(await syncPhone()).toBe(true);
  expect(phone.tell).toHaveBeenLastCalledWith(true);
  expect(track.mock.calls).toEqual([
    ["sx.app_launch", { start: "cold", ms: 2400 }],
    ["sx.permission_snapshot", { calls: "granted" }],
  ]);
});
