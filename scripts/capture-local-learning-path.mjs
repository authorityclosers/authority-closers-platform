import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";
const phase = process.argv[2] ?? "before";
if (!["before", "after", "after-light"].includes(phase)) throw new Error("Expected evidence phase");
const page = await localPage({ pathname: "/learning", newTab: true });
const output = path.resolve("docs/evidence/screenshots/learning-path-20260908");
await mkdir(output, { recursive: true });
const capture = async (surface, size) => {
  await page.evaluate("window.scrollTo(0,0)"); await page.delay(300);
  const image = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(path.join(output, `${phase}-${surface}-${size}.png`), Buffer.from(image.data, "base64"));
  process.stdout.write(`${phase}-${surface}-${size}.png\n`);
};
try {
  await page.until("document.readyState === 'complete' && Boolean(document.querySelector('main a[href^=\"/learn/\"]'))");
  const links = await page.evaluate("[...document.querySelectorAll('main a[href]')].map(e=>({path:e.getAttribute('href'),text:e.textContent.trim()}))");
  const course = links.find(link => link.path === "/learn/authority-closers-free-course") ?? links.find(link => link.path.startsWith("/learn/"));
  if (!course) throw new Error("Enrolled course unavailable");
  await page.evaluate(`[...document.querySelectorAll('main a')].find(e=>e.getAttribute('href')===${JSON.stringify(course.path)}).click()`, true);
  await page.until(`location.pathname === ${JSON.stringify(course.path)} && Boolean(document.querySelector('main a[href*="/module/"]'))`);
  for (const [size, width, height] of [["desktop",1440,1000],["mobile390",390,844]]) {
    await page.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    await capture("course", size);
  }
  const modulePath = await page.evaluate("document.querySelector('main a[href*=\"/module/\"]').getAttribute('href')");
  await page.evaluate("document.querySelector('main a[href*=\"/module/\"]').click()", true);
  await page.until(`location.pathname === ${JSON.stringify(modulePath)} && Boolean(document.querySelector('main h1'))`);
  await page.delay(1000);
  for (const [size, width, height] of [["desktop",1440,1000],["mobile390",390,844]]) {
    await page.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    await capture("module", size);
  }
  await page.send("Emulation.clearDeviceMetricsOverride");
  process.stdout.write(JSON.stringify({ source: "real My Learning enrollment links", screenshots:4, external_requests:page.external() }) + "\n");
} catch { process.stderr.write("Learning baseline navigation incomplete.\n"); process.stdout.write(JSON.stringify(await page.evaluate("({headings:[...document.querySelectorAll('main h1,main h2')].map(e=>e.textContent),links:[...document.querySelectorAll('main a')].map(e=>({href:e.getAttribute('href'),text:e.textContent})),buttons:[...document.querySelectorAll('main button')].map(e=>e.textContent)})").catch(()=>null)) + "\n"); process.exitCode = 1; }
finally { await page.close(); }
