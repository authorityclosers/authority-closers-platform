// Read-only visual acceptance against the already signed-in synthetic Coach.
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { localPage } from "./local-page-cdp.mjs";

const sandbox = JSON.parse(await readFile(".tmp/local-platform/sandbox.json", "utf8"));
const page = await localPage({ surface: "coach", pathname: `/studio/programs/${sandbox.studio_program_id}` });
const output = resolve("docs/evidence/screenshots/coach-layout-" + new Date().toISOString().replaceAll(":", "-"));
const checks = [];
await mkdir(output, { recursive: true });
const toggle = 'document.querySelector("button[aria-controls=course-outline]")';
async function nativeToggle() {
  await page.evaluate(`${toggle}.scrollIntoView({block:"center"})`);
  const point = await page.evaluate(`(() => { const r=${toggle}.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
  for (const type of ["mousePressed", "mouseReleased"]) await page.send("Input.dispatchMouseEvent", { type, button: "left", clickCount: 1, ...point });
}
async function capture(name) {
  const { data } = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(resolve(output, name + ".png"), Buffer.from(data, "base64"));
}
try {
  await page.until("Boolean(document.querySelector('[data-studio-editor]'))");
  for (const width of [1440, 768, 390, 320]) {
    await page.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: width < 768 });
    await page.delay(200);
    await page.evaluate("scrollTo(0,0)");
    assert.equal(await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
    if (width <= 800) {
      assert.equal(await page.evaluate(`${toggle}.getAttribute('aria-expanded')`), "false");
      assert.equal(await page.evaluate("getComputedStyle(document.querySelector('#course-outline')).display"), "none");
      await capture(`editor-${width}-collapsed`);
      await nativeToggle();
      await page.until(`${toggle}.getAttribute('aria-expanded') === 'true'`);
      assert.notEqual(await page.evaluate("getComputedStyle(document.querySelector('#course-outline')).display"), "none");
      assert.equal(await page.evaluate("document.documentElement.scrollWidth <= innerWidth"), true);
      await capture(`editor-${width}-expanded`);
      await nativeToggle();
      await page.until(`${toggle}.getAttribute('aria-expanded') === 'false'`);
      checks.push(`${width}px: native outline expand/collapse, matching accessible state, no horizontal overflow`);
    } else {
      assert.notEqual(await page.evaluate("getComputedStyle(document.querySelector('#course-outline')).display"), "none");
      await capture(`editor-${width}`);
      checks.push(`${width}px: persistent outline, no horizontal overflow`);
    }
  }
  assert.equal(page.external(), 0);
  await writeFile(resolve(output, "proof.json"), JSON.stringify({ scope: "localhost synthetic Coach", mutations: 0, checks, externalRequests: page.external() }, null, 2));
  console.log(JSON.stringify({ status: "passed", checks: checks.length, output }));
} catch {
  await capture("incomplete").catch(() => {});
  console.log(JSON.stringify({ status: "incomplete", checks, output }));
  process.exitCode = 1;
} finally {
  await page.send("Emulation.clearDeviceMetricsOverride").catch(() => {});
  await page.close();
}
