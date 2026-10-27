// The speed check on a GitHub-hosted runner (`wb-ci --speed`; the owner, 27 Oct 2026, via the orchestrator: "on
// low-end devices with the worst processors this app might be slow"). It serves the production standalone build made
// with AC_SALES_XRAY_PERF_FIXTURES=1 (app/perf-fixture: the review fixtures' fictional screens, no API), then times
// each key screen's load and taps with Chromium's CPU slowed to 1x, 4x and 6x, one run at a time so nothing else
// shares the CPU. Output: report.md (also the step summary) and speed.json; ac-bug-radar turns what is slow into
// AC Pulse cards (perf:<screen>:<action>).
//
//   node scripts/ci/wb_speed.mjs <output-dir> [.wb-ci/request.json]
import { spawn } from "node:child_process";
import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { get as httpGet } from "node:http";
import { resolve } from "node:path";
import { chromium } from "playwright";
import {
  ACTIONS,
  RATES,
  RUNS,
  SPEED_INIT,
  VIEWPORT,
  classify,
  cpuByRate,
  pickSpeedScreens,
  speedMarkdown,
  summarize,
} from "./wb_speed_lib.mjs";

const PORT = 18316;
const origin = `http://127.0.0.1:${PORT}`;
const APP = resolve("apps/sales-xray-web");
const STANDALONE = resolve(APP, ".next/standalone/apps/sales-xray-web");

const status = (url) =>
  new Promise((done) => {
    const request = httpGet(url, { timeout: 30000 }, (response) => {
      response.resume();
      done(response.statusCode ?? 0);
    });
    request.on("error", () => done(0));
    request.on("timeout", () => request.destroy());
  });

/** The standalone server; Next leaves its static files to the deployment, as Dockerfile.web copies them. */
async function server() {
  await cp(resolve(APP, ".next/static"), resolve(STANDALONE, ".next/static"), {
    recursive: true,
  });
  await cp(resolve(APP, "public"), resolve(STANDALONE, "public"), {
    recursive: true,
  }).catch(() => undefined);
  const child = spawn(process.execPath, [resolve(STANDALONE, "server.js")], {
    cwd: STANDALONE,
    detached: true,
    stdio: "ignore",
    env: {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      NODE_ENV: "production",
      PORT: String(PORT),
      HOSTNAME: "127.0.0.1",
      AC_SALES_XRAY_PERF_FIXTURES: "1",
      NEXT_TELEMETRY_DISABLED: "1",
    },
  });
  const stop = () => {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {}
  };
  const deadline = Date.now() + 90000;
  let last = 0;
  while (Date.now() < deadline && child.exitCode === null) {
    last = await status(`${origin}/perf-fixture/home`);
    if (last === 200) return { stop };
    await new Promise((done) => setTimeout(done, 500));
  }
  stop();
  throw new Error(
    `the speed build's server never answered 200 (last ${last}); was it built with AC_SALES_XRAY_PERF_FIXTURES=1?`,
  );
}

/** A fresh phone at one CPU rate: same-origin reads only, the timing hooks in before the first script. */
async function open(browser, rate) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    locale: "en-GB",
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  await context.addInitScript({ content: SPEED_INIT });
  await context.route("**/*", (route) => {
    const request = route.request();
    return new URL(request.url()).origin !== origin ||
      request.method() !== "GET"
      ? route.abort()
      : route.continue();
  });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate });
  return { context, page };
}

/**
 * Wait for the page to settle after `from`: its first change (up to `first` ms; a slow CPU takes a while to answer a
 * tap at all), then no change for `quiet` ms, or `cap` ms in all. When it last changed, and whether it changed.
 */
async function settle(page, from, quiet, cap, first = 0) {
  for (;;) {
    const { now, last } = await page.evaluate(() => ({
      now: performance.now(),
      last: window.__speed.last,
    }));
    const moved = last > from;
    if (!moved && now - from < first) {
      await page.waitForTimeout(50);
      continue;
    }
    const changed = Math.max(last, from);
    if (now - changed >= quiet)
      return { at: changed, moved, result: "settled" };
    if (now - from >= cap) return { at: now, moved: true, result: "timeout" };
    await page.waitForTimeout(50);
  }
}

/**
 * Load a screen. Its time is LCP, when the main content was painted (the first baseline showed "settled" too noisy
 * to rank screens: timers keep some pages changing); settled (300 ms quiet) and blocking time are kept beside it.
 */
async function load(page, path) {
  await page.goto(origin + path, { waitUntil: "load", timeout: 90000 });
  const done = await settle(page, 0, 300, 15000);
  // Ready: the page settled and the main thread has been free for 500 ms (hydration runs as long tasks while the
  // page looks done; a tap before then is lost, or on a link reloads the page).
  for (;;) {
    const { now, busy } = await page.evaluate(() => ({
      now: performance.now(),
      busy: window.__speed.busy,
    }));
    if (now - busy >= 500 || now >= 15000) break;
    await page.waitForTimeout(100);
  }
  await settle(page, 0, 150, 15000);
  const vitals = await page.evaluate(() => ({
    lcp: window.__speed.lcp,
    tbt: Math.round(window.__speed.tbt),
    busy: window.__speed.busy,
    last: window.__speed.last,
    loaded: performance.getEntriesByType("navigation")[0]?.loadEventEnd ?? 0,
  }));
  const settled = Math.round(Math.max(done.at, vitals.loaded));
  // The app's own CPU test (telemetry.ts measureCpu, kept as sx-cpu), run once the page is idle: what a phone this
  // slow measures, to set the device tiers from (27 Oct 2026). Null when the page never ran it.
  let cpu = null;
  for (let wait = 0; wait < 30 && cpu === null; wait++) {
    cpu = await page.evaluate(() => {
      try {
        const kept = JSON.parse(localStorage.getItem("sx-cpu") ?? "null");
        return typeof kept?.ms === "number" ? kept.ms : null;
      } catch {
        return null;
      }
    });
    if (cpu === null) await page.waitForTimeout(100);
  }
  return {
    // A screen's time: when it is ready to use; its LCP and blocking time beside it.
    ms: Math.round(Math.max(settled, vitals.busy, vitals.lcp ?? 0)),
    settled,
    lcp: vitals.lcp,
    tbt: vitals.tbt,
    cpu_ms: cpu,
    result: done.result,
  };
}

/**
 * One tap: from the tap (its own event time) to settled (150 ms quiet after the page first answers, waiting up to
 * 3 s for that answer). Null when the screen has no such control; `control` names the element as the code does.
 */
async function tap(page, selector) {
  const target = page.locator(`${selector}:visible`).first();
  if (!(await target.count())) return null;
  const { before, control } = await target.evaluate((el) => {
    window.__speed.tap = 0;
    const cls = [...el.classList]
      .map((name) => name.replace(/-module__[A-Za-z0-9_-]{5,8}__/, "__"))
      .find((name) => name.includes("__"));
    return {
      before: location.pathname,
      control: `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""}`,
    };
  });
  await target.click({ timeout: 10000 });
  const from = await page.evaluate(() => window.__speed.tap);
  if (!from) return { ms: 0, result: "no_change", control };
  const done = await settle(page, from, 150, 10000, 3000);
  if ((await page.evaluate(() => location.pathname)) !== before)
    return { result: "left", control };
  if (!done.moved) return { ms: 0, result: "no_change", control };
  return { ms: Math.round(done.at - from), result: done.result, control };
}

async function main() {
  const [output, requestPath = ".wb-ci/request.json"] = process.argv.slice(2);
  await mkdir(output, { recursive: true });
  let request = {};
  try {
    request = JSON.parse(await readFile(requestPath, "utf8"));
  } catch {}
  const screens = pickSpeedScreens(request.routes ?? []);
  const started = Date.now();
  const measures = [];
  const failures = [];
  const { stop } = await server();
  const deadline = setTimeout(
    () => {
      stop();
      process.exit(1);
    },
    40 * 60 * 1000,
  );
  let browser;
  try {
    browser = await chromium.launch();
    // Warm the server's render of each screen twice, untimed (the first baseline's 1x runs came out slower than 4x).
    for (const [, screen] of [...screens, ...screens]) {
      const warm = await open(browser, 1);
      await warm.page
        .goto(origin + screen.path, { waitUntil: "load", timeout: 90000 })
        .catch(() => undefined);
      await warm.context.close();
    }
    for (let run = 0; run < RUNS; run++)
      for (const rate of RATES)
        for (const [key, screen] of screens) {
          let session = await open(browser, rate);
          try {
            measures.push({
              screen: key,
              action: "load",
              rate,
              run,
              ...(await load(session.page, screen.path)),
            });
            // Each tap on a page just loaded, so one tap's change never slows the next.
            let fresh = true;
            for (const [action, selector] of Object.entries({
              ...ACTIONS,
              ...(screen.actions ?? {}),
            })) {
              if (!fresh) {
                await session.context.close();
                session = await open(browser, rate);
                await load(session.page, screen.path);
              }
              const timed = await tap(session.page, selector);
              fresh = !timed || timed.result === "no_change";
              if (!timed) continue;
              // A tap that left the page is kept (as "left", no time): on a ready page it is a link doing a
              // full load instead of opening in place.
              measures.push({ screen: key, action, rate, run, ...timed });
            }
          } catch (error) {
            const message = String(error?.message ?? error)
              .split("\n")[0]
              .slice(0, 160);
            failures.push(`${key} at ${rate}x, run ${run + 1}: ${message}`);
            measures.push({
              screen: key,
              action: "load",
              rate,
              run,
              result: "failed",
            });
          } finally {
            await session.context.close().catch(() => undefined);
          }
        }
  } finally {
    clearTimeout(deadline);
    await browser?.close();
    stop();
  }
  const rows = summarize(measures);
  const findings = classify(rows);
  const run = {
    schema: "wb-speed/1",
    source_sha: request.source_sha ?? null,
    elapsed_seconds: Math.round((Date.now() - started) / 1000),
    rates: RATES,
    runs: RUNS,
    cpu: cpuByRate(measures),
    rows,
    findings,
    failures,
    measures,
  };
  const text = speedMarkdown(run);
  await writeFile(resolve(output, "report.md"), text);
  await writeFile(resolve(output, "speed.json"), JSON.stringify(run, null, 1));
  if (process.env.GITHUB_STEP_SUMMARY)
    await writeFile(process.env.GITHUB_STEP_SUMMARY, text, { flag: "a" });
  console.log(text);
  // Slow screens are the report, not a failure; the job fails only when the check could not run (a quarter of
  // the screens never loaded at any rate).
  const loaded = new Set(
    measures
      .filter((m) => m.action === "load" && m.result !== "failed")
      .map((m) => m.screen),
  );
  process.exit(loaded.size < screens.length * 0.75 ? 1 : 0);
}

await main();
