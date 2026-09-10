import { mkdtemp, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = await mkdtemp(path.join(root, "docs/evidence/screenshots/progress-clarity-20260908-"));
const assert = (value, message) => { if (!value) throw new Error(message); };
const listTargets = async () => await fetch("http://127.0.0.1:9327/json/list").then((response) => response.json());
const page = await localPage({ pathname: "/progress", newTab: true });
const browserTargetId = page.createdTargetId;
const captures = [];
const interactions = {};

const layout = async () => await page.evaluate(`(()=>{const d=document.documentElement,b=document.body;return {clientWidth:d.clientWidth,scrollWidth:d.scrollWidth,scrollHeight:d.scrollHeight,bodyScrollHeight:b?.scrollHeight||0,viewportWidth:innerWidth,viewportHeight:innerHeight}})()`);
const resourceNames = async () => await page.evaluate(`performance.getEntriesByType("resource").map(e=>e.name).filter(n=>n.includes("/v1/learning/insights"))`);
const capture = async (name) => {
  const l = await layout();
  assert(l.scrollWidth <= l.clientWidth, `${name}: horizontal overflow ${l.scrollWidth} > ${l.clientWidth}`);
  const c = { x: 0, y: 0, width: l.viewportWidth, height: l.scrollHeight };
  const shot = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { ...c, scale: 1 } });
  await writeFile(path.join(output, `${name}.png`), Buffer.from(shot.data, "base64"));
  captures.push({ name, layout: l, contentSize: c });
};
const nativeClick = async (expression, label) => {
  await page.evaluate(`(()=>{const e=${expression};if(!e)return false;e.scrollIntoView({block:"center",inline:"nearest"});return true})()`);
  await page.until(`(()=>{const e=${expression};if(!e)return false;const r=e.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight && r.width>0 && r.height>0})()`, 5000);
  const point = await page.evaluate(`(()=>{const e=${expression};if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height}})()`);
  assert(point && point.w > 0 && point.h > 0, `${label}: target not visible`);
  await page.send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, x: point.x, y: point.y });
  await page.send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, x: point.x, y: point.y });
  await page.delay(350);
};
const key = async (keyName, code, vk, text) => {
  await page.send("Input.dispatchKeyEvent", { type: "keyDown", key: keyName, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk, ...(text ? { text } : {}) });
  await page.send("Input.dispatchKeyEvent", { type: "keyUp", key: keyName, code, windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk });
  await page.delay(350);
};
const detailsState = async () => await page.evaluate(`([...document.querySelectorAll("details")].map((e,i)=>({index:i,open:e.open,summary:e.querySelector("summary")?.textContent.trim()})))`);
const summary2 = `([...document.querySelectorAll("details > summary")].find(e=>(e.textContent||"").includes("SHIFT 2")))`;

try {
  await page.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  await page.delay(12000);
  await page.until(`!!document.querySelector('[data-progress-scope="course"]') && !!document.querySelector("details > summary")`, 60000);
  const defaultMobile = await layout();
  await capture("progress-default-390x844");

  await page.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await page.delay(1200);
  await page.until(`!!document.querySelector('[data-progress-scope="course"]')`, 30000);
  const defaultDesktop = await layout();
  await capture("progress-default-1440x900");

  await page.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  await page.delay(700);
  await page.until(`!!document.querySelector('[data-progress-scope="course"]')`, 30000);
  const before = await detailsState();
  assert(before.length >= 2 && before[1].open === false, "Module 2 must start collapsed");

  await page.evaluate(`(()=>{const e=${summary2};e.focus();return document.activeElement===e})()`, true);
  await key("Enter", "Enter", 13, "\r");
  const afterEnter = await detailsState();
  assert(afterEnter[1]?.open === true, "Module 2 did not open with Enter");
  interactions.keyboardEnter = { before: before[1], after: afterEnter[1] };

  await page.evaluate(`(()=>{const e=${summary2};e.focus();return document.activeElement===e})()`, true);
  await key(" ", "Space", 32);
  const afterSpace = await detailsState();
  assert(afterSpace[1]?.open === false, "Module 2 did not close with Space");
  interactions.keyboardSpace = { before: afterEnter[1], after: afterSpace[1] };

  await nativeClick(summary2, "Module 2 mouse click");
  const afterMouse = await detailsState();
  assert(afterMouse[1]?.open === true, "Module 2 did not open with native mouse click");
  interactions.nativeMouseModule = { after: afterMouse[1] };
  await capture("progress-module-expanded-390x844");

  const insightsBeforeScope = await resourceNames();
  await nativeClick(`([...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="All learning"))`, "All learning");
  await page.until(`!!document.querySelector('[data-progress-scope="all"]')`, 30000);
  await page.delay(700);
  const insightsAfterScope = await resourceNames();
  interactions.scopeSwitch = { from: "course", to: "all", insightsBefore: insightsBeforeScope.length, insightsAfter: insightsAfterScope.length, requestNames: insightsAfterScope };
  assert(insightsAfterScope.length === insightsBeforeScope.length, "Scope switch triggered insights request");

  const insightsBeforeExpand = await resourceNames();
  await nativeClick(`([...document.querySelectorAll("button")].find(e=>e.textContent.includes("Activity insights") && e.getAttribute("aria-expanded")==="false"))`, "Activity insights");
  await page.until(`(()=>{const e=document.querySelector("#progress-activity-insights");return !!e && e.hidden===false})()`, 30000);
  await page.until(`performance.getEntriesByType("resource").some(e=>e.name.includes("/v1/learning/insights"))`, 30000);
  await page.delay(600);
  const insightsAfterExpand = await resourceNames();
  interactions.activityInsights = { before: insightsBeforeExpand.length, after: insightsAfterExpand.length, requestNames: insightsAfterExpand };
  assert(insightsAfterExpand.length > insightsBeforeExpand.length, "Activity insights expansion did not request insights");
  assert(insightsAfterExpand.some(n=>n.includes("/v1/learning/insights?period=week")), "Insights request did not use week period");
  await capture("progress-insights-expanded-390x844");

  const finalMobile = await layout();
  for (const [name, l] of Object.entries({ defaultMobile, defaultDesktop, finalMobile })) assert(l.scrollWidth <= l.clientWidth, `${name}: horizontal overflow`);
  const baseline = { mobile: { contentHeight: 4051, scrollHeight: 4051 }, desktop: { contentHeight: 2909, scrollHeight: 2910 }, source: "docs/evidence/screenshots/v02-luna-baseline-20260908T170313-retry/results.json" };
  const proof = {
    generatedAt: new Date().toISOString(),
    scope: "local learner presentation-only QA; no account/domain writes",
    route: "http://learner.localhost:3100/progress",
    browserTargetId,
    interaction: "CDP Input.dispatchMouseEvent and Input.dispatchKeyEvent only",
    baseline,
    current: { defaultMobile, defaultDesktop, finalMobile },
    interactions,
    captures,
    horizontalOverflow: false,
    externalRequestsBlocked: page.external(),
  };
  await writeFile(path.join(output, "proof.json"), JSON.stringify(proof, null, 2));
  console.log(JSON.stringify({ passed: true, output, captures: captures.map(c=>c.name), heights: { defaultMobile: defaultMobile.scrollHeight, defaultDesktop: defaultDesktop.scrollHeight, finalMobile: finalMobile.scrollHeight }, insights: interactions.activityInsights }));
} catch (error) {
  console.error(JSON.stringify({ passed: false, message: error?.message || String(error), stack: error?.stack }));
  process.exitCode = 1;
} finally {
  await page.send("Emulation.clearDeviceMetricsOverride").catch(()=>{});
  await page.close().catch(()=>{});
  if (browserTargetId) {
    const remaining = await listTargets().catch(() => []);
    const ownTarget = remaining.find((target) => target.id === browserTargetId && target.type === "page" && target.url === "http://learner.localhost:3100/progress");
    if (ownTarget) await fetch(`http://127.0.0.1:9327/json/close/${encodeURIComponent(browserTargetId)}`).catch(()=>{});
  }
}
