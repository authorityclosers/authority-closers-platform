import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";
const page = await localPage({ pathname: "/settings", newTab: true });
const output = path.resolve("docs/evidence/screenshots/arcade-theme-20260908");
await mkdir(output, { recursive: true });
let original;
let restored = false;
const select = async (label, value) => {
  const state = await page.evaluate(`(()=>{const e=document.querySelector('select[aria-label=${JSON.stringify(label)}]');e.focus();e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));return {label:e.getAttribute('aria-label'),value:e.value,theme:document.documentElement.dataset.theme,accent:document.documentElement.dataset.accent};})()`, true);
  process.stdout.write(JSON.stringify({ select_result:state }) + "\n");
};
const navigate = async (suffix, ready) => {
  const previous = await page.evaluate("performance.timeOrigin");
  await page.send("Page.navigate", { url: "http://learner.localhost:3100" + suffix });
  await page.until(`performance.timeOrigin !== ${previous} && document.readyState === 'complete'`);
  await page.until(ready);
};
const settingsReady = "Boolean(document.querySelector('select[aria-label=\"Theme\"]')) && Boolean(document.querySelector('select[aria-label=\"Accent color\"]'))";
try {
  await page.until(settingsReady);
  await page.until("document.readyState === 'complete'"); await page.delay(1500);
  original = process.argv[2] === "restore-initial" ? {theme:"light",accent:"cobalt"} : await page.evaluate("({theme:document.querySelector('select[aria-label=\"Theme\"]').value,accent:document.querySelector('select[aria-label=\"Accent color\"]').value})");
  await select("Theme", "dark"); await page.delay(300); await select("Accent color", "emerald"); await page.delay(300);
  await page.until("document.documentElement.dataset.theme==='dark' && document.documentElement.dataset.accent==='emerald'");
  for (const [name, width, height, suffix] of [["hub-desktop",1440,1000,"/practice"],["drill-desktop",1440,1000,"/practice?set=next-move"],["drill-mobile390",390,844,"/practice?set=next-move"]]) {
    await page.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    await navigate(suffix, suffix.includes("?") ? `Boolean(${page.button("Check my response")})` : "Boolean(document.querySelector('#practice-title'))");
    if (suffix.includes("?")) await page.evaluate("document.querySelector('input[type=radio]').click()", true);
    await page.delay(300);
    const screenshot = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    await writeFile(path.join(output, `dark-emerald-${name}.png`), Buffer.from(screenshot.data, "base64"));
    const projection = await page.evaluate("({theme:document.documentElement.dataset.theme,accent:document.documentElement.dataset.accent,action:getComputedStyle(document.documentElement).getPropertyValue('--theme-action'),overflow:document.documentElement.scrollWidth>innerWidth})");
    if (projection.theme !== "dark" || projection.accent !== "emerald" || projection.overflow) throw new Error("Theme projection failed");
    process.stdout.write(JSON.stringify({ surface: name, ...projection }) + "\n");
  }
} catch { process.stderr.write("Local Arcade theme proof incomplete.\n"); process.stdout.write(JSON.stringify(await page.evaluate("({theme:document.documentElement.dataset.theme,accent:document.documentElement.dataset.accent,selectors:[...document.querySelectorAll('select')].map(e=>({label:e.getAttribute('aria-label'),value:e.value}))})").catch(()=>null)) + "\n"); process.exitCode = 1; }
finally {
  if (original) {
    try {
      await navigate("/settings", settingsReady);
      await page.delay(1500);
      await select("Theme", original.theme); await page.delay(300); await select("Accent color", original.accent);
      await page.until(`document.documentElement.dataset.themePreference === ${JSON.stringify(original.theme)} && document.documentElement.dataset.accent === ${JSON.stringify(original.accent)}`);
      restored = true;
    } catch { process.stderr.write("Original appearance restoration requires attention.\n"); process.exitCode = 1; }
  }
  await page.send("Emulation.clearDeviceMetricsOverride");
  process.stdout.write(JSON.stringify({ preferences_restored_via_ui: restored, direct_storage_mutations: false, external_requests: page.external() }) + "\n");
  await page.close();
}
