// The visual test matrix on a GitHub-hosted runner (`wb-ci --matrix [screen|route ...]`; owner via the orchestrator,
// 25 Oct 2026). Review fixtures (fictional data, no API origin, no credentials) at 7 phone and tablet sizes, font
// scale 85/100/115/130% and light and dark, measured in the page (wb_matrix_lib.mjs). The output is one small folder:
// report.md (also the step summary), matrix.json (every state's numbers) and one JPEG contact sheet per screen.
//
//   node scripts/ci/wb_matrix.mjs <output-dir> [.wb-ci/request.json]
import { spawn } from "node:child_process";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { chromium } from "playwright";
import { waitForFixtureServer } from "./sales_xray_visual.mjs";
import {
  SIZES,
  measure,
  onSheet,
  pickScreens,
  report,
  states,
  tagOf,
  textZoom,
  viewportOf,
  zoomOf,
} from "./wb_matrix_lib.mjs";

const origin = "http://127.0.0.1:18216";
const WORKERS = 3;

/** Same-origin reads only; nothing leaves the runner. The acquisition fixtures read one fixed review flag. */
async function local(route) {
  const request = route.request();
  const url = new URL(request.url());
  if (url.origin !== origin || request.method() !== "GET") return route.abort();
  if (url.pathname === "/health" && !url.search)
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"analysis_read_only":true}',
    });
  return route.continue();
}

async function step(page, item) {
  if (item.click) {
    const target = page.locator(item.click).first();
    if (item.optional && !(await target.count())) return;
    await target.click({ timeout: 10000 });
  }
  if (item.wait) await page.waitForSelector(item.wait, { timeout: 20000 });
  await page.waitForTimeout(250);
}

async function sheet(browser, output, key, shots) {
  const columns = [
    ["100% light", (s) => s.scale === 1 && s.theme === "light"],
    ["130% app", (s) => s.scale === 1.3 && s.mode === "app"],
    ["130% text", (s) => s.scale === 1.3 && s.mode === "text"],
    ["100% dark", (s) => s.scale === 1 && s.theme === "dark"],
  ];
  const cells = [];
  for (const size of SIZES)
    for (const [label, test] of columns) {
      const shot = shots.find(
        (item) => item.state.label === size.label && test(item.state),
      );
      const data = shot ? (await readFile(shot.path)).toString("base64") : null;
      cells.push(
        `<figure>${data ? `<img src="data:image/jpeg;base64,${data}">` : "<div class=none>failed</div>"}` +
          `<figcaption>${size.label} · ${label}</figcaption></figure>`,
      );
    }
  const page = await browser.newPage({
    viewport: { width: 4 * 200 + 40, height: 600 },
  });
  await page.setContent(
    `<style>body{margin:16px;font:12px system-ui;background:#fff;color:#111}h1{font-size:16px;margin:0 0 12px}` +
      `main{display:grid;grid-template-columns:repeat(4,192px);gap:8px}figure{margin:0}` +
      `img{display:block;width:192px;border:1px solid #ccc}.none{height:120px;border:1px dashed #c00}` +
      `figcaption{padding:2px 0 6px;color:#555}</style><h1>${key}</h1><main>${cells.join("")}</main>`,
  );
  await page.screenshot({
    path: resolve(output, `sheet-${key}.jpg`),
    type: "jpeg",
    quality: 70,
    fullPage: true,
  });
  await page.close();
}

async function main() {
  const [output, requestPath = ".wb-ci/request.json"] = process.argv.slice(2);
  const shotsDir = resolve(output, "shots");
  await mkdir(shotsDir, { recursive: true });
  let request = {};
  try {
    request = JSON.parse(await readFile(requestPath, "utf8"));
  } catch {}
  const screens = pickScreens(request.routes ?? []);
  const jobs = states().flatMap((state) =>
    screens.map(([key, screen]) => ({ key, screen, state })),
  );
  const env = Object.fromEntries(
    ["PATH", "HOME", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH"]
      .filter((key) => process.env[key])
      .map((key) => [key, process.env[key]]),
  );
  const server = spawn(
    process.execPath,
    [
      resolve("apps/sales-xray-web/node_modules/next/dist/bin/next"),
      "dev",
      "--turbopack",
      "--hostname",
      "127.0.0.1",
      "--port",
      "18216",
    ],
    {
      cwd: resolve("apps/sales-xray-web"),
      detached: true,
      stdio: "ignore",
      env: { ...env, AC_SALES_XRAY_REVIEW: "1", NEXT_TELEMETRY_DISABLED: "1" },
    },
  );
  const stop = () => {
    try {
      process.kill(-server.pid, "SIGTERM");
    } catch {}
  };
  const started = Date.now();
  const deadline = setTimeout(
    () => {
      stop();
      process.exit(1);
    },
    25 * 60 * 1000,
  );
  const rows = [];
  const shots = [];
  let browser;
  try {
    await waitForFixtureServer(
      `${origin}/review-fixture/shell`,
      () => server.exitCode === null,
    );
    browser = await chromium.launch();
    // Compile each route once, so the first measured state isn't the compile.
    const warm = await browser.newPage();
    for (const [, screen] of screens)
      await warm
        .goto(origin + screen.path, {
          waitUntil: "networkidle",
          timeout: 180000,
        })
        .catch(() => undefined);
    await warm.close();
    let next = 0;
    const worker = async () => {
      while (next < jobs.length) {
        const { key, screen, state } = jobs[next++];
        const tag = tagOf(key, state);
        const zoom = zoomOf(state);
        const context = await browser.newContext({
          viewport: viewportOf(state),
          deviceScaleFactor: zoom,
          colorScheme: state.theme,
          isMobile: state.width < 768,
          hasTouch: true,
          locale: "en-GB",
          reducedMotion: "reduce",
          serviceWorkers: "block",
          acceptDownloads: false,
        });
        const errors = [];
        try {
          await context.route("**/*", local);
          const page = await context.newPage();
          page.on("console", (message) => {
            if (message.type() === "error")
              errors.push(message.text().slice(0, 160));
          });
          await page.goto(origin + screen.path, {
            waitUntil: "networkidle",
            timeout: 90000,
          });
          await page.waitForTimeout(400);
          for (const item of screen.steps ?? []) await step(page, item);
          if (state.mode === "text" && state.scale !== 1)
            await page.evaluate(textZoom, state.scale);
          await page.waitForTimeout(150);
          const facts = await page.evaluate(measure);
          if (onSheet(state)) {
            const path = resolve(
              shotsDir,
              `${tag.replace(/[^a-z0-9]+/gi, "-")}.jpg`,
            );
            await page.screenshot({
              path,
              type: "jpeg",
              quality: 60,
              scale: "css",
            });
            shots.push({ key, state, path });
          }
          // One whole page per screen, phone size: the slice's before and after shot.
          if (
            state.width === 390 &&
            state.scale === 1 &&
            state.mode === "app" &&
            state.theme === "light"
          )
            await page.screenshot({
              path: resolve(output, `page-${key}.jpg`),
              type: "jpeg",
              quality: 70,
              fullPage: true,
              scale: "css",
            });
          rows.push({ key, tag, ...state, ...facts, errors: [...errors] });
        } catch (error) {
          rows.push({
            key,
            tag,
            ...state,
            failed: String(error?.message ?? error)
              .split("\n")[0]
              .slice(0, 200),
          });
        } finally {
          await context.close();
        }
      }
    };
    await Promise.all(Array.from({ length: WORKERS }, worker));
    for (const [key] of screens)
      await sheet(
        browser,
        output,
        key,
        shots.filter((shot) => shot.key === key),
      );
  } finally {
    clearTimeout(deadline);
    await browser?.close();
    stop();
    await rm(shotsDir, { recursive: true, force: true });
  }
  const order = new Map(
    jobs.map((job, index) => [tagOf(job.key, job.state), index]),
  );
  rows.sort((a, b) => order.get(a.tag) - order.get(b.tag));
  const text = report(rows, request.source_sha ?? null);
  await writeFile(resolve(output, "report.md"), text);
  await writeFile(
    resolve(output, "matrix.json"),
    JSON.stringify(
      {
        schema: "wb-ci-matrix/1",
        source_sha: request.source_sha ?? null,
        elapsed_seconds: Math.round((Date.now() - started) / 1000),
        rows,
      },
      null,
      1,
    ),
  );
  if (process.env.GITHUB_STEP_SUMMARY)
    await writeFile(process.env.GITHUB_STEP_SUMMARY, text, { flag: "a" });
  console.log(text);
  // Findings are the report; the job fails only when the matrix could not run (over a tenth of states failed).
  const failed = rows.filter((row) => row.failed).length;
  process.exit(failed > jobs.length / 10 ? 1 : 0);
}

await main();
