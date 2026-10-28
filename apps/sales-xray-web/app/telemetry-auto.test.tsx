// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ pathname: "/leads" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));
const vitals = vi.hoisted(() => ({
  callback: (metric: { name: string; value: number; rating: string }) => {
    void metric;
  },
}));
vi.mock("next/web-vitals", () => ({
  useReportWebVitals: (callback: typeof vitals.callback) => {
    vitals.callback = callback;
  },
}));
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

import { telemetry, timeAction } from "./telemetry";
import {
  actionOf,
  apiTiming,
  scrollDepth,
  elementOf,
  endpointOf,
  errorFacts,
  fingerprint,
  overlapsHidden,
  placeOf,
  seenSoFar,
  slowCall,
  styleOf,
  syncPhone,
  targetOf,
  TelemetryAuto,
  zoneOf,
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
    {
      kind: "rage",
      target: "button",
      screen: "leads",
      zone: "r1c1",
      where: expect.stringMatching(/^[0-9a-f]{8}$/),
    },
  ]);
  now = 6_000;
  nav.pathname = "/calls";
  await act(async () => root.render(<TelemetryAuto />));
  expect(tracked(track, "sx.screen_viewed")[1]).toEqual({
    screen: "calls",
    from: "leads",
    nav: "push",
    stay_ms: 5_000,
    seen_ms: 5_000,
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

it("doesn't time a swipe across tabs, or a press on the tab already shown", async () => {
  const track = vi.spyOn(telemetry, "track");
  html(`
    <div role="tablist">
      <button id="on" role="tab" aria-selected="true">Now</button>
      <button id="off" role="tab" aria-selected="false">All</button>
    </div>
    <nav><a id="here" href="/leads" aria-current="page">Leads</a></nav>`);
  const root = await mount();
  // The chosen tab, and the tab bar's own page: nothing is meant to change.
  for (const id of ["#on", "#here"])
    host
      .querySelector(id)!
      .dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  // A finger that lands on a tab and swipes the strip: the browser cancels it.
  const off = host.querySelector("#off")!;
  off.dispatchEvent(
    new PointerEvent("pointerdown", { bubbles: true, pointerId: 7 }),
  );
  off.dispatchEvent(
    new PointerEvent("pointercancel", { bubbles: true, pointerId: 7 }),
  );
  await act(async () => {
    vi.advanceTimersByTime(11_000);
  });
  expect(tracked(track, "sx.action_timing")).toEqual([]);

  // A real press on another tab is still timed.
  off.dispatchEvent(
    new PointerEvent("pointerdown", { bubbles: true, pointerId: 8 }),
  );
  await act(async () => {
    vi.advanceTimersByTime(1_100);
  });
  expect(tracked(track, "sx.action_timing")).toEqual([
    expect.objectContaining({ action: "tab_switch", result: "no_change" }),
  ]);
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

it("names where a tap landed by zone, code name and place, never by its words", () => {
  expect(zoneOf(10, 10, 390, 844)).toBe("r1c1");
  expect(zoneOf(389, 843, 390, 844)).toBe("r4c3");
  expect(zoneOf(200, 430, 390, 844)).toBe("r3c2");
  expect(zoneOf(10, 10, 0, 0)).toBeNull();
  html(`
    <section class="leads-table-module__x1Y2z__row">
      <span id="chip" class="leads-table_stageChip__AbC12">Priya Sample · Interested</span>
    </section>
    <div data-sx-feature="workspace_menu"><b id="menu">Sunrise Rooftops</b></div>
    <p id="plain" class="plain">9876543210</p>`);
  const chip = host.querySelector("#chip")!;
  expect(styleOf(chip)).toBe("leads-table.stagechip");
  expect(elementOf(chip)).toBe("leads-table.stagechip");
  expect(elementOf(host.querySelector("#menu")!)).toBe("workspace_menu");
  expect(elementOf(host.querySelector("#plain")!)).toBeNull();
  const place = placeOf(chip);
  expect(place).toMatch(/^[0-9a-f]{8}$/);
  // Two taps on the same chip in another row share the place.
  expect(placeOf(chip)).toBe(place);
  for (const value of [elementOf(chip), place])
    expect(value).not.toMatch(/priya|sunrise|9876/i);
});

it("counts only the time a screen was on view, and says where the page went away", async () => {
  expect(seenSoFar({ seen: 4_000, visibleSince: null }, 9_000)).toBe(4_000);
  expect(seenSoFar({ seen: 4_000, visibleSince: 8_000 }, 9_000)).toBe(5_000);
  const track = vi.spyOn(telemetry, "track");
  const flush = vi.spyOn(telemetry, "flush").mockResolvedValue(undefined);
  const visibility = vi.spyOn(document, "visibilityState", "get");
  visibility.mockReturnValue("visible");
  const root = await mount();
  // Two seconds on Leads, then a call in the dialler for ten seconds.
  now = 3_000;
  visibility.mockReturnValue("hidden");
  document.dispatchEvent(new Event("visibilitychange"));
  expect(tracked(track, "sx.screen_hidden")).toEqual([
    { screen: "leads", kind: "background", seen_ms: 2000 },
  ]);
  now = 13_000;
  visibility.mockReturnValue("visible");
  document.dispatchEvent(new Event("visibilitychange"));
  // Out of view again within half a minute: not sent twice.
  now = 14_000;
  visibility.mockReturnValue("hidden");
  document.dispatchEvent(new Event("visibilitychange"));
  visibility.mockReturnValue("visible");
  now = 15_000;
  document.dispatchEvent(new Event("visibilitychange"));
  expect(tracked(track, "sx.screen_hidden")).toHaveLength(1);
  now = 16_000;
  window.dispatchEvent(new Event("pagehide"));
  // Seen: 2 s, then 1 s, then 1 s: never the time in the dialler.
  expect(tracked(track, "sx.screen_hidden")[1]).toEqual({
    screen: "leads",
    kind: "exit",
    seen_ms: 4_000,
  });
  expect(flush).toHaveBeenCalledWith(true);
  await act(async () => root.unmount());
});

it("times a slow call to its answer's first byte, never one the page spent hidden", () => {
  const origin = "https://app.example";
  const entry = (over: Record<string, unknown> = {}) => ({
    name: `${origin}/v1/conversation-acquisition/submissions/3f2b7d10-aaaa-4bbb-8ccc-0123456789ab/source`,
    initiatorType: "fetch",
    startTime: 1_000,
    duration: 9_000,
    responseStart: 1_300,
    responseEnd: 10_000,
    responseStatus: 200,
    ...over,
  });
  // A recording that took 9 s to download from a server that answered in 0.3 s.
  expect(slowCall(entry(), origin, [])).toBeNull();
  expect(slowCall(entry({ responseStart: 3_000 }), origin, [])).toEqual({
    // Endpoint names stop at 48 characters.
    endpoint: "v1_conversation_acquisition_submissions_id_sourc",
    status: "2xx",
    ms: 9_000,
    wait_ms: 2_000,
  });
  // No first-byte time (an old browser): the whole call counts.
  expect(slowCall(entry({ responseStart: 0 }), origin, [])?.wait_ms).toBe(
    9_000,
  );
  // A server failure is reported however quick.
  expect(
    slowCall(
      entry({ responseStatus: 503, duration: 80, responseEnd: 1_080 }),
      origin,
      [],
    ),
  ).toMatchObject({ status: "5xx", wait_ms: 300 });
  const slow = entry({ responseStart: 4_000 });
  // The page went to the background mid-call, or is still there.
  expect(slowCall(slow, origin, [[5_000, 6_000]])).toBeNull();
  expect(slowCall(slow, origin, [[9_500, null]])).toBeNull();
  expect(slowCall(slow, origin, [[200, 900]])).not.toBeNull();
  expect(slowCall(slow, origin, [[10_001, null]])).not.toBeNull();
  // Not ours: another origin, the telemetry itself, not an API, an image.
  expect(
    slowCall(entry({ name: "https://cdn.example/v1/x" }), origin, []),
  ).toBeNull();
  expect(
    slowCall(
      entry({ name: `${origin}/v1/telemetry/events`, responseStart: 4_000 }),
      origin,
      [],
    ),
  ).toBeNull();
  expect(
    slowCall(
      entry({ name: `${origin}/leads`, responseStart: 4_000 }),
      origin,
      [],
    ),
  ).toBeNull();
  expect(
    slowCall(entry({ initiatorType: "img", responseStart: 4_000 }), origin, []),
  ).toBeNull();
  expect(overlapsHidden([], 0, 10)).toBe(false);
  expect(overlapsHidden([[10, 20]], 0, 10)).toBe(true);
});

it("sends the app's start when idle, with the CPU test and the phone's model", async () => {
  const track = vi.spyOn(telemetry, "track");
  const idle: Array<() => void> = [];
  Object.defineProperty(window, "requestIdleCallback", {
    configurable: true,
    value: (work: () => void) => idle.push(work),
  });
  Object.defineProperty(window, "cancelIdleCallback", {
    configurable: true,
    value: () => undefined,
  });
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 8 Pro Build/SP1A.210812.016; wv) AppleWebKit/537.36 Chrome/130 Mobile Safari/537.36 SalesXrayApp/1.0.30",
  );
  try {
    window.localStorage.removeItem("sx-cpu");
    const root = await mount();
    expect(tracked(track, "sx.app_start")).toEqual([]);
    expect(idle).toHaveLength(1);
    // The clock moves 5 ms each pass of the test from here.
    let clock = 0;
    vi.spyOn(performance, "now").mockImplementation(() => (clock += 2.5));
    await act(async () => idle[0]?.());
    expect(tracked(track, "sx.app_start")).toEqual([
      expect.objectContaining({
        ms: 1_000,
        screen: "leads",
        cpu_ms: 2.5,
        model_label: "redmi-note-8-pro",
      }),
    ]);
    expect(
      JSON.parse(window.localStorage.getItem("sx-cpu") ?? "{}"),
    ).toMatchObject({
      ms: 2.5,
    });
    await act(async () => root.unmount());
  } finally {
    delete (window as { requestIdleCallback?: unknown }).requestIdleCallback;
    delete (window as { cancelIdleCallback?: unknown }).cancelIdleCallback;
  }
});

it("times a Call button from the call's real start, never from a touch on it", async () => {
  // 27 Oct 2026: a third of the company phone's "Call presses" were touches
  // that never became a call (a tap that only stopped a glide, or a swipe).
  const track = vi.spyOn(telemetry, "track");
  html(`<ul><li data-lead-row=""><span>Asha</span>
    <button id="call" data-sx-call="" aria-label="Call Asha">Call</button></li></ul>`);
  expect(actionOf(host.querySelector("#call"))).toBeNull();
  const root = await mount();
  host
    .querySelector("#call")!
    .dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  await act(async () => {
    vi.advanceTimersByTime(1_100);
  });
  expect(tracked(track, "sx.action_timing")).toEqual([]);

  // The call starts: timed from here to the screen settling.
  timeAction("call_start");
  now = 1_300;
  await act(async () => {
    host.append(document.createElement("section"));
  });
  await act(async () => {
    vi.advanceTimersByTime(200);
  });
  expect(tracked(track, "sx.action_timing")).toEqual([
    expect.objectContaining({
      action: "call_start",
      result: "settled",
      ms: 300,
    }),
  ]);
  await act(async () => root.unmount());
  // Unmounted: nothing times any more.
  timeAction("call_start");
  await act(async () => {
    vi.advanceTimersByTime(1_100);
  });
  expect(tracked(track, "sx.action_timing")).toHaveLength(1);
});

it("records every ordinary click as role and grid only, and stops when consent is off", async () => {
  const track = vi.spyOn(telemetry, "track");
  html(
    '<button aria-label="Call Fictional Person">Fictional Person +910000000000</button>',
  );
  const root = await mount();
  for (let i = 0; i < 60; i++)
    host
      .querySelector("button")!
      .dispatchEvent(
        new MouseEvent("click", { bubbles: true, clientX: 10, clientY: 10 }),
      );
  const taps = track.mock.calls.filter(([event]) => event === "sx.tap");
  expect(taps).toHaveLength(60);
  expect(taps[0][1]).toEqual({
    target: "button",
    zone: "r1c1",
    screen: "leads",
  });
  expect(JSON.stringify(taps)).not.toMatch(
    /Fictional|910000000000|clientX|aria/,
  );
  vi.mocked(telemetry.active).mockReturnValue(false);
  host.querySelector("button")!.click();
  expect(track.mock.calls.filter(([event]) => event === "sx.tap")).toHaveLength(
    60,
  );
  await act(async () => root.unmount());
});

it("coalesces nested pane scrolls and records new depth quarters without reading content", async () => {
  const track = vi.spyOn(telemetry, "track");
  const root = await mount();
  const pane = document.createElement("div");
  host.append(pane);
  Object.defineProperties(pane, {
    scrollHeight: { value: 1000 },
    clientHeight: { value: 200 },
  });
  pane.scrollTop = 410;
  for (let i = 0; i < 10; i++) pane.dispatchEvent(new Event("scroll"));
  await act(async () => vi.advanceTimersByTime(250));
  expect(
    track.mock.calls.filter(([event]) => event === "sx.scroll_depth"),
  ).toEqual([["sx.scroll_depth", { depth: 50, screen: "leads" }]]);
  pane.scrollTop = 200;
  pane.dispatchEvent(new Event("scroll"));
  await act(async () => vi.advanceTimersByTime(250));
  expect(
    track.mock.calls.filter(([event]) => event === "sx.scroll_depth"),
  ).toHaveLength(1);
  pane.scrollTop = 800;
  pane.dispatchEvent(new Event("scroll"));
  await act(async () => vi.advanceTimersByTime(250));
  expect(track).toHaveBeenCalledWith("sx.scroll_depth", {
    depth: 100,
    screen: "leads",
  });
  await act(async () => root.unmount());
});

it("keeps fast, repeated, failed and background API timings; masks even lowercase slugs", () => {
  const entry = {
    name: "https://app.example/v1/people/fictional-person?phone=123",
    initiatorType: "fetch",
    startTime: 0,
    duration: 80,
    responseStart: 30,
    responseEnd: 80,
    responseStatus: 200,
  };
  for (let i = 0; i < 100; i++)
    expect(apiTiming(entry, "https://app.example", [])).toEqual({
      endpoint: "v1_people_id",
      status: "2xx",
      band: "lt100",
      background: "no",
    });
  expect(
    apiTiming(entry, "https://app.example", [[10, null]])?.background,
  ).toBe("yes");
  expect(
    apiTiming(
      { ...entry, responseEnd: 0, responseStatus: 0 },
      "https://app.example",
      [],
    )?.status,
  ).toBe("network");
  expect(
    apiTiming(
      { ...entry, name: "https://app.example/v1/telemetry/events" },
      "https://app.example",
      [],
    ),
  ).toBeNull();
  expect(apiTiming(entry, "https://other.example", [])).toBeNull();
  expect(scrollDepth(-5, 1000, 200)).toBe(0);
  expect(scrollDepth(0, 200, 200)).toBe(100);
});

it("captures first/largest paint, repeated masked JS errors and route paint timing", async () => {
  const track = vi.spyOn(telemetry, "track");
  const frames: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", (work: FrameRequestCallback) => {
    frames.push(work);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  try {
    const root = await mount();
    vitals.callback({ name: "FCP", value: 400, rating: "good" });
    vitals.callback({ name: "LCP", value: 900, rating: "good" });
    expect(track).toHaveBeenCalledWith("sx.web_vital", {
      metric: "fcp",
      value: 400,
      rating: "good",
      screen: "leads",
    });
    expect(track).toHaveBeenCalledWith("sx.web_vital", {
      metric: "lcp",
      value: 900,
      rating: "good",
      screen: "leads",
    });
    for (let i = 0; i < 12; i++)
      window.dispatchEvent(
        new ErrorEvent("error", {
          error: new TypeError("Fictional Person +910000000000"),
        }),
      );
    const errors = track.mock.calls.filter(
      ([event]) => event === "sx.js_error",
    );
    expect(errors).toHaveLength(12);
    expect(JSON.stringify(errors)).not.toContain("Fictional");
    frames.shift()!(1000);
    frames.shift()!(1000);
    expect(track).toHaveBeenCalledWith("sx.route_timing", {
      nav: "first",
      band: "1000_3000",
      screen: "leads",
    });
    await act(async () => root.unmount());
  } finally {
    vi.unstubAllGlobals();
  }
});

it("observes every API resource without endpoint cooldown or slow-call sampling", async () => {
  const observers = new Map<
    string,
    (list: { getEntries: () => object[] }) => void
  >();
  class Observer {
    constructor(
      private callback: (list: { getEntries: () => object[] }) => void,
    ) {}
    observe(options: { type: string }) {
      observers.set(options.type, this.callback);
    }
    disconnect() {}
  }
  vi.stubGlobal("PerformanceObserver", Observer);
  try {
    const track = vi.spyOn(telemetry, "track");
    const root = await mount();
    const entry = {
      name: window.location.origin + "/v1/leads",
      initiatorType: "fetch",
      startTime: 0,
      duration: 10,
      responseStart: 5,
      responseEnd: 10,
      responseStatus: 200,
    };
    observers.get("resource")!({
      getEntries: () => Array.from({ length: 65 }, () => entry),
    });
    expect(
      track.mock.calls.filter(([event]) => event === "sx.api_timing"),
    ).toHaveLength(65);
    expect(
      track.mock.calls.filter(([event]) => event === "sx.api_slow"),
    ).toHaveLength(0);
    await act(async () => root.unmount());
  } finally {
    vi.unstubAllGlobals();
  }
});
