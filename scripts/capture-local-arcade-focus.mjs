import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";
const page = await localPage({ pathname: "/practice", newTab: true });
const output = path.resolve("docs/evidence/screenshots/arcade-focus-20260908");
await mkdir(output, { recursive: true });
try {
  for (const [label, width, height] of [["desktop", 1440, 1000], ["mobile390", 390, 844], ["mobile320", 320, 740]]) {
    await page.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    for (const [surface, suffix] of [["hub", "/practice"], ["drill", "/practice?set=next-move"]]) {
      await page.send("Page.navigate", { url: "http://learner.localhost:3100" + suffix });
      await page.until(surface === "hub" ? "Boolean(document.querySelector('#practice-title'))" : `Boolean(${page.button("Check my response")})`);
      await page.evaluate("window.scrollTo(0,0)"); await page.delay(500);
      const screenshot = await page.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
      await writeFile(path.join(output, `${surface}-${label}.png`), Buffer.from(screenshot.data, "base64"));
      const bounds = await page.evaluate("({viewport:innerWidth,content:document.documentElement.scrollWidth,height:innerHeight})");
      process.stdout.write(JSON.stringify({ screenshot: `${surface}-${label}.png`, ...bounds }) + "\n");
    }
  }
  await page.send("Emulation.clearDeviceMetricsOverride");
  process.stdout.write(JSON.stringify({ external_requests: page.external(), viewport_only: true }) + "\n");
} catch { process.stderr.write("Local Arcade screenshot proof incomplete.\n"); process.exitCode = 1; }
finally { await page.close(); }
