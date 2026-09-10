import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";
const page = await localPage({ pathname: "/profile", newTab: true });
const output = path.resolve("docs/evidence/screenshots/local-avatar-browser-20260908");
await mkdir(output, { recursive: true });
const ready = () => page.until(`Boolean(${page.button("Change photo")}) && [...document.querySelectorAll('main img')].some(e=>e.alt.includes('profile photo') && e.complete && e.naturalWidth===512)`, 60000);
const screenshot = async (name) => {
  await page.evaluate("window.scrollTo(0,0)"); await page.delay(300);
  const result = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(output, name + ".png"), Buffer.from(result.data, "base64"));
};
const version = () => page.evaluate("fetch('/v1/profile/avatar',{credentials:'same-origin',cache:'no-store',redirect:'error'}).then(async r=>{if(!r.ok)throw Error();const a=await r.json();return {asset:a.avatar?.asset_id,version:a.avatar?.version_id};})");
try {
  await page.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await ready();
  const before = await version();
  if (!before.asset || !before.version) throw new Error("Current version unavailable");
  const documentOrigin = await page.evaluate("performance.timeOrigin");
  await page.send("Page.reload");
  await page.until(`performance.timeOrigin !== ${documentOrigin} && document.readyState === 'complete'`);
  await ready();
  const after = await version();
  if (before.asset !== after.asset || before.version !== after.version) throw new Error("Current version changed");
  await screenshot("05-retained-new-document-desktop");
  await page.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  await page.click("Change photo");
  await page.until("Boolean(document.querySelector('[role=dialog]'))");
  await screenshot("06-current-photo-editor-mobile390");
  const bounds = await page.evaluate(`(()=>{const b=${page.button("Save photo")};const r=b.getBoundingClientRect();return {viewport:innerWidth,content:document.documentElement.scrollWidth,top:r.top,bottom:r.bottom,height:innerHeight};})()`);
  if (bounds.content > bounds.viewport || bounds.top < 0 || bounds.bottom > bounds.height) throw new Error("Mobile save control outside viewport");
  await page.click("Cancel");
  await screenshot("07-retained-profile-mobile390");
  await page.send("Emulation.clearDeviceMetricsOverride");
  process.stdout.write(JSON.stringify({ status: "passed", new_document_and_main_ready: true, fresh_version_unchanged: true, decoded_width: 512, mobile_save_bounds: bounds, external_requests: page.external() }) + "\n");
} catch { process.stderr.write("Local avatar retention proof incomplete; no private URL diagnostics emitted.\n"); process.exitCode = 1; }
finally { await page.close(); }
