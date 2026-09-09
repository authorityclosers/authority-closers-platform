import { mkdtemp, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { localPage } from "./local-page-cdp.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = await mkdtemp(path.join(root, "docs/evidence/screenshots/practice-sound-clarity-20260908-"));
const assert = (value, message) => { if (!value) throw new Error(message); };
const listTargets = async () => await fetch("http://127.0.0.1:9327/json/list").then((response) => response.json());
const page = await localPage({ pathname: "/practice?set=gaps", newTab: true });
const browserTargetId = page.createdTargetId;
const captures = [];
let preferences;
const restorePreferences = async () => {
  if (!preferences) return false;
  const restored = await page.evaluate(`(()=>{const p=${JSON.stringify(preferences)};for(const [k,v] of [["ac-practice-sounds",p.sounds],["ac-practice-volume",p.volume]]){if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v)}window.dispatchEvent(new Event("ac-practice-sounds-change"));return localStorage.getItem("ac-practice-sounds")===p.sounds&&localStorage.getItem("ac-practice-volume")===p.volume})()`);
  assert(restored, "Original local sound preferences were not restored");
  preferences = undefined;
  return true;
};
const layout = async () => await page.evaluate(`(()=>{const d=document.documentElement;return {clientWidth:d.clientWidth,scrollWidth:d.scrollWidth,scrollHeight:d.scrollHeight,viewportWidth:innerWidth,viewportHeight:innerHeight}})()`);
const nativeClick = async (expression, label) => {
  await page.evaluate(`(()=>{const e=${expression};if(!e)return false;e.scrollIntoView({block:"center",inline:"nearest"});return true})()`);
  await page.until(`(()=>{const e=${expression};if(!e)return false;const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&r.width>0&&r.height>0})()`, 5000);
  const point = await page.evaluate(`(()=>{const r=(${expression}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  assert(point, `${label}: target missing`);
  await page.send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, x: point.x, y: point.y });
  await page.send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, x: point.x, y: point.y });
  await page.delay(450);
};
const capture = async (name) => {
  const l = await layout();
  assert(l.scrollWidth <= l.clientWidth, `${name}: horizontal overflow`);
  const shot = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(output, `${name}.png`), Buffer.from(shot.data, "base64"));
  captures.push({ name, layout: l });
};

try {
  await page.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  await page.delay(12000);
  await page.until(`!!document.querySelector('[aria-label="Practice sound settings"]')`, 30000);
  preferences = await page.evaluate(`({sounds:localStorage.getItem("ac-practice-sounds"),volume:localStorage.getItem("ac-practice-volume")})`);
  await nativeClick(`document.querySelector('[aria-label="Practice sound settings"]')`, "sound settings");
  await page.until(`!!document.querySelector('[role="dialog"]')`, 10000);
  const initial = await page.evaluate(`(()=>({enabled:document.querySelector('[role="switch"][aria-label="Practice sound effects"]')?.getAttribute('aria-checked'),volume:document.querySelector('[aria-label="Practice sound volume"]')?.value}))()`);
  await capture("practice-sound-settings-390x844");

  if (initial.enabled === "false") await nativeClick(`document.querySelector('[role="switch"][aria-label="Practice sound effects"]')`, "enable for explicit sound-control test");
  await nativeClick(`document.querySelector('[role="switch"][aria-label="Practice sound effects"]')`, "sound switch off");
  const muted = await page.evaluate(`document.querySelector('[role="switch"][aria-label="Practice sound effects"]')?.getAttribute('aria-checked')`);
  await nativeClick(`document.querySelector('[role="switch"][aria-label="Practice sound effects"]')`, "sound switch on");
  const enabled = await page.evaluate(`document.querySelector('[role="switch"][aria-label="Practice sound effects"]')?.getAttribute('aria-checked')`);
  assert(muted === "false" && enabled === "true", "Sound switch did not toggle off and on");
  await page.delay(2500);
  const resources = await page.evaluate(`performance.getEntriesByType("resource").map(e=>e.name).filter(n=>n.includes("/audio/practice/"))`);
  const tap = `([...document.querySelectorAll('[role="dialog"] button')].find(e=>e.textContent.trim()==="Tap"))`;
  const tapDisabled = await page.evaluate(`Boolean(${tap}?.disabled)`);
  assert(!tapDisabled, "Tap preview is not ready");
  await nativeClick(tap, "Tap preview");
  await page.delay(900);
  const preview = await page.evaluate(`({status:document.querySelector('[role="status"]')?.textContent||"",buttons:[...document.querySelectorAll('[role="dialog"] button')].map(e=>({text:e.textContent.trim(),disabled:e.disabled}))})`);
  assert(preview.status.includes("Sound preview"), "Explicit preview was not confirmed");
  await capture("practice-sound-enabled-390x844");
  await nativeClick(`document.querySelector('[role="switch"][aria-label="Practice sound effects"]')`, "sound switch final off");
  const finalState = await page.evaluate(`document.querySelector('[role="switch"][aria-label="Practice sound effects"]')?.getAttribute('aria-checked')`);
  assert(finalState === "false", "Sound switch did not end muted");
  assert((await layout()).scrollWidth <= (await layout()).clientWidth, "Horizontal overflow");
  const localStorageRestored = await restorePreferences();
  await writeFile(path.join(output, "proof.json"), JSON.stringify({
    generatedAt: new Date().toISOString(),
    scope: "local practice presentation-only QA; no account/domain writes",
    route: "http://learner.localhost:3100/practice?set=gaps",
    browserTargetId,
    interaction: "CDP Input.dispatchMouseEvent only",
    initial, muted, enabled, finalState, volume: initial.volume,
    audioResources: resources,
    preview,
    localStorageRestored,
    captures,
    externalRequestsBlocked: page.external(),
  }, null, 2));
  console.log(JSON.stringify({ passed: true, output, initial, muted, enabled, finalState, audioResources: resources.length }));
} finally {
  if (preferences) await restorePreferences().catch(() => { process.exitCode = 1; console.error("Sound preference restoration failed"); });
  await page.send("Emulation.clearDeviceMetricsOverride").catch(()=>{});
  await page.close().catch(()=>{});
  if (browserTargetId) {
    const remaining = await listTargets().catch(() => []);
    const ownTarget = remaining.find((target) => target.id === browserTargetId && target.type === "page" && target.url === "http://learner.localhost:3100/practice?set=gaps");
    if (ownTarget) await fetch(`http://127.0.0.1:9327/json/close/${encodeURIComponent(browserTargetId)}`).catch(()=>{});
  }
}
