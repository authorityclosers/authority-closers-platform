import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";

import {
  CHECKS,
  chooseTaps,
  cleanClass,
  componentOf,
  contrastRatio,
  cropBox,
  dedupe,
  findingKey,
  fixtureKey,
  groupFindings,
  groupKeyOf,
  helperScript,
  hex,
  isLarge,
  labelish,
  leaves,
  moduleOf,
  namesOut,
  normalizeMessage,
  over,
  parseColor,
  pathOf,
  pickRadarScreens,
  radarLoads,
  radarScreens,
  screenLoads,
  radarStates,
  reportMarkdown,
  risky,
  sameTarget,
  scrub,
  shardOf,
  stateTag,
} from "./wb_radar_lib.mjs";

/** A tiny stand-in for a DOM element: enough for the path and label helpers. */
function el(
  tag,
  {
    id = "",
    role = null,
    classes = [],
    data = [],
    text = "",
    aria = null,
    parent = null,
  } = {},
) {
  const attrs = {
    ...(role ? { role } : {}),
    ...(aria ? { "aria-label": aria } : {}),
  };
  for (const name of data) attrs[name] = "";
  return {
    tagName: tag.toUpperCase(),
    id,
    classList: classes,
    className: classes.join(" "),
    attributes: Object.keys(attrs).map((name) => ({ name })),
    getAttribute: (name) => attrs[name] ?? null,
    innerText: text,
    parentElement: parent,
  };
}

test("checks 3 phones at three scales, 1280 at two and the Android app, light and dark: 24 states in 16 loads", () => {
  assert.equal(radarStates().length, 24);
  assert.equal(radarLoads().length, 16);
  // The Android app: its user agent and font-scale handshake on a 360 px phone, the CPU 4x slower.
  const android = radarLoads().filter((load) => load.android);
  assert.deepEqual(
    android.map((load) => load.theme),
    ["light", "dark"],
  );
  for (const load of android) {
    assert.equal(load.size.width, 360);
    assert.match(load.android.userAgent, /\bSalesXrayApp\/\d/);
    assert.equal(load.android.fontScale, 1.2);
    assert.equal(load.android.cpu, 4);
    assert.equal(
      stateTag(load.states[0]),
      `360x800 120% android ${load.theme}`,
    );
  }
  const labels = new Set(radarStates().map((state) => state.label));
  assert.deepEqual([...labels], ["320x640", "360x800", "390x844", "1280x800"]);
  // The app's zoom is a phone's; the computer gets 100% and 130% text only.
  assert.ok(
    !radarStates().some((s) => s.desktop && s.mode === "app" && s.scale !== 1),
  );
  assert.equal(
    stateTag({ label: "320x640", scale: 1.3, mode: "text", theme: "dark" }),
    "320x640 130% text dark",
  );
  // 130% text is measured on the same load as 100%, after it.
  for (const load of radarLoads().filter((l) => l.zoom === 1 && !l.android))
    assert.deepEqual(
      load.states.map((s) => s.scale),
      [1, 1.3],
    );
});

test("sweeps every named screen and every other fixture page, sharded round-robin", () => {
  const screens = {
    "leads-all": { path: "/review-fixture/leads?tab=all" },
    kit: { path: "/review-fixture/kit-old" },
  };
  const all = radarScreens(screens, [
    "/review-fixture/leads",
    "/review-fixture/kit",
    "/review-fixture/report/story",
  ]);
  assert.deepEqual(
    all.map(([key, screen]) => `${key} ${screen.path}`),
    [
      "leads-all /review-fixture/leads?tab=all",
      "kit /review-fixture/kit-old",
      "kit-page /review-fixture/kit",
      "report-story /review-fixture/report/story",
    ],
  );
  assert.equal(fixtureKey("/review-fixture/report-review"), "report-review");
  assert.deepEqual(
    pickRadarScreens(["kit-page"], screens, ["/review-fixture/kit"]).map(
      ([key]) => key,
    ),
    ["kit-page"],
  );
  assert.throws(
    () => pickRadarScreens(["nope"], screens, []),
    /unknown radar screen/,
  );
  const parts = [0, 1, 2].map((i) => shardOf(all, i, 3).map(([key]) => key));
  assert.deepEqual(parts, [
    ["leads-all", "report-story"],
    ["kit"],
    ["kit-page"],
  ]);
});

test("colours: WCAG ratios, alpha over a background, large text", () => {
  assert.equal(contrastRatio([0, 0, 0], [255, 255, 255]).toFixed(1), "21.0");
  assert.equal(
    contrastRatio([118, 118, 118], [255, 255, 255]).toFixed(2),
    "4.54",
  );
  assert.ok(contrastRatio([156, 163, 175], [255, 255, 255]) < 3);
  assert.deepEqual(
    over([0, 0, 0, 0.5], [255, 255, 255, 1]),
    [127.5, 127.5, 127.5, 1],
  );
  assert.ok(
    isLarge(24, 400) &&
      isLarge(19, 700) &&
      !isLarge(18, 700) &&
      !isLarge(16, 400),
  );
  assert.equal(hex([107, 114, 128, 1]), "#6b7280");
  assert.deepEqual(parseColor("rgba(10, 20, 30, 0.25)"), [10, 20, 30, 0.25]);
  assert.deepEqual(parseColor("rgb(1 2 3 / 50%)"), [1, 2, 3, 0.5]);
  assert.deepEqual(parseColor("transparent"), [0, 0, 0, 0]);
});

test("element paths drop build hashes, bare wrappers and row text", () => {
  assert.equal(
    cleanClass("lightbox-shell-module__3nIbHW__tabPill"),
    "lightbox-shell__tabPill",
  );
  assert.equal(
    cleanClass("workspace-picker-module__UvZe-W__tile"),
    "workspace-picker__tile",
  );
  assert.equal(cleanClass("lucide"), null);
  assert.equal(cleanClass("css-1x2y3z"), null);
  assert.equal(cleanClass("sales-xray-document"), "sales-xray-document");
  const main = el("main", { id: "main-content" });
  const wrap = el("div", { parent: main });
  const strip = el("div", {
    role: "tablist",
    classes: ["leads-desk-module__aB1cD2__tabs"],
    parent: wrap,
  });
  const tab = el("button", {
    role: "tab",
    classes: ["lucide", "leads-desk-module__aB1cD2__tab"],
    data: ["data-sx-equal"],
    text: "All leads",
    parent: strip,
  });
  assert.equal(
    pathOf(tab),
    "main#main-content > div[role=tablist].leads-desk__tabs > button[role=tab][data-sx-equal].leads-desk__tab",
  );
  // React's generated ids and positions never reach a key.
  assert.equal(
    pathOf(el("span", { id: "«r1»", parent: el("li") })),
    "li > span",
  );
  // React 19.1's useId ("_r_a_") too; a real id stays.
  assert.equal(pathOf(el("h3", { id: "_r_a_", parent: el("li") })), "li > h3");
  assert.equal(
    pathOf(el("h3", { id: "root", parent: el("li") })),
    "li > h3#root",
  );
  assert.ok(
    labelish(
      el("span", { classes: ["lightbox-shell-module__3nIbHW__tabPill"] }),
    ),
  );
  assert.ok(labelish(el("span", { classes: ["chip"] })));
  assert.ok(
    !labelish(el("table", { classes: ["leads-table-module__x1y2z3__table"] })),
  );
});

test("the page gets the helpers as one script, with nothing missing", () => {
  const window = {};
  vm.runInNewContext(helperScript(), { window });
  const R = window.__radar;
  assert.equal(R.contrastRatio([0, 0, 0], [255, 255, 255]).toFixed(0), "21");
  assert.equal(R.cleanClass("sheet-module__NvWf5a__panel"), "sheet__panel");
  assert.equal(
    R.pathOf(el("button", { role: "tab", parent: el("nav") })),
    "nav > button[role=tab]",
  );
  assert.ok(R.risky("Delete lead") && !R.risky("Calls"));
  assert.equal(R.scrub("Pro ₹4,999 a month"), "Pro [amount] a month");
});

test("never taps what deletes, sends, calls, pays or leaves the app", () => {
  for (const label of [
    "Delete lead",
    "Remove",
    "Log out",
    "Sign out",
    "Send",
    "Call Asha",
    "WhatsApp",
    "Pay now",
    "Upgrade",
  ])
    assert.ok(risky(label), label);
  for (const label of [
    "Calls",
    "All leads",
    "Stages",
    "Recorded calls",
    "Settings",
  ])
    assert.ok(!risky(label), label);
  const origin = "http://127.0.0.1:18216";
  assert.ok(leaves("tel:+910000000000", origin));
  assert.ok(leaves("https://wa.me/910000000000", origin));
  assert.ok(leaves("https://example.com/x", origin));
  assert.ok(leaves("/x", origin, "_blank"));
  assert.ok(!leaves("/review-fixture/leads?tab=all", origin));
  assert.ok(!leaves("#notes", origin));
  assert.equal(
    scrub("₹1,200 and Rs. 300 and $5"),
    "[amount] and [amount] and [amount]",
  );
});

test("taps one or two of a repeated control, every tab, at most the cap", () => {
  const rows = Array.from({ length: 5 }, (_, i) => ({
    selector: "li > button.row",
    label: `Lead ${i}`,
    index: 0,
  }));
  const tabs = Array.from({ length: 4 }, (_, i) => ({
    selector: "button[role=tab]",
    label: `Tab ${i}`,
    index: 0,
    tabLike: true,
  }));
  const { chosen, skipped } = chooseTaps([
    ...rows,
    ...tabs,
    { selector: "button.x", label: "Delete", index: 0, skip: "risky" },
    { selector: "a", label: "Call", index: 0, skip: "leaves" },
  ]);
  assert.equal(
    chosen.filter((t) => t.selector === "li > button.row").length,
    2,
  );
  assert.equal(chosen.filter((t) => t.tabLike).length, 4);
  assert.deepEqual(skipped, { risky: 1, leaves: 1, repeat: 3, cap: 0 });
  assert.equal(chooseTaps(tabs, 2).chosen.length, 2);
  assert.ok(
    sameTarget(
      { selector: "a", label: "x", index: 1 },
      { selector: "a", label: "x", index: 1, id: "9" },
    ),
  );
  assert.ok(
    !sameTarget(
      { selector: "a", label: "x", index: 1 },
      { selector: "a", label: "x", index: 0 },
    ),
  );
});

test("crops stay inside the viewport with some context around the element", () => {
  const viewport = { width: 320, height: 640 };
  // Past the right edge: clamped to the viewport, 40 px above and below, at least 140 tall.
  assert.deepEqual(cropBox({ l: 100, t: 50, r: 400, b: 90 }, viewport), {
    x: 40,
    y: 0,
    width: 280,
    height: 140,
  });
  // A small chip mid-screen: grown to 280 x 140 around it.
  assert.deepEqual(cropBox({ l: 150, t: 300, r: 170, b: 320 }, viewport), {
    x: 20,
    y: 240,
    width: 280,
    height: 140,
  });
  assert.deepEqual(cropBox(null, viewport), {
    x: 0,
    y: 0,
    width: 320,
    height: 480,
  });
  assert.equal(
    cropBox({ l: 0, t: 0, r: 320, b: 2000 }, viewport).height,
    480 - 0,
  );
});

const finding = (over) => ({
  check: "clipped-label",
  severity: "medium",
  page: "leads-all",
  selector:
    "div[role=tablist].leads-desk__tabs > button[role=tab].leads-desk__tab",
  label: "All leads",
  detail: '"All leads" ends in …: 38 of 61 px shown',
  state: "320x640 130% text light",
  ...over,
});

test("one finding per key across widths, scales and themes, with where it shows", () => {
  const raw = [
    finding({ crop: "crops/a.jpg" }),
    finding({ state: "360x800 130% text light", severity: "high" }),
    finding({ state: "320x640 130% text light" }),
    finding({ page: "leads-desk" }),
  ];
  const found = dedupe(raw);
  assert.equal(found.length, 2);
  const first = found.find((f) => f.page === "leads-all");
  assert.deepEqual(first.where, [
    "320x640 130% text light",
    "360x800 130% text light",
  ]);
  assert.equal(first.severity, "high");
  assert.equal(first.count, 3);
  assert.equal(first.crop, "crops/a.jpg");
  assert.equal(first.key, findingKey(raw[0]));
  assert.match(first.id, /^[0-9a-f]{10}$/);
});

test("groups by root cause: one component, colour pair or message on any page", () => {
  assert.equal(
    componentOf("main > div.leads-desk__tabs > button[role=tab]"),
    "div.leads-desk__tabs … button[role=tab]",
  );
  assert.equal(
    componentOf("nav > a.lightbox-shell__bottomLink"),
    "a.lightbox-shell__bottomLink",
  );
  // Siblings of one component that spill together are one group; a page that scrolls sideways is its own.
  assert.equal(
    moduleOf("main > div.coaching__card > p.coaching__lead"),
    "coaching",
  );
  assert.equal(moduleOf("main > p"), null);
  assert.equal(
    groupKeyOf({
      check: "overflow-element",
      selector: "div.coaching__framework",
      page: "a",
    }),
    groupKeyOf({
      check: "overflow-element",
      selector: "div.x > p.coaching__lead",
      page: "b",
    }),
  );
  assert.equal(
    groupKeyOf({
      check: "overflow-page",
      detail: "the page is 297 px wide in 267",
      page: "report",
    }),
    "overflow-page | report",
  );
  const contrast = {
    check: "contrast",
    colors: "#9ca3af on #ffffff",
    selector: "p.a",
    page: "x",
  };
  assert.equal(groupKeyOf(contrast), "contrast | #9ca3af on #ffffff");
  assert.equal(
    groupKeyOf({ check: "console-error", message: "Warning: x", page: "a" }),
    "console-error | Warning: x",
  );
  assert.equal(
    groupKeyOf({
      check: "overlap",
      selector: "h2.card__title ⟂ span.card__pill",
      page: "a",
    }),
    "overlap | h2.card__title ⟂ span.card__pill",
  );
  const groups = groupFindings(
    dedupe([
      finding({}),
      finding({ page: "leads-desk" }),
      finding({ page: "leads-board" }),
      {
        ...contrast,
        severity: "low",
        label: "",
        detail: "",
        state: "320x640 100% app light",
      },
      finding({
        check: "overflow-element",
        severity: "high",
        selector: "main > ul.leads__list",
        crop: "crops/b.jpg",
      }),
    ]),
  );
  assert.deepEqual(
    groups.map((g) => [g.check, g.pages.length, g.severity]),
    [
      ["overflow-element", 1, "high"],
      ["clipped-label", 3, "medium"],
      ["contrast", 1, "low"],
    ],
  );
  assert.equal(groups[0].crop, "crops/b.jpg");
  assert.match(groups[0].id, /^[0-9a-f]{12}$/);
  // The id is the key's: stable from run to run.
  assert.equal(groupFindings(dedupe([finding({})]))[0].id, groups[1].id);
});

test("error messages lose ports, ids, numbers and queries, and never carry amounts", () => {
  assert.equal(
    normalizeMessage(
      "GET http://127.0.0.1:18216/v1/leads?x=1 404 for 3f2b8c9d-0e11-4d7b-9a1e-3f2b8c9d0e11",
    ),
    "GET /v1/leads # for <id>",
  );
  assert.equal(normalizeMessage("Plan ₹999 failed"), "Plan [amount] failed");
});

test("cards and reports carry no names, only the words around them", () => {
  assert.equal(
    namesOut("Edit Asha Fictional's lead rules"),
    "Edit [name] lead rules",
  );
  assert.equal(
    namesOut("Workspace: Fictional Homes. Switch"),
    "Workspace: [name]. Switch",
  );
  assert.equal(namesOut("All leads"), "All leads");
  assert.equal(namesOut("Review, 3 waiting"), "Review, 3 waiting");
  assert.equal(namesOut("Lead Rules"), "Lead Rules");
});

test("the report counts by check, lists the top groups with crops, every group and what it can't tell", () => {
  const findings = dedupe([
    finding({ crop: "crops/a.jpg" }),
    finding({
      check: "dead-tap",
      severity: "medium",
      selector: "button.kit__more",
      context: 'tap "More"',
    }),
  ]);
  const groups = groupFindings(findings);
  const text = reportMarkdown({
    source_sha: "0123456789abcdef",
    findings,
    groups,
    pages: [
      {
        key: "leads-all",
        path: "/review-fixture/leads?tab=all",
        crawled: true,
        failed: [],
      },
      {
        key: "kit",
        path: "/review-fixture/kit",
        crawled: false,
        failed: ["320x640 100% app light: Timeout 90000ms exceeded."],
      },
    ],
  });
  assert.match(text, /2 findings in 2 groups on 2 pages for `0123456789ab`/);
  assert.match(
    text,
    /\| clipped-label \(label cut short\) \| 1 \| 1 \| 0 \| 1 \| 0 \|/,
  );
  assert.match(text, /!\[\]\(crops\/a\.jpg\)/);
  assert.match(text, /`radar:[0-9a-f]{12}` dead-tap/);
  assert.match(
    text,
    /- kit \(\/review-fixture\/kit\): 320x640 100% app light: Timeout/,
  );
  assert.match(text, /#### What the checks cannot tell/);
  assert.ok(Object.keys(CHECKS).includes("tab-no-switch"));
});

test("bug #43: Connections' parts are swept, and wrapped or cut tab bars are their own checks", async () => {
  const { SCREENS } = await import("./wb_matrix_lib.mjs");
  const swept = new Map(radarScreens(SCREENS, []));
  for (const part of ["apps", "ai-replies", "developers", "pulse"])
    assert.ok(
      [...swept.values()].some(
        (screen) =>
          screen.path === `/review-fixture/hub?tab=connections&part=${part}`,
      ),
      part,
    );
  assert.equal(CHECKS["label-wraps"], "tab or chip label wraps");
  assert.equal(CHECKS["tabs-clipped"], "tab bar cut at the screen edge");
  // One card per bar or control, whichever page it shows on.
  const key = groupKeyOf({
    check: "tabs-clipped",
    selector: "div.org-hub__parts > div[role=group].kit__segmented",
    page: "hub-connections-apps",
  });
  assert.equal(
    key,
    groupKeyOf({
      check: "tabs-clipped",
      selector: "div.org-hub__parts > div[role=group].kit__segmented",
      page: "hub-connections-pulse",
    }),
  );
});

test("a screen that needs a phone's own width skips the Android app's loads", async () => {
  const { SCREENS } = await import("./wb_matrix_lib.mjs");
  assert.equal(screenLoads(SCREENS["leads-all"]).length, 16);
  for (const name of ["leads-table", "leads-table-open"]) {
    const loads = screenLoads(SCREENS[name]);
    assert.equal(loads.length, 14, name);
    assert.ok(!loads.some((load) => load.android), name);
  }
  assert.equal(screenLoads().length, 16);
});

test("seller journeys: five on the fictional screens, each step doing something, no names", async () => {
  const { JOURNEYS, stepActions } = await import("./wb_journeys_lib.mjs");
  assert.deepEqual(Object.keys(JOURNEYS), [
    "sign-in-setup",
    "after-call",
    "call-mode",
    "upload-recording",
    "read-report",
  ]);
  for (const [key, plan] of Object.entries(JOURNEYS)) {
    assert.ok(plan.steps.length >= 3, key);
    assert.match(plan.steps[0].goto, /^\/review-fixture\//, key);
    assert.equal(namesOut(plan.title), plan.title, key);
    const names = plan.steps.map((step) => step.name);
    assert.equal(
      new Set(names).size,
      names.length,
      `${key}: step names repeat`,
    );
    for (const step of plan.steps) {
      assert.ok(stepActions(step).length, `${key}: ${step.name} does nothing`);
      assert.equal(namesOut(step.name), step.name, `${key}: ${step.name}`);
      if (step.goto)
        assert.match(step.goto, /^\/review-fixture\//, `${key}: ${step.name}`);
      if (step.fill) assert.equal(step.fill.length, 2, `${key}: ${step.name}`);
    }
  }
});

test("a request picks journeys by name; pages only means no journeys, journeys only means no pages", async () => {
  const { JOURNEYS, pickJourneys, onlyJourneys, isJourneyRoute } = await import(
    "./wb_journeys_lib.mjs"
  );
  const finished = Object.keys(JOURNEYS).filter((key) => !JOURNEYS[key].draft);
  assert.ok(finished.length >= 3);
  assert.deepEqual(
    pickJourneys([]).map(([key]) => key),
    finished,
  );
  assert.equal(pickJourneys(["journeys"]).length, 5);
  assert.deepEqual(
    pickJourneys(["journey:after-call", "leads-all"]).map(([key]) => key),
    ["after-call"],
  );
  assert.deepEqual(pickJourneys(["leads-all", "/review-fixture/home"]), []);
  assert.throws(() => pickJourneys(["journey:nope"]), /unknown journey nope/);
  // A draft walks only when asked for: never in the nightly (its stops would be about the journey, not the app).
  const plans = { done: { steps: [] }, draft: { steps: [], draft: true } };
  assert.deepEqual(
    pickJourneys([], plans).map(([key]) => key),
    ["done"],
  );
  assert.deepEqual(
    pickJourneys(["journeys"], plans).map(([key]) => key),
    ["done", "draft"],
  );
  assert.deepEqual(
    pickJourneys(["journey:draft"], plans).map(([key]) => key),
    ["draft"],
  );
  assert.equal(onlyJourneys([]), false);
  assert.equal(onlyJourneys(["journeys"]), true);
  assert.equal(onlyJourneys(["journey:call-mode", "leads-all"]), false);
  assert.ok(
    isJourneyRoute("journey:call-mode") && !isJourneyRoute("journeys-page"),
  );
});

test("a journey's recording is a real WAV, fictional and small; its budget follows the phone's speed", async () => {
  const { fictionalRecording, journeyBudget, journeyTimeout, STEP_BUDGET_MS } =
    await import("./wb_journeys_lib.mjs");
  const { name, mimeType, buffer } = fictionalRecording();
  assert.equal(name, "fictional-call.wav");
  assert.equal(mimeType, "audio/wav");
  assert.equal(buffer.toString("ascii", 0, 4), "RIFF");
  assert.equal(buffer.toString("ascii", 8, 16), "WAVEfmt ");
  assert.equal(buffer.readUInt32LE(4), buffer.length - 8);
  assert.equal(buffer.readUInt32LE(40), buffer.length - 44);
  assert.ok(buffer.length < 200_000);
  assert.equal(journeyBudget(null), STEP_BUDGET_MS);
  assert.equal(journeyBudget({ cpu: 4 }), 4 * STEP_BUDGET_MS);
  assert.ok(journeyTimeout({ cpu: 4 }) > journeyTimeout(null));
});

test("journeys in the report: a table of walks, and a stop is its own group per journey and step", () => {
  const stop = (page) =>
    finding({
      check: "journey-broken",
      severity: "high",
      page,
      selector: "4. Send the code",
      label: "Send the code",
      detail: "stops at step 4. Send the code: Timeout 15000ms exceeded.",
    });
  const findings = dedupe([
    stop("journey:sign-in-setup"),
    stop("journey:other"),
  ]);
  const groups = groupFindings(findings);
  assert.equal(groups.length, 2);
  assert.equal(
    groupKeyOf(findings[0]),
    "journey-broken | journey:sign-in-setup | 4. Send the code",
  );
  const text = reportMarkdown({
    findings,
    groups,
    pages: [],
    journeys: [
      {
        key: "sign-in-setup",
        title:
          "A new seller signs in with an email code and sets up the business",
        profile: "phone",
        total: 15,
        steps: [
          { name: "1. Open sign-in", ms: 900 },
          { name: "2. Type the email", ms: 120 },
          { name: "3. Accept the terms", ms: 2400 },
        ],
        stopped: "4. Send the code",
      },
      {
        key: "sign-in-setup",
        title:
          "A new seller signs in with an email code and sets up the business",
        profile: "android",
        total: 15,
        steps: [{ name: "1. Open sign-in", ms: 3000 }],
        stopped: null,
      },
    ],
  });
  assert.match(text, /#### Seller journeys \(fictional screens\)/);
  assert.match(
    text,
    /\| phone \| 3\/15 \| 3\.4 s \| 3\. Accept the terms \(2\.4 s\) \| 4\. Send the code \|/,
  );
  assert.match(
    text,
    /\| the Android app, slow phone \| 1\/15 \| 3\.0 s \| 1\. Open sign-in \(3\.0 s\) \| — \|/,
  );
  assert.match(
    text,
    /journey-broken \(a seller journey stops at a step\) \| 2 \| 2 \| 2 \|/,
  );
});

test("a shard stopped at the deadline says what was still running, and the slowest pages are listed", () => {
  const text = reportMarkdown({
    findings: [],
    groups: [],
    pages: [
      { key: "home", path: "/review-fixture/home", ms: 412000, failed: [] },
      { key: "kit", path: "/review-fixture/kit", ms: 61000, failed: [] },
      { key: "calls-list", path: "/review-fixture/calls", ms: 0, failed: [] },
    ],
    stopped: [
      {
        shard: "3/5",
        running: [
          { page: "home-seller", kind: "sweep", since: 0, seconds: 540 },
        ],
      },
    ],
  });
  assert.match(text, /#### Shards stopped at the 40-minute deadline/);
  assert.match(text, /- shard 3\/5: still running home-seller \(sweep, 540s\)/);
  assert.match(text, /#### Slowest pages[^\n]*\n\n- home: 412s\n- kit: 61s\n/);
  assert.doesNotMatch(text, /- calls-list: 0s/);
});
