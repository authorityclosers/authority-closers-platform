// node --test scripts/ci/wb_readability_lib.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CORNERS,
  JUNK,
  LONG,
  SCREENS,
  baselineFrom,
  cellOf,
  compare,
  isJunk,
  loads,
  nameOf,
  namesOf,
  pick,
  plainClass,
  plainSelector,
  reportMarkdown,
  stressDomInPage,
  stressScript,
  stressValue,
  union,
} from "./wb_readability_lib.mjs";

const long = (key, value) => stressValue(key, value, LONG, pick);

test("the gate runs 20 screens at the four corner states, plain and long", () => {
  assert.equal(SCREENS.length, 20);
  assert.equal(new Set(SCREENS.map((s) => s.key)).size, 20);
  assert.deepEqual(
    CORNERS.map((c) => c.key),
    ["360 dark 130%", "360 light 100%", "1280 light", "1280 dark"],
  );
  assert.equal(loads().length, 20 * 4 * 2);
  assert.equal(cellOf(loads()[0]), "home | plain | 360 dark 130%");
  for (const screen of SCREENS) assert.match(screen.path, /^\/review-fixture\//);
});

test("a finding's name drops build hashes and positions, never keeps on-screen text", () => {
  assert.equal(plainClass("leads-module__Ab12Cd__row"), "leads:row");
  assert.equal(
    plainSelector("div.leads-module__Ab12Cd__row:nth-child(3) > span.name"),
    "div.leads:row > span.name",
  );
  assert.equal(nameOf({ check: "overlap", selector: "a.x  b.y" }), "overlap | a.x > b.y");
  // An id React makes up for one render is not part of a finding's name.
  assert.equal(plainSelector("#_r_0_-heading-overview"), "#:id:-heading-overview");
  assert.equal(plainSelector("#_R_eatpesncflb_-heading-overview"), "#:id:-heading-overview");
  assert.equal(plainSelector("#\\:r1\\:-label"), "#:id:-label");
  assert.equal(plainSelector("#report-title"), "#report-title");
  // The same button, named by axe with whichever attribute made it unique at the time.
  assert.equal(
    plainSelector('.x > .y[data-open-review="14"][type="button"]'),
    plainSelector('.x > .y[data-open-review="14"][data-reach=""]'),
  );
  assert.equal(plainSelector('.y[data-open-review="14"][data-reach]'), '.y[data-open-review="14"]');
  assert.deepEqual(
    namesOf([
      { check: "b", selector: "x" },
      { check: "a", selector: "x" },
      { check: "b", selector: "x" },
    ]),
    ["a | x", "b | x"],
  );
});

test("only what is new against the baseline blocks; a cell not measured is left alone", () => {
  const baseline = { one: ["a | x", "b | y"], two: ["c | z"] };
  const { fresh, gone } = compare({ one: ["a | x", "d | w"] }, baseline);
  assert.deepEqual(fresh, [{ cell: "one", name: "d | w" }]);
  assert.deepEqual(gone, [{ cell: "one", name: "b | y" }]);
  assert.deepEqual(compare({ one: ["a | x", "b | y"] }, baseline), { fresh: [], gone: [] });
  assert.deepEqual(compare({ three: ["n | m"] }, baseline).fresh, [{ cell: "three", name: "n | m" }]);
});

test("two runs fold into one baseline", () => {
  assert.deepEqual(union({ one: ["b", "a"] }, { one: ["c", "a"], two: ["z"] }), {
    one: ["a", "b", "c"],
    two: ["z"],
  });
});

test("a baseline from several recording runs knows what any of them saw", () => {
  const { cells, errors } = baselineFrom([
    [
      { cell: "one", names: ["a | x"] },
      { cell: "two", error: "timeout" },
    ],
    [
      { cell: "one", names: ["b | y"] },
      { cell: "two", names: ["c | z"] },
    ],
  ]);
  assert.deepEqual(cells, { one: ["a | x", "b | y"], two: ["c | z"] });
  assert.deepEqual(errors, ["two: timeout"]);
});

test("junk is whole words a person should never read", () => {
  for (const text of ["undefined", "Due NaN days", "[object Object]", "Invalid Date", "null", "Owner: null"])
    assert.ok(isJunk(text), text);
  for (const text of ["Undefined behaviour", "Nullable", "Banana", "No leads yet", "nullify"])
    assert.ok(!isJunk(text), text);
  assert.ok(JUNK.test("�"));
});

test("long data: names, companies, labels, amounts and 100% grow; ids, dates, links and enums stay", () => {
  assert.ok(LONG.people.includes(long("owner_name", "Priya Nair")));
  assert.ok(long("name", "Asha Rao").length >= 40);
  assert.equal(long("name", "Asha Rao"), long("name", "Asha Rao"));
  assert.ok(LONG.companies.includes(long("company", "Demo Textiles")));
  assert.equal(long("label", "Interested"), `Interested${LONG.labelTail}`);
  assert.equal(long("city", "Pune"), LONG.place);
  assert.equal(long("amount", 185000), LONG.amount);
  assert.equal(long("win_percent", 42), 100);
  assert.ok(long("note", "Call back tomorrow").startsWith("Call back tomorrow"));
  assert.ok(/[ऀ-ॿ]/.test(LONG.people.join("") + LONG.sentence));
  for (const [key, value] of [
    ["id", "00000000-0000-4000-8000-000000000300"],
    ["stage", "meeting_scheduled"],
    ["created_at", "2026-10-03T12:00:00Z"],
    ["href", "/leads?tab=all"],
    ["phone", "+91 00000 60001"],
    ["email", "asha@example.com"],
    ["count", 12],
    ["amount", 0],
    ["name", ""],
  ])
    assert.equal(long(key, value), value, key);
});

test("the long-data script is one self-contained expression", () => {
  const script = stressScript();
  assert.match(script, /^\(function stressInit/);
  assert.ok(script.includes(LONG.place));
  // It runs with nothing from this module in scope.
  const window = { fetch: async () => new Response('{"owner_name":"Priya Nair","id":"abc"}', { headers: { "content-type": "application/json" } }) };
  new Function("window", "Response", script)(window, Response);
  window.fetch = async () =>
    new Response('{"owner_name":"Priya Nair","stage":"new"}', { headers: { "content-type": "application/json" } });
  return window
    .fetch("/v1/x")
    .then((r) => r.json())
    .then((data) => {
      assert.ok(LONG.people.includes(data.owner_name));
      assert.equal(data.stage, "new");
      assert.equal(window.__stressed, 1);
    });
});

test("the in-page long-data pass is one self-contained expression", () => {
  const script = stressDomInPage();
  assert.match(script, /^\(function stressDom/);
  assert.ok(script.includes(LONG.people[0]));
  assert.ok(script.includes("12,34,56,789"));
});

test("the report says green, red or recording, and lists what is new", () => {
  const rows = [
    { cell: "home | plain | 1280 light", screen: "home", variant: "plain", names: ["overlap | a.x"] },
    { cell: "home | long | 1280 light", screen: "home", variant: "long", names: [], stressed: 0 },
  ];
  const green = reportMarkdown({ rows, fresh: [], gone: [], recorded: false, baselineCells: 2 });
  assert.match(green, /\*\*Green\.\*\*/);
  assert.match(green, /Long data did not reach: home/);
  assert.match(reportMarkdown({ rows: [{ ...rows[0], chars: 40 }], fresh: [], gone: [], recorded: false, baselineCells: 1 }), /Thin screens[^:]*: home/);
  const red = reportMarkdown({
    rows,
    fresh: [{ cell: "home | plain | 1280 light", name: "overlap | a.x" }],
    gone: [],
    recorded: false,
    baselineCells: 2,
  });
  assert.match(red, /\*\*Red\.\*\* 1 new finding/);
  assert.match(red, /\| home, plain, 1280 light \| overlap \| `a\.x` \|/);
  assert.match(reportMarkdown({ rows, fresh: [], gone: [], recorded: true, baselineCells: 0 }), /only records/);
});
