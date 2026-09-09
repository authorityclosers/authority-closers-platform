import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";

const page = await localPage({ pathname: "/profile", newTab: true });
const output = path.resolve("docs/evidence/screenshots/local-avatar-browser-20260908");
await mkdir(output, { recursive: true });
const screenshot = async (name) => {
  await page.evaluate("window.scrollTo(0,0)");
  const result = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(output, name + ".png"), Buffer.from(result.data, "base64"));
};
try {
  await page.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await page.until(`Boolean(${page.button("Change photo")})`, 60000);
  await screenshot("01-before-desktop");
  await page.click("Change photo");
  await page.until("Boolean(document.querySelector('input[type=file]'))");
  // A synthetic four-colour PNG, not a real person's photograph or external asset.
  await page.evaluate(`new Promise((resolve,reject)=>{const c=document.createElement('canvas');c.width=640;c.height=480;const x=c.getContext('2d');x.fillStyle='#0b6563';x.fillRect(0,0,320,240);x.fillStyle='#edba60';x.fillRect(320,0,320,240);x.fillStyle='#243753';x.fillRect(0,240,320,240);x.fillStyle='#8faec1';x.fillRect(320,240,320,240);x.fillStyle='#fff';x.font='bold 140px sans-serif';x.textAlign='center';x.fillText('LOCAL',320,290);c.toBlob(b=>{if(!b){reject();return;}const d=new DataTransfer();d.items.add(new File([b],'synthetic-local-avatar.png',{type:'image/png'}));const input=document.querySelector('input[type=file]');input.files=d.files;input.dispatchEvent(new Event('change',{bubbles:true}));resolve();},'image/png');})`);
  await page.until("Boolean(document.querySelector('img[alt=\"Local avatar preview\"]'))");
  await page.click("Zoom in"); await page.click("Zoom in");
  await page.until("Number(document.querySelector('[aria-label=\"Photo zoom\"]').value)>1.1");
  await screenshot("02-crop-zoom-desktop");
  await page.click("Save photo");
  await page.until("document.body.textContent.includes('Profile photo updated.')", 60000);
  await page.until("[...document.querySelectorAll('img')].some(e=>e.alt.includes('profile photo') && e.complete && e.naturalWidth===512)");
  await screenshot("03-saved-desktop");
  const beforeDocument = await page.evaluate("performance.timeOrigin");
  await page.send("Page.reload");
  await page.until(`performance.timeOrigin !== ${beforeDocument} && document.readyState === 'complete'`);
  await page.until(`Boolean(${page.button("Change photo")}) && [...document.querySelectorAll('img')].some(e=>e.alt.includes('profile photo') && e.complete && e.naturalWidth===512)`);
  await screenshot("05-retained-new-document-desktop");
  await page.send("Emulation.clearDeviceMetricsOverride");
  process.stdout.write(JSON.stringify({ status: "passed", synthetic_image: true, actual_upload_save_reload: true, decoded_width: 512, external_requests: page.external(), screenshots: 4, interaction: "CDP user-gesture buttons and synthetic file input" }) + "\n");
} catch {
  const state = await page.evaluate("({headings:[...document.querySelectorAll('h1,h2')].map(e=>e.textContent),controls:[...document.querySelectorAll('button')].map(e=>({label:e.getAttribute('aria-label'),text:e.textContent})),alerts:[...document.querySelectorAll('[role=alert],[role=status]')].map(e=>e.textContent)})").catch(() => null);
  if (state) process.stdout.write(JSON.stringify(state) + "\n");
  process.stderr.write("Local avatar browser proof incomplete; no private URL diagnostics emitted.\n"); process.exitCode = 1;
} finally { await page.close(); }
