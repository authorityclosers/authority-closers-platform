// The Readability Gate (owner, 18 Nov 2026: "How come there are bugs that are just visible?", then "Yes, start
// stage 1"). The top 20 screens from the review fixtures (fictional data, no API origin, no credentials), each at
// the four corner states (360 px dark with 130% text, 360 px light, 1280 px light and dark), once as the fixture is
// and once with long real-shaped data. One pass runs the bug radar's scan, the phone overlap scan, the contrast
// scan, axe-core and the gate's own checks (wb_readability_lib.mjs), with no model anywhere.
//
// It fails only on what is NEW against scripts/ci/wb-readability-baseline.json (today's findings), so it starts
// green and stops regressions. A load with something new is measured three times and only what every pass saw
// counts, so one slow paint cannot fail a run.
//
//   node scripts/ci/wb_readability.mjs <output-dir> [--origin http://127.0.0.1:3026] [--only <key,key>]
//        [--baseline <file>] [--write-baseline [--prune]] [--workers 3] [--shots]
//
// Without --origin it starts the fixture server itself (as wb_matrix.mjs does). --write-baseline folds this run
// into the baseline (with --prune: replaces the cells this run measured). The output: report.md (also the step
// summary), readability.json, and one JPEG per load with something new.
import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { inPage as contrastInPage } from "./wb_contrast_lib.mjs";
import { textZoom } from "./wb_matrix_lib.mjs";
import { inPage as overlapInPage } from "./wb_overlap_lib.mjs";
import { helperScript, radarScan } from "./wb_radar_lib.mjs";
import {
  SCREENS,
  cellOf,
  compare,
  extraInPage,
  loads,
  nameOf,
  namesOf,
  reportMarkdown,
  stressDomInPage,
  stressScript,
  union,
} from "./wb_readability_lib.mjs";

export const BASELINE = "scripts/ci/wb-readability-baseline.json";
// A new finding must show in every one of this many measurements of its load to count.
const PASSES = 3;
// The fixtures run on the development server with the clock fixed: a hydration mismatch there is the server's
// "now" against the fixed one, not something a person sees.
const DEV_NOISE =
  /\/_next\/webpack-hmr|__nextjs|\.hot-update\.|\/favicon\.ico|\[HMR\]|\[Fast Refresh\]|Download the React DevTools|[Hh]ydrat/;
// axe's rules the gate keeps: what a person sees or taps. Its tap-size rule is off by default.
const AXE_RULES = ["color-contrast", "target-size", "meta-viewport", "scrollable-region-focusable"];

function argument(name) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

function axeSource() {
  const require = createRequire(import.meta.url);
  const nextRequire = createRequire(
    require.resolve("eslint-config-next", { paths: [resolve("apps/sales-xray-web")] }),
  );
  return createRequire(nextRequire.resolve("eslint-plugin-jsx-a11y")).resolve("axe-core");
}

/** One load, measured once: every scan's findings as {check, selector, detail}. */
async function measure(browser, origin, load, axePath, local) {
  const { screen, corner, variant } = load;
  const context = await browser.newContext({
    viewport: { width: corner.width, height: corner.height },
    colorScheme: corner.theme,
    isMobile: corner.phone,
    hasTouch: corner.phone,
    locale: "en-GB",
    reducedMotion: "reduce",
    serviceWorkers: "block",
    acceptDownloads: false,
  });
  try {
    // The app goes dark only through its own theme key, as a person picks it in Settings.
    await context.addInitScript((theme) => {
      try {
        window.localStorage.setItem("sales-xray:theme", theme);
      } catch {
        /* storage blocked: the page stays on its default */
      }
    }, corner.theme);
    await context.addInitScript({ content: helperScript() });
    if (variant === "long") await context.addInitScript({ content: stressScript() });
    // Same-origin reads only; nothing leaves the runner. Fixtures have no API: a read the page does not answer
    // itself gets the 404 the dev server would give, at once.
    await context.route("**/*", (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== origin || request.method() !== "GET") return route.abort();
      if (url.pathname.startsWith("/v1/"))
        return route.fulfill({ status: 404, contentType: "application/json", body: '{"detail":"Not Found"}' });
      return local ? local(route) : route.continue();
    });
    const tab = await context.newPage();
    const errors = [];
    tab.on("pageerror", (error) => {
      const text = String(error.message).split("\n")[0];
      if (!DEV_NOISE.test(text)) errors.push(text.replace(/\d+/g, "N").slice(0, 80));
    });
    await tab.clock.setFixedTime(new Date("2026-10-03T12:00:00Z"));
    await tab.goto(origin + screen.path, { waitUntil: "load", timeout: 90000 });
    await tab.locator((!corner.phone && screen.readyWide) || screen.ready).first().waitFor({ timeout: 20000 });
    if (!corner.phone && screen.readyWide) await tab.waitForTimeout(1500);
    await tab.addStyleTag({
      content: "*,*::before,*::after{animation:none!important;transition:none!important}",
    });
    await tab.evaluate(() => document.fonts.ready);
    await tab.waitForTimeout(500);
    if (variant === "long") {
      // Screens whose fixture keeps its data in the page: the names, amounts and percentages grow where they stand.
      await tab.evaluate(stressDomInPage());
      await tab.waitForTimeout(250);
    }
    if (corner.scale !== 1) {
      await tab.evaluate(textZoom, corner.scale);
      await tab.waitForTimeout(250);
    }
    const findings = [];
    const radar = await tab.evaluate(radarScan, { phone: corner.phone });
    for (const f of radar.findings) findings.push({ check: f.check, selector: f.selector, detail: f.detail });
    const overlap = await tab.evaluate(overlapInPage("body"));
    for (const o of overlap.overlaps) findings.push({ check: "text-overlap", selector: `${o.a} x ${o.b}` });
    for (const c of overlap.clipped) findings.push({ check: "text-cut", selector: c.el, detail: `${c.by} px` });
    const contrast = await tab.evaluate(contrastInPage("body"));
    for (const f of contrast.failures)
      findings.push({ check: "contrast-aa", selector: f.el, detail: `${f.ratio}:1, needs ${f.need}` });
    const extra = await tab.evaluate(extraInPage(corner.scale));
    findings.push(...extra.findings);
    await tab.addScriptTag({ path: axePath });
    const axe = await tab.evaluate(async (rules) => {
      const out = await window.axe.run(document, {
        runOnly: { type: "rule", values: rules },
        resultTypes: ["violations"],
      });
      return out.violations.flatMap((v) =>
        v.nodes.slice(0, 30).map((node) => ({ id: v.id, target: String(node.target?.[0] ?? "") })),
      );
    }, AXE_RULES);
    for (const a of axe) findings.push({ check: `axe:${a.id}`, selector: a.target });
    for (const text of new Set(errors)) findings.push({ check: "page-error", selector: text });
    const stressed = variant === "long" ? await tab.evaluate(() => window.__stressed ?? 0) : null;
    return { findings, stressed, chars: extra.chars, runs: overlap.runs, tab, context };
  } catch (error) {
    await context.close().catch(() => undefined);
    throw error;
  }
}

async function main() {
  const output = resolve(process.argv[2] ?? "wb-readability");
  await mkdir(output, { recursive: true });
  const given = argument("--origin");
  const only = argument("--only");
  const baselinePath = resolve(argument("--baseline") ?? BASELINE);
  const write = process.argv.includes("--write-baseline");
  const prune = process.argv.includes("--prune");
  const shots = process.argv.includes("--shots");
  const workers = Number(argument("--workers") ?? 3);
  let stop = () => undefined;
  let origin = given;
  let local;
  if (!origin) {
    const matrix = await import("./wb_matrix.mjs");
    origin = matrix.origin;
    local = matrix.local;
    ({ stop } = await matrix.fixtureServer());
  }
  const screens = only ? SCREENS.filter((s) => only.split(",").includes(s.key)) : SCREENS;
  let baseline = null;
  try {
    baseline = JSON.parse(await readFile(baselinePath, "utf8")).cells ?? {};
  } catch {
    /* no baseline yet: this run records */
  }
  const axePath = axeSource();
  const jobs = loads(screens);
  const rows = new Array(jobs.length);
  let browser;
  try {
    browser = await chromium.launch();
    // Compile each route once, so the first state is not the compile.
    const warm = await browser.newPage();
    for (const screen of screens)
      await warm
        .goto(origin + screen.path, { waitUntil: "load", timeout: 180000 })
        .then(() => warm.locator(screen.ready).first().waitFor({ timeout: 30000 }))
        .catch(() => undefined);
    await warm.close();
    let next = 0;
    const work = async () => {
      for (let at = next++; at < jobs.length; at = next++) {
        const load = jobs[at];
        const cell = cellOf(load);
        const row = { cell, screen: load.screen.key, variant: load.variant, state: load.corner.key };
        const known = new Set(baseline?.[cell] ?? []);
        try {
          if (!browser.isConnected()) browser = await chromium.launch();
          let session = await measure(browser, origin, load, axePath, local);
          let names = namesOf(session.findings);
          let findings = session.findings;
          const novel = (list) => list.filter((name) => !known.has(name));
          if (!baseline) {
            // Recording: measure twice and keep what either pass saw, so the baseline already knows the findings
            // that come and go with timing.
            await session.context.close();
            session = await measure(browser, origin, load, axePath, local);
            names = [...new Set([...names, ...namesOf(session.findings)])].sort();
            findings = [...findings, ...session.findings];
          }
          for (let pass = 2; pass <= PASSES && baseline && novel(names).length; pass++) {
            // Something new: measure again and keep only what every pass saw of it (a late paint, a notice
            // sliding in or a slow font shows in one pass and not the next).
            await session.context.close();
            session = await measure(browser, origin, load, axePath, local);
            const again = new Set(namesOf(session.findings));
            names = names.filter((name) => known.has(name) || again.has(name));
            findings = session.findings;
          }
          row.names = names;
          row.stressed = session.stressed;
          row.chars = session.chars;
          row.details = Object.fromEntries(
            findings.filter((f) => f.detail).map((f) => [nameOf(f), f.detail]),
          );
          if (!session.runs) row.error = "no text found";
          if (shots || (baseline && novel(names).length))
            await session.tab
              .screenshot({
                path: resolve(output, `${cell.replace(/[^a-z0-9]+/gi, "-")}.jpg`),
                type: "jpeg",
                quality: 55,
                scale: "css",
              })
              .catch(() => undefined);
          await session.context.close().catch(() => undefined);
        } catch (error) {
          row.error = String(error?.message ?? error).split("\n")[0].slice(0, 160);
        }
        rows[at] = row;
        process.stdout.write(
          `${cell}: ${row.error ? `error ${row.error}` : `${row.names.length} findings${row.stressed === null ? "" : `, ${row.stressed} long values`}`}\n`,
        );
      }
    };
    await Promise.all(Array.from({ length: Math.max(1, workers) }, work));
  } finally {
    await browser?.close().catch(() => undefined);
    stop();
  }
  const found = Object.fromEntries(rows.filter((row) => !row.error).map((row) => [row.cell, row.names]));
  const { fresh, gone } = baseline ? compare(found, baseline) : { fresh: [], gone: [] };
  const report = reportMarkdown({
    rows,
    fresh,
    gone,
    recorded: !baseline,
    baselineCells: Object.keys(baseline ?? {}).length,
  });
  await writeFile(resolve(output, "readability.json"), JSON.stringify({ rows, fresh, gone }, null, 1));
  await writeFile(resolve(output, "report.md"), report);
  if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, report);
  console.log(report);
  if (write) {
    const cells = prune ? { ...(baseline ?? {}), ...found } : union(baseline ?? {}, found);
    const sorted = Object.fromEntries(Object.keys(cells).sort().map((cell) => [cell, cells[cell]]));
    await writeFile(
      baselinePath,
      JSON.stringify({ schema: "ac.wb-readability-baseline/1", cells: sorted }, null, 1) + "\n",
    );
    console.log(`baseline written: ${Object.keys(sorted).length} states`);
    process.exit(0);
  }
  // A load that could not be measured fails the gate only once a baseline exists (a recording run reports it).
  process.exit(baseline && (fresh.length || rows.some((row) => row.error)) ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) await main();
