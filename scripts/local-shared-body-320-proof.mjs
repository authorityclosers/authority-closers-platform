// Read-only regression for the shared body minimum-width correction.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { localPage } from "./local-page-cdp.mjs";
const origin = "http://learner.localhost:3100";
const output = path.resolve(
  "docs/evidence/screenshots",
  "shared-body-320-" + new Date().toISOString().replace(/[:.]/g, "-"),
);
const page = await localPage({ pathname: "/learning", newTab: true });
const checks = [];
const navigate = async (pathname) => {
  const previous = await page.evaluate("performance.timeOrigin");
  await page.send("Page.navigate", { url: origin + pathname });
  await page.until(
    `performance.timeOrigin!==${previous}&&location.origin===${JSON.stringify(origin)}&&document.readyState==='complete'`,
    60000,
  );
};
const capture = async (name) => {
  await page.evaluate("window.scrollTo(0,0)");
  await page.delay(250);
  const width = await page.evaluate(
    "({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,bodyMin:getComputedStyle(document.body).minWidth})",
  );
  if (width.scroll > width.client + 1 || width.bodyMin !== "0px") throw Error();
  const image = await page.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await writeFile(
    path.join(output, name + ".png"),
    Buffer.from(image.data, "base64"),
    { flag: "wx" },
  );
  checks.push({ name, ...width });
};
try {
  await page.until(
    `location.origin===${JSON.stringify(origin)}&&Boolean(document.querySelector('main a[href="/learn/authority-closers-free-course"]'))`,
    60000,
  );
  const allowed = await page.evaluate(
    "fetch('/v1/me',{credentials:'same-origin',cache:'no-store',redirect:'error'}).then(async r=>{if(!r.ok)throw Error();const m=await r.json();return m.email==='learner@ac.localhost'&&m.membership_role==='learner'&&m.selected_tenant_id==='65e76922-c033-5459-9101-3de86637246e';})",
  );
  if (!allowed) throw Error();
  await mkdir(output, { recursive: false });
  await page.send("Emulation.setDeviceMetricsOverride", {
    width: 320,
    height: 740,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await navigate("/learn/authority-closers-free-course");
  await page.until(
    "Boolean(document.querySelector('main a[href*=\"/module/\"]'))",
  );
  await capture("01-course");
  const module = await page.evaluate(
    "document.querySelector('main a[href*=\"/module/\"]').getAttribute('href')",
  );
  if (!module.startsWith("/learn/")) throw Error();
  await navigate(module);
  await page.until(
    "Boolean(document.querySelector('main a[href^=\"/activity/\"]'))",
  );
  await capture("02-module");
  await navigate("/profile");
  await page.until(
    `Boolean(${page.button("Change photo")})&&[...document.querySelectorAll('main img')].some(e=>e.alt.includes('profile photo')&&e.complete&&e.naturalWidth===512)`,
    60000,
  );
  await capture("03-profile");
  if (page.external() !== 0) throw Error();
  const proof = {
    status: "passed",
    viewport_width: 320,
    read_only: true,
    external_requests: 0,
    checks,
  };
  await writeFile(
    path.join(output, "proof.json"),
    JSON.stringify(proof, null, 2) + "\n",
    { flag: "wx" },
  );
  process.stdout.write(JSON.stringify({ ...proof, output }) + "\n");
} catch {
  process.stderr.write(
    "Shared body 320px read-only regression incomplete; no private diagnostics emitted.\n",
  );
  process.exitCode = 1;
} finally {
  await page.send("Emulation.clearDeviceMetricsOverride").catch(() => {});
  await page.close();
}
