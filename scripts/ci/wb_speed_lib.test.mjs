import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";

import {
  ACTIONS,
  LIMITS,
  RATES,
  SPEED_INIT,
  SPEED_SCREENS,
  classify,
  median,
  perfKey,
  pickSpeedScreens,
  speedMarkdown,
  summarize,
} from "./wb_speed_lib.mjs";

test("times a phone at 1x, 4x and 6x CPU on the key screens, the actions telemetry names", () => {
  assert.deepEqual(RATES, [1, 4, 6]);
  assert.ok(
    ["leads", "report", "calls", "home"].every((key) => SPEED_SCREENS[key]),
  );
  assert.ok(
    Object.values(SPEED_SCREENS).every((s) =>
      s.path.startsWith("/perf-fixture/"),
    ),
  );
  // telemetry-auto.tsx actionOf: a lead row, a tab, a dialog trigger.
  assert.equal(ACTIONS.lead_open, "[data-lead-row]");
  assert.match(ACTIONS.tab_switch, /role="tab"/);
  assert.equal(ACTIONS.sheet_open, '[aria-haspopup="dialog"]');
  assert.deepEqual(
    pickSpeedScreens(["report", "nope"]).map(([key]) => key),
    ["report"],
  );
  assert.equal(
    pickSpeedScreens(["/review-fixture/leads"]).length,
    Object.keys(SPEED_SCREENS).length,
  );
  assert.equal(perfKey("leads", "lead_open"), "perf:leads:lead_open");
});

test("medians ignore taps that changed nothing and runs that failed", () => {
  assert.equal(median([300, 100, 200]), 200);
  assert.equal(median([100, 200]), 150);
  assert.equal(median([]), null);
  const rows = summarize([
    {
      screen: "leads",
      action: "lead_open",
      rate: 6,
      ms: 900,
      result: "settled",
    },
    {
      screen: "leads",
      action: "lead_open",
      rate: 6,
      ms: 1300,
      result: "settled",
    },
    {
      screen: "leads",
      action: "lead_open",
      rate: 6,
      ms: 10000,
      result: "timeout",
    },
    {
      screen: "leads",
      action: "lead_open",
      rate: 6,
      ms: 0,
      result: "no_change",
    },
    {
      screen: "leads",
      action: "load",
      rate: 6,
      ms: 2500,
      lcp: 1800,
      tbt: 400,
      result: "settled",
    },
    { screen: "leads", action: "load", rate: 6, result: "failed" },
  ]);
  const tap = rows.find((row) => row.action === "lead_open").rates[6];
  assert.equal(tap.median, 1300);
  assert.deepEqual([tap.runs, tap.capped, tap.no_change], [3, 1, 1]);
  const page = rows.find((row) => row.action === "load").rates[6];
  assert.deepEqual(
    [page.median, page.lcp, page.tbt, page.failed],
    [2500, 1800, 400, 1],
  );
});

test("slow on a low-end phone is a card; over the builder's limit is for the builder", () => {
  const rows = summarize([
    { screen: "report", action: "load", rate: 6, ms: 5200, result: "settled" },
    { screen: "report", action: "load", rate: 4, ms: 3600, result: "settled" },
    {
      screen: "leads",
      action: "lead_open",
      rate: 6,
      ms: 1100,
      result: "settled",
    },
    {
      screen: "leads",
      action: "tab_switch",
      rate: 6,
      ms: 400,
      result: "settled",
    },
    { screen: "home", action: "load", rate: 6, ms: 2900, result: "settled" },
  ]);
  const found = classify(rows);
  assert.deepEqual(
    found.map((f) => [f.key, f.severity, f.ms, f.at4]),
    [
      ["perf:report:load", "builder", 5200, 3600],
      ["perf:leads:lead_open", "slow", 1100, null],
    ],
  );
  assert.equal(LIMITS.tap.builder, 2000);
});

test("the report lists every screen and action at each rate, and what is slow", () => {
  const rows = summarize([
    { screen: "leads", action: "load", rate: 1, ms: 600, result: "settled" },
    { screen: "leads", action: "load", rate: 4, ms: 1900, result: "settled" },
    {
      screen: "leads",
      action: "load",
      rate: 6,
      ms: 15000,
      result: "timeout",
      lcp: 2600,
      tbt: 900,
    },
  ]);
  const text = speedMarkdown({
    rows,
    findings: classify(rows),
    failures: ["chats at 6x, run 1: Timeout"],
    source_sha: "0123456789abcdef",
  });
  assert.match(
    text,
    /\| Leads, All \| opening the screen \| 600 \| 1900 \| 15000\+ \| 2600 \| 900 \| \*\*for the builder\*\* \|/,
  );
  assert.match(
    text,
    /`perf:leads:load` Leads, All, opening the screen: 15000 ms at 6x \(1900 at 4x, 600 at 1x\)/,
  );
  assert.match(text, /- chats at 6x, run 1: Timeout/);
  assert.match(text, /for `0123456789ab`/);
});

test("the page hooks run before any script and keep the last change, LCP, blocking and the tap", () => {
  const listeners = {};
  const window = {};
  const context = {
    window,
    document: {},
    performance: { now: () => 42 },
    MutationObserver: class {
      constructor(callback) {
        this.callback = callback;
      }
      observe() {
        this.callback();
      }
    },
    PerformanceObserver: class {
      observe() {}
    },
    addEventListener: (name, handler) => (listeners[name] = handler),
  };
  vm.runInNewContext(SPEED_INIT, context);
  assert.equal(window.__speed.last, 42);
  listeners.pointerdown({ timeStamp: 7 });
  assert.equal(window.__speed.tap, 7);
});
