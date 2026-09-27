// Local compiled UI only. All APIs are intercepted; no real call is submitted.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import vm from "node:vm";
import { chromium } from "playwright";
import ts from "typescript";

const origin = process.env.SALES_XRAY_QA_ORIGIN || "http://127.0.0.1:3118";
assert.match(origin, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
const fixturePath = path.resolve(
  "apps/sales-xray-web/tests/acquisition-fixture.ts",
);
const fixtureModule = { exports: {} };
vm.runInNewContext(
  ts.transpileModule(await readFile(fixturePath, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
  }).outputText,
  { exports: fixtureModule.exports, require: createRequire(fixturePath) },
);
const fixture = fixtureModule.exports;
const output = path.resolve(".tmp/sales-xray-new-call-navigation");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const viewport of [
    { width: 1024, height: 626 },
    { width: 390, height: 844 },
    { width: 375, height: 667 },
  ]) {
    const context = await browser.newContext({
      viewport,
      reducedMotion: "reduce",
    });
    let malformed = true;
    let reads = 0;
    const writes = [];
    await context.addInitScript(
      (id) => localStorage.setItem("ac.xray.submission.v1", id),
      fixture.submissionId,
    );
    await context.route("**/v1/**", async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      if (request.method() !== "GET")
        writes.push(`${request.method()} ${pathname}`);
      let status = 200;
      let body = {};
      if (pathname === "/v1/me/workspaces") status = 401;
      else if (pathname.endsWith("/entry")) body = fixture.entry;
      else if (pathname.endsWith("/availability")) body = { paused: false };
      else if (pathname.endsWith("/upload-policy")) body = fixture.policy;
      else if (pathname.endsWith("/session"))
        body = { state: "guest", allowance: fixture.allowance };
      else if (pathname.endsWith(`/submissions/${fixture.submissionId}`)) {
        reads++;
        body = malformed
          ? { malformed: true }
          : {
              ...fixture.progress,
              state: "held",
              local_state: "failed",
              stages: [{ stage: "C2", state: "uncertain" }],
            };
      } else status = 404;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    });
    await context.route("https://challenges.cloudflare.com/**", (route) =>
      route.abort(),
    );
    const page = await context.newPage();
    // Exclude Next's empty route-announcer live region outside the workspace.
    const errorAlert = page.locator('#main-content [role="alert"]');
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const callUrl = `${origin}/?call=${fixture.submissionId}`;
    await page.goto(callUrl);
    await errorAlert.waitFor();
    const escape = page.getByRole("button", {
      name: "Analyse another call",
      exact: true,
    });
    await escape.waitFor();
    const escapeBounds = await escape.boundingBox();
    assert.ok(
      escapeBounds.y >= 0 &&
        escapeBounds.y + escapeBounds.height <= viewport.height,
      "error escape must be inside viewport",
    );
    await page.screenshot({
      path: path.join(output, `error-${viewport.width}.png`),
    });
    const failedReads = reads;
    const nav = page.getByRole("navigation", {
      name: viewport.width > 620 ? "Workspace" : "Mobile Sales Xray navigation",
      exact: true,
    });
    await nav
      .getByRole("link", {
        name: viewport.width > 620 ? "Analyse a call" : "Analyse",
        exact: true,
      })
      .click();
    await page.waitForURL(`${origin}/?new=1`);
    await page.waitForFunction(
      () => document.querySelector('input[type="file"]')?.disabled === false,
    );
    assert.equal(
      await errorAlert.count(),
      0,
      (await errorAlert.allTextContents()).join(" "),
    );
    assert.equal(
      reads,
      failedReads,
      "new call must not read remembered submission",
    );
    await page.reload();
    await page.waitForFunction(
      () => document.querySelector('input[type="file"]')?.disabled === false,
    );
    assert.equal(reads, failedReads, "refresh preserves new-call intent");
    await page.goto(callUrl);
    await errorAlert.waitFor();
    await page
      .getByRole("button", { name: "Analyse another call", exact: true })
      .click();
    await page.waitForURL(`${origin}/?new=1`);
    await page.waitForFunction(
      () => document.querySelector('input[type="file"]')?.disabled === false,
    );
    await page.screenshot({
      path: path.join(output, `new-${viewport.width}.png`),
    });
    assert.equal(
      await page.evaluate(() => localStorage.getItem("ac.xray.submission.v1")),
      fixture.submissionId,
    );
    malformed = false;
    await page.goto(callUrl);
    await page
      .getByRole("heading", { name: "Analysis paused", exact: true })
      .waitFor();
    assert.deepEqual(
      writes,
      [],
      "new-call navigation must never mutate saved work",
    );
    assert.deepEqual(errors, []);
    results.push({
      ...viewport,
      escapeBounds,
      sidebarNewCall: true,
      reloadStaysNew: true,
      errorEscape: true,
      explicitCallRestores: true,
      savedSelectorPreserved: true,
      writes,
      errors,
    });
    await context.close();
  }
  await writeFile(
    path.join(output, "results.json"),
    JSON.stringify(
      {
        capturedAt: new Date().toISOString(),
        origin,
        data: "synthetic-only",
        results,
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify(results, null, 2));
} finally {
  await browser.close();
}
