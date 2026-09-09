import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { localPage } from "./local-page-cdp.mjs";

if (!process.argv.includes("--capture-local-studio-baseline")) throw new Error("Explicit local baseline mode required");
const page = await localPage({ surface: "admin", pathname: "/studio/programs", newTab: true });
try {
  await page.until("document.body.innerText.includes('Open program') || document.body.innerText.includes('Sign in')");
  const state = await page.evaluate("({path:location.pathname,links:[...document.querySelectorAll('a')].filter(a=>a.getAttribute('href')?.startsWith('/studio/programs/')).map(a=>({path:a.getAttribute('href'),title:a.closest('article')?.querySelector('h3')?.textContent}))})");
  console.log(JSON.stringify(state));
  if (state.path.includes("login")) throw new Error("Studio session requires normal sign-in");
  const draft = state.links.find((item) => item.title?.includes("Coach"));
  if (!draft) throw new Error("Synthetic coach draft was not found");
  await page.send("Page.navigate", {url: "http://admin.localhost:3101" + draft.path});
  await page.until("document.body.innerText.includes('Publication readiness')");
  const output = resolve("docs/evidence/screenshots/studio-editor-" + new Date().toISOString().replaceAll(":", "-"));
  await mkdir(output, {recursive: true});
  for (const width of [1440,390]) {
    await page.send("Emulation.setDeviceMetricsOverride", {width,height:900,deviceScaleFactor:1,mobile:false});
    await page.delay(250);
    const screenshot = await page.send("Page.captureScreenshot", {format:"png",captureBeyondViewport:false});
    await writeFile(resolve(output,`baseline-${width}.png`),Buffer.from(screenshot.data,"base64"));
  }
  console.log(JSON.stringify({output,externalRequests:page.external()}));
} finally { await page.close(); }
