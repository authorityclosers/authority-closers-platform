// node --test scripts/ci/wb_overlap_lib.test.mjs: the phone overlap check's own rules.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  collides,
  crossing,
  inPage,
  overlapStates,
  summarise,
  tagOfState,
} from "./wb_overlap_lib.mjs";

const box = (left, top, width, height) => ({ left, top, right: left + width, bottom: top + height });

test("runs every width, text size and theme the owner asked for", () => {
  const states = overlapStates();
  assert.equal(states.length, 12);
  assert.deepEqual([...new Set(states.map((s) => s.width))], [360, 363, 412]);
  assert.deepEqual([...new Set(states.map((s) => s.scale))], [1, 1.3]);
  assert.deepEqual([...new Set(states.map((s) => s.theme))], ["light", "dark"]);
  assert.equal(tagOfState({ width: 360, scale: 1.3, theme: "dark" }), "360 130% dark");
});

test("measures what two boxes share", () => {
  assert.deepEqual(crossing(box(0, 0, 10, 10), box(5, 5, 10, 10)), { width: 5, height: 5 });
  assert.deepEqual(crossing(box(0, 0, 10, 10), box(20, 20, 10, 10)), { width: 0, height: 0 });
});

test("text drawn into other text collides; neighbours and stacked lines don't", () => {
  // "Unworked" running into "Follow-up" on the same line (the stage strip, 17 Nov 2026).
  assert.equal(collides(box(10, 300, 60, 16), box(52, 300, 50, 16)), true);
  // Side by side, touching.
  assert.equal(collides(box(10, 300, 60, 16), box(70, 300, 50, 16)), false);
  // Two lines in a tight line height share a pixel or two of their glyph boxes.
  assert.equal(collides(box(10, 300, 60, 20), box(10, 316, 60, 20)), false);
  // A sliver under 1.5 px across is rounding, not a collision.
  assert.equal(collides(box(10, 300, 60, 16), box(69, 300, 50, 16)), false);
});

test("summarises only the states with findings, errors first", () => {
  const clean = { page: "leads-list", state: "360 100% light", overlaps: [], clipped: [] };
  const bad = {
    page: "lead-page",
    state: "360 130% light",
    overlaps: [{ a: "span.stepLabel", b: "span.stepLabel" }],
    clipped: [],
  };
  const broken = { page: "lead-page", state: "412 100% dark", overlaps: [], clipped: [], error: "timeout" };
  const lines = summarise([clean, bad, broken]);
  assert.equal(lines.length, 2);
  assert.match(lines[0], /could not measure \(timeout\)/);
  assert.match(lines[1], /1 overlapping, 0 clipped · span\.stepLabel x span\.stepLabel/);
  assert.deepEqual(summarise([clean]), []);
});

test("sends the scan to the page as one expression with the same collision rule", () => {
  const expression = inPage("[data-lead-page]");
  assert.match(expression, /^\(function scanOverlaps\(rootSelector, hit\)/);
  assert.ok(expression.includes('"[data-lead-page]"'));
  assert.ok(expression.includes("minShare"));
});
