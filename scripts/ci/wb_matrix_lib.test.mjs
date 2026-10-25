import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SCREENS,
  onSheet,
  pickScreens,
  report,
  states,
  statesFor,
  tagOf,
  viewportOf,
  zoomOf,
} from "./wb_matrix_lib.mjs";

test("covers 7 sizes, 85 to 130% font scale both ways, and both themes", () => {
  const all = states();
  assert.equal(all.length, 7 * 6 * 2);
  assert.deepEqual(
    [...new Set(all.map((state) => state.label))],
    [
      "320x640",
      "360x640",
      "360x800",
      "390x844",
      "412x915",
      "430x932",
      "768x1024",
    ],
  );
  assert.deepEqual(
    [...new Set(all.map((state) => `${state.scale} ${state.mode}`))],
    ["1 app", "0.85 text", "1.15 text", "1.3 text", "1.15 app", "1.3 app"],
  );
  assert.deepEqual(
    [...new Set(all.map((state) => state.theme))],
    ["light", "dark"],
  );
});

test("zooms like the Android app: clamped to 1-1.2, so 130% on 360 px leaves 300 CSS px", () => {
  const phone = { width: 360, height: 800 };
  assert.equal(zoomOf({ ...phone, scale: 1.3, mode: "app" }), 1.2);
  assert.equal(zoomOf({ ...phone, scale: 0.85, mode: "app" }), 1);
  assert.equal(zoomOf({ ...phone, scale: 1.3, mode: "text" }), 1);
  assert.deepEqual(viewportOf({ ...phone, scale: 1.3, mode: "app" }), {
    width: 300,
    height: 667,
  });
  assert.deepEqual(viewportOf({ ...phone, scale: 1.15, mode: "text" }), {
    width: 360,
    height: 800,
  });
});

test("keeps four states per size on a contact sheet", () => {
  const sheet = states().filter(onSheet);
  assert.equal(sheet.length, 7 * 4);
  assert.equal(
    tagOf("leads-table", {
      label: "360x800",
      scale: 1.3,
      mode: "app",
      theme: "light",
    }),
    "leads-table 360x800 130% app light",
  );
});

test("picks named screens or fixture paths, and refuses anything else", () => {
  assert.equal(pickScreens().length, Object.keys(SCREENS).length);
  assert.deepEqual(
    pickScreens(["leads-table"]).map(([key]) => key),
    ["leads-table"],
  );
  assert.deepEqual(pickScreens(["/review-fixture/plans?x=1"]), [
    ["review-fixture-plans-x-1", { path: "/review-fixture/plans?x=1" }],
  ]);
  assert.throws(
    () => pickScreens(["leads-everything"]),
    /unknown matrix screen/,
  );
});

test("reports, per screen, how many states had each problem and where", () => {
  const base = { label: "360x800", scale: 1, mode: "app", theme: "light" };
  const text = report(
    [
      {
        key: "lead-sheet",
        tag: "lead-sheet a",
        ...base,
        overflow: false,
        spill: ["WhatsApp (text 64 in 60)"],
        small: [],
      },
      {
        key: "lead-sheet",
        tag: "lead-sheet b",
        ...base,
        overflow: true,
        spill: [],
        small: ["Note 40x40"],
      },
      {
        key: "home",
        tag: "home a",
        ...base,
        failed: "Timeout 90000ms exceeded.",
      },
    ],
    "0123456789abcdef",
  );
  assert.match(text, /3 states on 2 screens .* for `0123456789ab`/);
  assert.match(text, /\| lead-sheet \| 0 \| 1 \| 0 \| 1 \|/);
  assert.match(text, /\| home \| 1 \|/);
  assert.match(text, /- spill: "WhatsApp \(text 64 in 60\)" \[lead-sheet a\]/);
  assert.match(text, /- failed: Timeout 90000ms exceeded. \[home a\]/);
});

test("adds computer states only for a screen that asks", () => {
  assert.equal(statesFor({ path: "/x" }).length, states().length);
  const desk = statesFor({ path: "/x", desktop: true }).filter(
    (state) => state.desktop,
  );
  // 1280, 1440, 1920 x 100% and three text scales x light and dark: the computer states.
  assert.equal(desk.length, 3 * 4 * 2);
  assert.ok(desk.every((state) => state.mode === "text" || state.scale === 1));
});
