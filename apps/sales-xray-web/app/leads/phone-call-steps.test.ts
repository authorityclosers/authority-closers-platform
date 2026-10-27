import { afterEach, expect, it, vi } from "vitest";

const sent = vi.hoisted(() => ({
  track: vi.fn(),
  time: vi.fn(),
}));
vi.mock("../telemetry", () => ({
  screenOf: () => "leads",
  timeAction: sent.time,
  track: sent.track,
}));

import { callStep, reportCallPress } from "./phone-call-steps";

afterEach(() => vi.clearAllMocks());

// 27 Oct 2026: count calls that started, apart from touches that didn't call.
it("counts a real call start, a rescued touch and a touch that placed no call apart", () => {
  reportCallPress("touch");
  reportCallPress("click");
  reportCallPress("rescued");
  reportCallPress("drag");
  reportCallPress("moved");
  reportCallPress("long");
  expect(sent.time.mock.calls).toEqual([["call_start"], ["call_start"]]);
  expect(sent.track.mock.calls.map(([, payload]) => payload)).toEqual([
    { step: "started", via: "touch", screen: "leads" },
    { step: "started", via: "click", screen: "leads" },
    { step: "rescued", screen: "leads" },
    { step: "touch_no_call", why: "drag", screen: "leads" },
    { step: "touch_no_call", why: "moved", screen: "leads" },
    { step: "touch_no_call", why: "long", screen: "leads" },
  ]);
  expect(
    sent.track.mock.calls.every(([name]) => name === "sx.phone_call"),
  ).toBe(true);
});

it("sends the hand-off steps with bounded whole milliseconds and codes only", () => {
  callStep("status", { ms: 41.6 });
  callStep("bridge_ok", { ms: 88, mode: "dialer" });
  callStep("bridge_error", { ms: 999_999, why: "timeout" });
  callStep("fallback_tel");
  expect(sent.track.mock.calls.map(([, payload]) => payload)).toEqual([
    { step: "status", ms: 42, screen: "leads" },
    { step: "bridge_ok", ms: 88, mode: "dialer", screen: "leads" },
    { step: "bridge_error", ms: 60_000, why: "timeout", screen: "leads" },
    { step: "fallback_tel", screen: "leads" },
  ]);
});

it("never lets telemetry stop a call", () => {
  sent.track.mockImplementation(() => {
    throw new Error("down");
  });
  expect(() => reportCallPress("touch")).not.toThrow();
  expect(() => callStep("permits")).not.toThrow();
});
