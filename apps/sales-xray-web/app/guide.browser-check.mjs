// Run from the repository root with a local Sales Xray dev server. Every API
// request is intercepted; no customer data, uploads, or provider calls are used.
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import vm from "node:vm";
import { chromium } from "playwright";
import ts from "typescript";

const origin =
  process.env.SALES_XRAY_GUIDE_QA_ORIGIN || "http://127.0.0.1:3038";
assert.match(origin, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
const output = path.join(
  process.env.PAPERCLIP_RUN_SCRATCH_DIR ||
    process.env.PAPERCLIP_SCRATCH_DIR ||
    process.cwd(),
  "onboarding-guide-evidence",
);
await mkdir(output, { recursive: true });
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
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const width of [390, 1440]) {
    const context = await browser.newContext({
      viewport: { width, height: width === 390 ? 844 : 900 },
      reducedMotion: width === 390 ? "reduce" : "no-preference",
    });
    let liveState = "progress";
    const writes = [];
    await context.route("**/v1/**", async (route) => {
      const request = route.request();
      const pathname = new URL(request.url()).pathname;
      let body = {},
        status = 200;
      if (request.method() !== "GET") {
        writes.push(`${request.method()} ${pathname}`);
        return route.fulfill({
          status: 400,
          contentType: "application/json",
          body: "{}",
        });
      }
      if (pathname === "/v1/me/workspaces")
        body = {
          person_id: "fictional-guide-user",
          session_id: "fictional-session",
          selected_tenant_id: "fictional-personal",
          workspaces: [{ tenant_id: "fictional-personal", name: "Personal" }],
        };
      else if (pathname === "/v1/me/sales-xray-workspaces")
        body = {
          selected_tenant_id: "fictional-personal",
          workspaces: [
            {
              tenant_id: "fictional-personal",
              kind: "personal",
              name: "Personal",
              role: null,
              sales_xray_enabled: true,
            },
          ],
        };
      else if (pathname.endsWith("/write-eligibility")) status = 204;
      else if (pathname === "/v1/me/sales-xray-profile")
        body = {
          name: "Alex Example",
          email: "alex@example.test",
          phone_number_e164: null,
          phone_verified: false,
          profile_complete: true,
          revision: 1,
        };
      else if (pathname.endsWith("/entry"))
        body = {
          ...fixture.entry,
          auth_mode: "account",
          site_key: null,
          challenge_action: null,
        };
      else if (pathname.endsWith("/session"))
        body = { state: "claimed", allowance: fixture.allowance };
      else if (pathname.endsWith("/availability")) body = { paused: false };
      else if (pathname.endsWith("/upload-policy")) body = fixture.policy;
      else if (pathname.endsWith("/report")) body = fixture.envelope;
      else if (pathname.endsWith("/transcript")) body = fixture.transcript;
      else if (pathname.endsWith("/plan"))
        body = { ...fixture.plan, accepted: true, state: "active" };
      else if (pathname.includes("/submissions/"))
        body = {
          ...fixture.progress,
          state: liveState === "report" ? "completed" : "active",
          automatic_progression: true,
          has_report: liveState === "report",
          stages: ["C2", "C4", "C5"].map((stage, i) => ({
            stage,
            state:
              liveState === "report"
                ? "completed"
                : i === 0
                  ? "running"
                  : "queued",
          })),
        };
      else status = 404;
      await route.fulfill({
        status,
        contentType: "application/json",
        body: status === 204 ? "" : JSON.stringify(body),
      });
    });
    await context.route("https://challenges.cloudflare.com/**", (route) =>
      route.abort(),
    );
    const page = await context.newPage();
    page.setDefaultNavigationTimeout(120_000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const card = page.locator("[data-guide-card]");
    const step = (id) => page.locator(`[data-guide-step="${id}"]`);
    async function capture(name) {
      await page.evaluate(() => document.fonts.ready);
      const metrics = await card.evaluate((el) => {
        const r = el.getBoundingClientRect();
        return {
          left: r.left,
          right: r.right,
          top: r.top,
          bottom: r.bottom,
          animation: getComputedStyle(el).animationName,
          modal: !!document.querySelector('[aria-modal="true"]'),
        };
      });
      assert.ok(
        metrics.left >= 0 &&
          metrics.right <= width &&
          metrics.top >= 0 &&
          metrics.bottom <= (width === 390 ? 844 : 900),
        JSON.stringify(metrics),
      );
      assert.equal(metrics.modal, false);
      if (width === 390) assert.equal(metrics.animation, "none");
      await page.screenshot({
        path: path.join(output, `${name}-${width}.png`),
      });
      results.push({ width, state: name, ...metrics });
    }
    await page.goto(`${origin}/analysis/new`, {
      waitUntil: "domcontentloaded",
    });
    await step("welcome").waitFor();
    await capture("welcome");
    assert.notEqual(
      await page.evaluate(
        () => document.activeElement?.closest("[data-guide-card]") !== null,
      ),
      true,
    );
    for (const name of ["listen", "understand", "practise", "upload"]) {
      await card.getByRole("button", { name: "Next", exact: true }).click();
      await step(name).waitFor();
    }
    await page.locator("[data-guide-coach]").waitFor();
    assert.equal(
      await page
        .locator("[data-guide-coach]")
        .evaluate((el) => getComputedStyle(el).pointerEvents),
      "none",
    );
    await capture("upload");
    assert.equal(
      await page
        .getByRole("button", { name: "Choose a file", exact: true })
        .evaluate((el) => {
          const r = el.getBoundingClientRect();
          const top = document.elementFromPoint(
            r.left + r.width / 2,
            r.top + r.height / 2,
          );
          return top === el || el.contains(top);
        }),
      true,
      "guide must not cover the file picker",
    );
    // Use the real saved-call routes with a fictional pending receipt. This
    // tests reload/resume and automatic report arrival without uploading data.
    await page.goto(`${origin}/analysis/calls/${fixture.submissionId}`, {
      waitUntil: "domcontentloaded",
    });
    await step("progress").waitFor();
    await capture("progress");
    liveState = "report";
    await page.reload({ waitUntil: "domcontentloaded" });
    await step("report").waitFor();
    await capture("report");
    await card.getByRole("button", { name: "Next", exact: true }).click();
    await step("moments").waitFor();
    await capture("moments");
    await card.getByRole("button", { name: "Finish", exact: true }).click();
    await card.waitFor({ state: "hidden" });
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle");
    // Owner, 5 Oct 2026: a finished or closed guide stays off, with no
    // floating launcher; the account menu switch turns it back on.
    assert.equal(await card.count(), 0);
    assert.equal(await page.locator("[data-guide-launcher]").count(), 0);
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    results.push({
      width,
      finishSurvivesReload: true,
      noLauncher: true,
      apiWrites: 0,
      browserErrors: 0,
    });
    await context.close();
  }
  await writeFile(
    path.join(output, "results.json"),
    JSON.stringify(
      { origin, data: "fictional-only; every API intercepted", results },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ output, results }, null, 2));
} finally {
  await browser.close();
}
