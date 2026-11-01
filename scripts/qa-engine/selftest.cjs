// Pure self-test for the QA robot: no browser, no server, no network. Run by tests/unit/ci/test_qa_engine.py.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { normSelector } = require("./lib/util.cjs");
const inv = require("./lib/invariants.cjs");
const cfg = require("./lib/config.cjs");

// the semantic selector is text
assert.strictEqual(typeof normSelector('button "Call 98765 43210"'), "string");

// the roll-up: one report per page, rule and viewport, with the viewport as the selector
const finding = (selector, shot) => ({ rule: "layout:tap-target-44", selector, severity: "POLISH", summary: "s", detail: `${selector} is 30x30px`, route: "/leads", shot });
const rolled = inv.rollup([finding("button A", "css-a"), finding("button B", "css-b"), { rule: "page:blank", selector: "main", severity: "MAJOR", summary: "s", detail: "d", route: "/leads" }], "390");
assert.strictEqual(rolled.length, 2);
const tap = rolled.find((f) => f.rule === "layout:tap-target-44");
assert.strictEqual(tap.selector, "@390");
assert.strictEqual(tap.count, 2);
assert.deepStrictEqual(tap.shotAll, ["css-a", "css-b"]);
assert.ok(rolled.some((f) => f.rule === "page:blank" && f.selector !== "@390"));

// a blank page is a finding, a page with text is not
const base = { textLength: 0, overflow: { sw: 390, cw: 390, items: [] }, covered: [], overlaps: [], clipped: [], small: [], selects: [], emptyLists: [] };
assert.ok(inv.findingsFrom(base, { route: "/leads", phone: true }).some((f) => f.rule === "page:blank"));
assert.ok(!inv.findingsFrom({ ...base, textLength: 300 }, { route: "/leads", phone: true }).some((f) => f.rule === "page:blank"));

// the click map: 99 unique destinations, each with a kind and what that kind needs
const map = JSON.parse(fs.readFileSync(path.join(__dirname, "data", "click-map.json"), "utf8"));
const ids = new Set();
const kinds = new Set(["nav", "select", "sheet", "back", "option", "present", "todo", "lead-close"]);
assert.strictEqual(map.destinations.length, 99);
for (const d of map.destinations) {
  assert.ok(!ids.has(d.id), `duplicate id ${d.id}`);
  ids.add(d.id);
  assert.ok(kinds.has(d.kind), `${d.id}: unknown kind ${d.kind}`);
  if (d.kind !== "todo") {
    assert.ok(d.start && d.control && d.control.role && d.control.name, `${d.id}: needs a start and a control`);
    if (d.kind === "nav") assert.ok(d.expect && d.expect.path, `${d.id}: a navigation needs an expected path`);
    if (d.kind === "option") assert.ok(d.option, `${d.id}: an option needs its name`);
  }
}

// the configuration: sizes the robot can open, areas that route to a builder, limits that keep it polite
for (const size of ["390 px", "360 px", "1440", "1920"]) assert.ok(cfg.DEVICES[size] && cfg.DEVICES[size].viewport, size);
assert.ok(cfg.REPORT_AREAS.Leads && cfg.REPORT_AREAS.Home);
assert.ok(cfg.LIMITS.contexts >= 1 && cfg.LIMITS.reportsPerPersonaPerHour <= 60);
assert.ok(cfg.PROXY.startsWith("http"));

console.log("qa-engine selftest ok");
