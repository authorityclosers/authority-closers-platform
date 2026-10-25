// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { telemetry } from "./telemetry";
import { FlowRun, useFlow } from "./telemetry-flows";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let now = 0;

beforeEach(() => {
  now = 1_000;
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(performance, "now").mockImplementation(() => now);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const sent = (send: { mock: { calls: unknown[][] } }) =>
  send.mock.calls.map((call) => call[1] as Record<string, unknown>);

it("sends a run's start, new steps, refused saves and one ending", () => {
  const send = vi.fn();
  const run = new FlowRun("onboarding", "business", () => now, send);
  run.step("start", 0, 5);
  now = 4_000;
  run.step("start", 0, 5); // the same step again: nothing new
  run.step("name", 1, 5);
  run.blocked();
  now = 9_500;
  run.done();
  run.cancel(); // already ended: nothing
  expect(sent(send)).toEqual([
    {
      flow: "onboarding",
      outcome: "start",
      step: "start",
      via: "business",
      index: 0,
      steps: 5,
      ms: 0,
    },
    {
      flow: "onboarding",
      outcome: "step",
      step: "name",
      via: "business",
      index: 1,
      steps: 5,
      ms: 3_000,
    },
    {
      flow: "onboarding",
      outcome: "blocked",
      step: "name",
      via: "business",
      index: 1,
      steps: 5,
      ms: 3_000,
    },
    {
      flow: "onboarding",
      outcome: "done",
      step: "name",
      via: "business",
      index: 1,
      steps: 5,
      ms: 8_500,
    },
  ]);
  expect(run.running).toBe(false);
  expect(send.mock.calls.every((call) => call[0] === "sx.flow")).toBe(true);
});

it("starts a new run after one ends, and clamps counts and time", () => {
  const send = vi.fn();
  const run = new FlowRun("add_lead", "quick", () => now, send);
  run.step("form");
  now = 1_000 + 4_000_000;
  run.done({ step: "save", left: 99 });
  run.step("form");
  run.abandon();
  expect(sent(send)).toEqual([
    { flow: "add_lead", outcome: "start", step: "form", via: "quick", ms: 0 },
    {
      flow: "add_lead",
      outcome: "done",
      step: "save",
      via: "quick",
      left: 20,
      ms: 3_600_000,
    },
    { flow: "add_lead", outcome: "start", step: "form", via: "quick", ms: 0 },
    { flow: "add_lead", outcome: "abandon", step: "form", via: "quick", ms: 0 },
  ]);
});

function Probe({
  active,
  onRun,
}: {
  active: boolean;
  onRun: (run: FlowRun) => void;
}) {
  onRun(useFlow("log_result", { active, via: "after_call" }));
  return null;
}

it("starts when active, and a run still going when the screen closes is left half way", async () => {
  const track = vi.spyOn(telemetry, "track").mockImplementation(() => {});
  const root = createRoot(document.createElement("div"));
  const held: { run?: FlowRun } = {};
  await act(async () =>
    root.render(<Probe active={false} onRun={(value) => (held.run = value)} />),
  );
  expect(track).not.toHaveBeenCalled();
  await act(async () =>
    root.render(<Probe active onRun={(value) => (held.run = value)} />),
  );
  held.run!.step("talk");
  await act(async () => root.unmount());
  await act(async () => {
    vi.runAllTimers();
  });
  expect(
    track.mock.calls.map((call) => (call[1] as { outcome: string }).outcome),
  ).toEqual(["start", "step", "abandon"]);
});

it("counts the page going away as left half way and sends it on the way out", async () => {
  const track = vi.spyOn(telemetry, "track").mockImplementation(() => {});
  const flush = vi.spyOn(telemetry, "flush").mockResolvedValue(undefined);
  const root = createRoot(document.createElement("div"));
  await act(async () => root.render(<Probe active onRun={() => {}} />));
  window.dispatchEvent(new Event("pagehide"));
  expect(track.mock.calls.at(-1)?.[1]).toMatchObject({
    flow: "log_result",
    outcome: "abandon",
  });
  expect(flush).toHaveBeenCalledWith(true);
  await act(async () => root.unmount());
  await act(async () => {
    vi.runAllTimers();
  });
  // Already ended: unmounting sends nothing more.
  expect(
    track.mock.calls.filter(
      (call) => (call[1] as { outcome: string }).outcome === "abandon",
    ),
  ).toHaveLength(1);
});
