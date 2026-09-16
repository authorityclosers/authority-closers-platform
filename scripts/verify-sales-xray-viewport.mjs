// Synthetic browser QA only: every API request is intercepted before it can
// reach the production bridge. This never submits an actual recording.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import vm from "node:vm";
import { chromium } from "playwright";
import ts from "typescript";

const root = process.cwd();
const fixturePath = path.join(
  root,
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
const origin =
  process.env.SALES_XRAY_QA_ORIGIN || "http://salesxray.localhost:3016";
assert.match(
  origin,
  /^http:\/\/(salesxray\.localhost|127\.0\.0\.1|localhost):\d+$/,
);
const output = path.join(root, ".tmp/sales-xray-ui-qa");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
async function assertReportFits(page, state, viewport) {
  const metrics = await page.evaluate(() => {
    const main = document.querySelector(".studio-main");
    const panel = document.querySelector(
      '[data-report-section] > [role="tabpanel"]:not([hidden])',
    );
    const dock = document.querySelector('[aria-label="Call audio player"]');
    return {
      mainHeight: main.clientHeight,
      mainScroll: main.scrollHeight,
      contentBottom: panel.getBoundingClientRect().bottom,
      playerTop: dock.getBoundingClientRect().top,
    };
  });
  assert.ok(
    metrics.mainScroll <= metrics.mainHeight + 1,
    `${state} inner overflow at ${viewport.width}: ${JSON.stringify(metrics)}`,
  );
  assert.ok(
    metrics.contentBottom <= metrics.playerTop + 1,
    `${state} covered by audio player at ${viewport.width}: ${JSON.stringify(metrics)}`,
  );
  results.push({ state, ...viewport, ...metrics, fits: true });
}
// A valid, silent one-second PCM WAV so preview errors do not distort layout.
const sampleAudio = Buffer.alloc(16044);
sampleAudio.write("RIFF", 0);
sampleAudio.writeUInt32LE(16036, 4);
sampleAudio.write("WAVEfmt ", 8);
sampleAudio.writeUInt32LE(16, 16);
sampleAudio.writeUInt16LE(1, 20);
sampleAudio.writeUInt16LE(1, 22);
sampleAudio.writeUInt32LE(8000, 24);
sampleAudio.writeUInt32LE(16000, 28);
sampleAudio.writeUInt16LE(2, 32);
sampleAudio.writeUInt16LE(16, 34);
sampleAudio.write("data", 36);
sampleAudio.writeUInt32LE(16000, 40);
try {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1024, height: 626 },
    { width: 390, height: 844 },
    { width: 375, height: 667 },
  ]) {
    if (
      process.env.SALES_XRAY_QA_WIDTH &&
      viewport.width !== Number(process.env.SALES_XRAY_QA_WIDTH)
    )
      continue;
    for (const state of (
      process.env.SALES_XRAY_QA_STATES ||
      "entry,selected,verification,uploading,C2,C4,C5,delayed-C2,delayed-C4,delayed-C5,held,report,calls"
    ).split(",")) {
      const context = await browser.newContext({
        viewport,
        reducedMotion: "reduce",
      });
      let apiRequests = 0;
      const delayedState = state.startsWith("delayed-");
      const mutations = [];
      let liveState = delayedState ? state.slice("delayed-".length) : state;
      let sourceId = fixture.submissionId;
      let sourceSha = fixture.progress.source_sha256;
      let finishUpload;
      const uploadGate = new Promise((resolve) => {
        finishUpload = resolve;
      });
      if (state === "verification")
        await context.addInitScript(() => {
          let mounted;
          window.turnstile = {
            render(element) {
              mounted = element;
              const check = document.createElement("button");
              check.textContent = "Synthetic verification widget";
              check.style.cssText =
                "height:65px;width:100%;background:#f8fafc;border:1px solid #dce4f0;border-radius:8px;color:#60738f";
              element.append(check);
              return "test-widget";
            },
            remove() {
              mounted?.replaceChildren();
            },
          };
        });
      await context.route("**/v1/**", async (route) => {
        apiRequests++;
        if (route.request().method() !== "GET")
          mutations.push(
            route.request().method() +
              " " +
              new URL(route.request().url()).pathname,
          );
        const url = new URL(route.request().url());
        let body = {};
        let status = 200;
        if (url.pathname === "/v1/me/workspaces") status = 401;
        else if (url.pathname.endsWith("/entry")) body = fixture.entry;
        else if (url.pathname.endsWith("/availability"))
          body = { paused: false };
        else if (url.pathname.endsWith("/upload-policy")) body = fixture.policy;
        else if (url.pathname.endsWith("/session")) {
          if (state === "verification") status = 401;
          else body = { state: "guest", allowance: fixture.allowance };
        } else if (url.pathname.endsWith("/report"))
          body = {
            ...fixture.envelope,
            submission_id: sourceId,
            source_sha256: sourceSha,
          };
        else if (url.pathname.endsWith("/transcript"))
          body = { ...fixture.transcript, source_sha256: sourceSha };
        else if (
          url.pathname.endsWith("/source") &&
          route.request().method() === "PUT"
        ) {
          sourceId = url.pathname.split("/")[5];
          sourceSha = route.request().headers()["x-source-sha256"];
          if (!(await uploadGate)) return route.abort();
          body = {
            ...fixture.progress,
            submission_id: sourceId,
            source_sha256: sourceSha,
            allowance: fixture.allowance,
          };
          status = 202;
        } else if (
          url.pathname.endsWith("/waveform") ||
          url.pathname.endsWith("/source")
        )
          status = 404;
        else if (url.pathname.endsWith("/plan/quote")) body = fixture.plan;
        else if (url.pathname.endsWith("/plan"))
          body = { ...fixture.plan, accepted: true, state: "active" };
        else if (url.pathname.includes("/submissions/")) {
          const active = ["C2", "C4", "C5"].indexOf(liveState);
          body = {
            ...fixture.progress,
            submission_id: sourceId,
            source_sha256: sourceSha,
            state: liveState === "held" ? "held" : "active",
            local_state: "completed",
            automatic_progression: true,
            has_report: liveState === "report",
            stages: ["C2", "C4", "C5"].map((stage, i) => ({
              stage,
              state:
                liveState === "held"
                  ? i === 0
                    ? "completed"
                    : i === 1
                      ? "uncertain"
                      : "queued"
                  : i < active
                    ? "completed"
                    : i === active
                      ? "running"
                      : "queued",
            })),
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
      if (delayedState) await page.clock.install();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const selected = ["selected", "verification", "uploading"].includes(
        state,
      );
      const saved = ![
        "entry",
        "selected",
        "verification",
        "uploading",
        "calls",
      ].includes(state);
      await page.goto(
        `${origin}${state === "calls" ? "/calls" : saved ? `/?call=${fixture.submissionId}` : "/"}`,
        { waitUntil: "domcontentloaded" },
      );
      await page.locator("#main-content").waitFor();
      if (selected) {
        await page.locator("input[type=file]").waitFor({ state: "attached" });
        await page.waitForFunction(
          () => !document.querySelector("input[type=file]")?.disabled,
        );
        await page.locator("input[type=file]").setInputFiles({
          name: "Synthetic discovery call.wav",
          mimeType: "audio/wav",
          buffer: sampleAudio,
        });
        await page
          .getByRole("button", { name: "Analyse my call", exact: true })
          .waitFor();
        if (state === "uploading") {
          await page.getByRole("checkbox").check();
          await page
            .getByRole("button", { name: "Analyse my call", exact: true })
            .click();
          await page
            .getByRole("heading", { name: "Your call is on its way." })
            .waitFor();
          assert.equal(
            await page.getByRole("checkbox").count(),
            0,
            "consent form must not be duplicated under upload progress",
          );
        }
      } else if (state === "report")
        await page
          .getByRole("tab", { name: "Overview", exact: true })
          .waitFor();
      else if (saved)
        await page.locator('[aria-label="Processing stages"]').waitFor();
      await page.waitForTimeout(300);
      await page.evaluate(() => document.fonts.ready);
      await page.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      if (delayedState) {
        const readLayout = () =>
          page.evaluate(() => {
            const status = document
              .querySelector("[data-update-delayed]")
              .closest('[role="status"]');
            return [...status.children].map((element) => {
              const { x, y, width, height } = element.getBoundingClientRect();
              return { x, y, width, height };
            });
          });
        const before = await readLayout();
        await page.clock.fastForward(60_001);
        await page.locator('[data-update-delayed="true"]').waitFor();
        const after = await readLayout();
        assert.deepEqual(
          after,
          before,
          `${state} must not move the panel at ${viewport.width}`,
        );
        assert.equal(
          await page
            .locator(`[data-stage="${liveState}"][data-state="running"]`)
            .count(),
          1,
        );
        assert.equal(
          await page
            .getByRole("status")
            .getByText("WAITING FOR AN UPDATE", { exact: true })
            .count(),
          1,
        );
        assert.equal(await page.locator('[data-paused="true"]').count(), 0);
        assert.equal(
          await page
            .getByRole("link", { name: "Open saved calls", exact: true })
            .getAttribute("href"),
          "/calls",
        );
        assert.deepEqual(
          mutations,
          [],
          "waiting must not submit, approve or reupload work",
        );
        results.push({
          state: `${state}-stable-layout`,
          ...viewport,
          before,
          after,
          mutations,
          verified: true,
        });
      }
      const metrics = await page.evaluate(() => {
        const main = document.querySelector(".studio-main");
        const primary = document.querySelector(".studio-wide");
        const rect = primary?.getBoundingClientRect();
        return {
          width: innerWidth,
          height: innerHeight,
          docWidth: document.documentElement.scrollWidth,
          docHeight: document.documentElement.scrollHeight,
          mainHeight: main?.clientHeight,
          mainScroll: main?.scrollHeight,
          primaryBottom: rect?.bottom,
          stage: document
            .querySelector(".xray-app[data-stage]")
            ?.getAttribute("data-stage"),
        };
      });
      await page.screenshot({
        path: path.join(
          output,
          `${state}-${viewport.width}x${viewport.height}.png`,
        ),
      });
      assert.ok(
        metrics.docHeight <= viewport.height + 1,
        `${state} page vertical overflow ${JSON.stringify(metrics)}`,
      );
      assert.ok(
        metrics.docWidth <= viewport.width + 1,
        `${state} page horizontal overflow`,
      );
      if (selected && state !== "uploading")
        assert.ok(
          metrics.primaryBottom <=
            viewport.height - (viewport.width < 621 ? 78 : 0),
          `${state} action offscreen: ${JSON.stringify(metrics)}`,
        );
      if (state !== "report")
        assert.ok(
          metrics.mainScroll <= metrics.mainHeight + 1,
          `${state} inner viewport overflow: ${JSON.stringify(metrics)}`,
        );
      assert.deepEqual(errors, [], `${state} page errors`);
      results.push({ state, ...metrics, apiRequests });
      if (delayedState) {
        liveState = "held";
        await page.clock.fastForward(3_001);
        await page
          .getByRole("heading", { name: "Analysis paused", exact: true })
          .waitFor();
        assert.equal(await page.locator("[data-update-delayed]").count(), 0);
        assert.equal(
          await page.locator('[data-stage="C2"] small').textContent(),
          "Complete",
        );
        assert.deepEqual(
          mutations,
          [],
          "paused recovery must not start itself",
        );
        assert.equal(
          await page
            .locator(".studio-main")
            .evaluate((main) => main.scrollHeight <= main.clientHeight + 1),
          true,
        );
        results.push({
          state: `${state}-to-held`,
          ...viewport,
          verified: true,
        });
      }
      if (state === "entry") {
        const profile = page
          .getByRole("button", { name: "Open profile menu", exact: true })
          .filter({ visible: true });
        await profile.focus();
        await page.keyboard.press("Enter");
        await page.getByRole("region", { name: "Profile actions" }).waitFor();
        await page.keyboard.press("Tab");
        assert.equal(
          await page.evaluate(() =>
            document.activeElement?.textContent?.trim(),
          ),
          "Sign in to my AC account",
        );
        await page.keyboard.press("Escape");
        assert.equal(
          await profile.evaluate((button) => button === document.activeElement),
          true,
          "Escape returns profile focus",
        );
        assert.equal(await profile.getAttribute("aria-expanded"), "false");
        if (viewport.width > 620) {
          await page
            .getByRole("button", { name: "Collapse Sales Xray navigation" })
            .click();
          await page
            .getByRole("button", { name: "Expand Sales Xray navigation" })
            .waitFor();
          assert.equal(
            await page.evaluate(
              () =>
                document.documentElement.scrollWidth <= innerWidth &&
                document.documentElement.scrollHeight <= innerHeight,
            ),
            true,
          );
          await page
            .getByRole("button", { name: "Expand Sales Xray navigation" })
            .click();
        }
        results.push({
          state: "shell-keyboard",
          width: viewport.width,
          verified: true,
        });
      }
      if (state === "uploading") {
        liveState = "C2";
        finishUpload(true);
        for (const phase of ["C2", "C4", "C5"]) {
          liveState = phase;
          await page
            .locator(`[data-stage="${phase}"][data-state="running"]`)
            .waitFor();
          const fit = await page
            .locator(".studio-main")
            .evaluate((main) => main.scrollHeight <= main.clientHeight + 1);
          assert.ok(
            fit,
            `automatic ${phase} transition overflows at ${viewport.width}`,
          );
        }
        liveState = "report";
        await page
          .getByRole("tab", { name: "Overview", exact: true })
          .waitFor();
        assert.equal(
          new URL(page.url()).pathname,
          "/",
          "transition stays in the same workspace",
        );
        assert.deepEqual(errors, [], "automatic transition errors");
        results.push({
          state: "upload-to-report",
          width: viewport.width,
          verified: true,
        });
      }
      if (state === "report") {
        for (const tab of ["Moments", "Sales skills", "Next-call plan"]) {
          await page.getByRole("tab", { name: tab, exact: true }).click();
          const tabMetrics = await page.evaluate(() => {
            const main = document.querySelector(".studio-main");
            const panel = document.querySelector(
              '[data-report-section] > [role="tabpanel"]:not([hidden])',
            );
            const dock = document.querySelector(
              '[aria-label="Call audio player"]',
            );
            return {
              mainHeight: main.clientHeight,
              mainScroll: main.scrollHeight,
              contentBottom: panel.getBoundingClientRect().bottom,
              playerTop: dock.getBoundingClientRect().top,
            };
          });
          results.push({
            state: tab,
            width: viewport.width,
            height: viewport.height,
            ...tabMetrics,
          });
          if (tab !== "Moments")
            await assertReportFits(page, `${tab} fit`, viewport);
          await page.screenshot({
            path: path.join(
              output,
              `${tab.toLowerCase().replaceAll(" ", "-")}-${viewport.width}x${viewport.height}.png`,
            ),
          });
          if (tab === "Sales skills") {
            const opener = page
              .getByRole("button", { name: /^Open notes:/ })
              .filter({ visible: true })
              .first();
            await opener.click();
            const dialog = page.getByRole("dialog");
            await dialog.waitFor();
            await page.screenshot({
              path: path.join(
                output,
                `skill-notes-${viewport.width}x${viewport.height}.png`,
              ),
            });
            for (let index = 1; index < 8; index++)
              await dialog.getByRole("button", { name: "Next skill" }).click();
            assert.equal(
              await dialog
                .getByRole("button", { name: "Next skill" })
                .isDisabled(),
              true,
            );
            assert.equal(
              await page.evaluate(() => document.activeElement.tagName),
              "H2",
            );
            await page.keyboard.press("Shift+Tab");
            assert.equal(
              await dialog
                .getByRole("button", { name: "Previous skill" })
                .evaluate((el) => el === document.activeElement),
              true,
            );
            await page.keyboard.press("Tab");
            assert.equal(
              await dialog
                .getByRole("button", { name: "Close skill notes" })
                .evaluate((el) => el === document.activeElement),
              true,
            );
            await page.keyboard.press("Escape");
            assert.equal(
              await opener.evaluate((el) => el === document.activeElement),
              true,
            );
            if (viewport.width <= 1100 || viewport.height <= 740) {
              await page
                .getByRole("button", { name: "Next skills", exact: true })
                .click();
              assert.equal(
                await page
                  .getByRole("button", { name: /^Open notes:/ })
                  .filter({ visible: true })
                  .count(),
                4,
              );
              await page.screenshot({
                path: path.join(
                  output,
                  `skills-page-2-${viewport.width}x${viewport.height}.png`,
                ),
              });
              await assertReportFits(page, "Sales skills page 2", viewport);
            }
          }
          if (tab === "Next-call plan") {
            const opener = page.getByRole("button", {
              name: /Read full notes.*Keep doing this/,
            });
            await opener.click();
            await page.getByRole("dialog").waitFor();
            await page.screenshot({
              path: path.join(
                output,
                `plan-notes-${viewport.width}x${viewport.height}.png`,
              ),
            });
            await page.keyboard.press("Escape");
            if (viewport.width <= 620) {
              for (const name of ["Change", "Practise"]) {
                await page.getByRole("button", { name, exact: true }).click();
                await assertReportFits(page, `Plan ${name}`, viewport);
                await page.screenshot({
                  path: path.join(
                    output,
                    `plan-${name.toLowerCase()}-${viewport.width}x${viewport.height}.png`,
                  ),
                });
              }
            }
          }
          if (tab !== "Moments") {
            await page.emulateMedia({ media: "print" });
            const printState = await page.evaluate((label) => {
              const section = document.querySelector(
                `section[aria-label="${label}"]`,
              );
              return [...section.querySelectorAll("article")].map((card) => ({
                visible: getComputedStyle(card).display !== "none",
                titleClamp: getComputedStyle(card.querySelector("h3"))
                  .webkitLineClamp,
                paragraphs: [...card.querySelectorAll("p")].map((p) => ({
                  display: getComputedStyle(p).display,
                  clamp: getComputedStyle(p).webkitLineClamp,
                })),
              }));
            }, tab);
            assert.equal(printState.length, tab === "Sales skills" ? 8 : 3);
            assert.ok(
              printState.every(
                (card) =>
                  card.visible &&
                  card.titleClamp === "none" &&
                  card.paragraphs.every(
                    (p) => p.display !== "none" && p.clamp === "none",
                  ),
              ),
              `${tab} print must include complete notes`,
            );
            await page.emulateMedia({ media: "screen" });
            results.push({
              state: `${tab} complete print`,
              ...viewport,
              verified: true,
            });
          }
        }
        await page.getByRole("tab", { name: "Overview", exact: true }).click();
        await page.locator('[data-insight-number="02"]').click();
        await page.getByRole("dialog").waitFor();
        await page.screenshot({
          path: path.join(
            output,
            `review-${viewport.width}x${viewport.height}.png`,
          ),
        });
        await page.keyboard.press("Escape");
        await page.getByRole("dialog").waitFor({ state: "hidden" });
      }
      finishUpload();
      await context.close();
    }
  }
  console.log(JSON.stringify(results, null, 2));
  if (results.some((result) => result.state === "Sales skills")) {
    for (const [name, rendered] of [
      ["skills", "sales-skills"],
      ["plan", "next-call-plan"],
    ]) {
      for (const [kind, width, height] of [
        ["desktop", 1440, 900],
        ["mobile", 375, 667],
      ]) {
        if (
          process.env.SALES_XRAY_QA_WIDTH &&
          width !== Number(process.env.SALES_XRAY_QA_WIDTH)
        )
          continue;
        const reference = await readFile(
          path.join(
            root,
            `docs/design/sales-xray-20260916/${name}-${kind}-v1.png`,
          ),
        );
        const implementation = await readFile(
          path.join(output, `${rendered}-${width}x${height}.png`),
        );
        const comparison = await browser.newPage({
          viewport: { width: width * 2, height: height + 36 },
        });
        await comparison.setContent(
          `<style>body{margin:0;font:14px sans-serif;display:flex;background:#edf1f5}figure{margin:0;width:${width}px}figcaption{height:36px;box-sizing:border-box;padding:10px}img{width:${width}px;height:${height}px;object-fit:contain;display:block;background:white}</style><figure><figcaption>Generated reference · ${name} · normalized ${width}×${height}</figcaption><img src="data:image/png;base64,${reference.toString("base64")}"></figure><figure><figcaption>Compiled implementation · synthetic report · ${width}×${height}</figcaption><img src="data:image/png;base64,${implementation.toString("base64")}"></figure>`,
        );
        await comparison
          .locator("img")
          .evaluateAll((images) =>
            Promise.all(images.map((img) => img.decode())),
          );
        await comparison.screenshot({
          path: path.join(output, `comparison-${name}-${kind}.png`),
        });
        await comparison.close();
      }
    }
  }
  await writeFile(
    path.join(output, "viewport-results.json"),
    JSON.stringify(
      {
        capturedAt: new Date().toISOString(),
        origin,
        data: "synthetic-only",
        browser: "Chromium",
        reducedMotion: true,
        results,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
