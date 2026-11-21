// The screen guard's comparison: identical renders pass, a 1 px change or a size change is caught, and the frame
// list covers Home, Leads and the tab bar. Needs the Playwright browser (the visual job has it).
//
//   node --test scripts/ci/wb_guard_screens.test.mjs
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { chromium } from "playwright";
import {
  CHROMIUM_ARGS,
  comparePngs,
  guardFrames,
  TOLERANCE,
} from "./wb_guard_screens.mjs";

let browser;
let page;
before(async () => {
  browser = await chromium.launch({ args: CHROMIUM_ARGS });
  page = await browser.newPage({
    viewport: { width: 120, height: 60 },
    deviceScaleFactor: 1,
  });
});
after(() => browser?.close());

/** A small tab-bar-like strip; `nudge` moves one label by 1 px, `tint` shifts its colour by that much. */
async function shot({ nudge = 0, tint = 0, width = 120 } = {}) {
  await page.setViewportSize({ width, height: 60 });
  await page.setContent(
    `<body style="margin:0;background:#fff"><nav style="display:flex;gap:8px;padding:10px;font:14px sans-serif">` +
      `<span style="position:relative;left:${nudge}px;color:rgb(${20 + tint},20,20)">Home</span><span>Leads</span></nav></body>`,
  );
  return `data:image/png;base64,${(await page.screenshot()).toString("base64")}`;
}

test("identical renders have no changed pixels", async () => {
  const a = await shot();
  const found = await page.evaluate(comparePngs, [a, await shot(), TOLERANCE]);
  assert.equal(found.sizeMismatch, false);
  assert.equal(found.changed, 0);
  assert.equal(found.diff, null);
});

test("a 1 px move is caught, with a diff image and the changed area", async () => {
  const found = await page.evaluate(comparePngs, [
    await shot(),
    await shot({ nudge: 1 }),
    TOLERANCE,
  ]);
  assert.ok(found.changed > 0, "moved text must change pixels");
  assert.match(found.diff, /^data:image\/png;base64,/);
  assert.ok(found.box[0] >= 9 && found.box[2] < 60, `box ${found.box}`);
});

test("a colour change past the tolerance is caught, within it is not", async () => {
  const base = await shot();
  const small = await page.evaluate(comparePngs, [
    base,
    await shot({ tint: TOLERANCE - 2 }),
    TOLERANCE,
  ]);
  assert.equal(small.changed, 0);
  const big = await page.evaluate(comparePngs, [
    base,
    await shot({ tint: 60 }),
    TOLERANCE,
  ]);
  assert.ok(big.changed > 0);
});

test("a size change fails without a pixel count", async () => {
  const found = await page.evaluate(comparePngs, [
    await shot(),
    await shot({ width: 121 }),
    TOLERANCE,
  ]);
  assert.equal(found.sizeMismatch, true);
  assert.deepEqual(found.baseline, [120, 60]);
  assert.deepEqual(found.current, [121, 60]);
});

test("the guard covers Home and Leads at both sizes and schemes, and the tab bar on three pages", () => {
  const names = guardFrames().map((frame) => frame.name);
  for (const key of ["home-owner", "home-seller", "leads"])
    for (const width of [390, 1440])
      for (const scheme of ["light", "dark"])
        assert.ok(names.includes(`${key}-${width}-${scheme}`));
  for (const key of ["tabbar-home", "tabbar-leads", "tabbar-shell"])
    for (const scheme of ["light", "dark"])
      assert.ok(names.includes(`${key}-390-${scheme}`));
  assert.equal(new Set(names).size, names.length);
});
