// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { telemetry } from "./telemetry";
import { DwellClock, MAX_READ_MS, useSectionDwell } from "./telemetry-dwell";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const CALL = "3f2b7d10-aaaa-4bbb-8ccc-0123456789ab";
let now = 0;
let report: (entries: { isIntersecting: boolean }[]) => void = () => {};
let options: IntersectionObserverInit | undefined;

beforeEach(() => {
  now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(
        callback: typeof report,
        init: IntersectionObserverInit | undefined,
      ) {
        report = callback;
        options = init;
      }
      observe() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (document as { visibilityState?: unknown }).visibilityState;
});

it("counts only readable time, across visits, and caps it", () => {
  let at = 0;
  const clock = new DwellClock(() => at);
  clock.set(true);
  at = 2_000;
  clock.set(false);
  at = 9_000;
  clock.set(true);
  at = 10_500;
  expect(clock.take()).toBe(3_500);
  at = 11_000;
  expect(clock.take()).toBe(500);
  clock.set(false);
  at = 20_000;
  expect(clock.take()).toBe(0);
  clock.set(true);
  at += 3_600_000;
  expect(clock.take()).toBe(MAX_READ_MS);
});

it("sends one section read, with its band, when the section goes", async () => {
  const track = vi.spyOn(telemetry, "track");
  function Section({ callId }: { callId: string | null }) {
    const dwell = useSectionDwell("analysis", {
      callId,
      skill: "d07",
      look: "brain4",
    });
    return <section ref={dwell} />;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Section callId={CALL} />));
  expect(options?.rootMargin).toBe("-40% 0px -40% 0px");

  // A 0.6 s glance, then 41.4 s more across two visits.
  act(() => report([{ isIntersecting: true }]));
  now = 600;
  act(() => report([{ isIntersecting: false }]));
  now = 5_000;
  act(() => report([{ isIntersecting: true }]));
  now = 35_000;
  act(() => report([{ isIntersecting: false }]));
  now = 50_000;
  act(() => report([{ isIntersecting: true }]));
  now = 61_400;
  await act(async () => root.unmount());

  expect(track).toHaveBeenCalledTimes(1);
  expect(track).toHaveBeenCalledWith("sx.section_read", {
    call_id: CALL,
    section: "analysis",
    read_band: "30_120s",
    dwell_ms: 41_400 + 600,
    skill: "d07",
    look: "brain4",
  });
});

it("sends when the page is hidden; hidden time and reads under a second are not sent", async () => {
  const track = vi.spyOn(telemetry, "track");
  const flush = vi.spyOn(telemetry, "flush").mockResolvedValue(undefined);
  let state: DocumentVisibilityState = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  function Section({ callId }: { callId: string | null }) {
    return <div ref={useSectionDwell("overview", { callId })} />;
  }
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Section callId={CALL} />));
  act(() => report([{ isIntersecting: true }]));
  now = 3_000;
  state = "hidden";
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(track).toHaveBeenCalledWith(
    "sx.section_read",
    expect.objectContaining({
      section: "overview",
      read_band: "under_5s",
      dwell_ms: 3_000,
    }),
  );
  expect(flush).toHaveBeenCalledWith(true);
  // Hidden time is not read time.
  now = 60_000;
  await act(async () => root.render(<Section callId={null} />));
  expect(track).toHaveBeenCalledTimes(1);
  await act(async () => root.unmount());
  expect(track).toHaveBeenCalledTimes(1);
});
