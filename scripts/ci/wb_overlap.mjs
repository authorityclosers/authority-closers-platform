// The phone overlap check (owner, 17 Nov 2026: "How did this get through? Testing didn't notice it"): the lead page
// and the Leads list from the review fixtures (fictional data, no API origin, no credentials), at 360, 363 and
// 412 px, normal and large (1.3x) text, light and dark. It fails when visible text runs into other text or is cut
// off with no ellipsis (wb_overlap_lib.mjs). wb-ci's visual job runs it after the screenshots.
//
//   node scripts/ci/wb_overlap.mjs <output-dir> [--origin http://127.0.0.1:3026]
//
// Without --origin it starts the fixture server itself (as wb_matrix.mjs does). The output: report.md (also the
// step summary), overlap.json and one JPEG per state with a finding.
import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { textZoom } from "./wb_matrix_lib.mjs";
import {
  HEIGHT,
  inPage,
  overlapStates,
  summarise,
  tagOfState,
} from "./wb_overlap_lib.mjs";

const FIRST_LEAD = "00000000-0000-4000-8000-000000000300";

/** The screens checked: the lead page on a long stage path and on the fixture's own, and the Leads list. */
export const PAGES = [
  {
    key: "lead-page-long-path",
    path: `/review-fixture/leads?path=long#lead=${FIRST_LEAD}`,
    ready: "[data-lead-page]",
    root: "[data-lead-page]",
  },
  {
    key: "lead-page",
    path: `/review-fixture/leads#lead=${FIRST_LEAD}`,
    ready: "[data-lead-page]",
    root: "[data-lead-page]",
  },
  { key: "leads-list", path: "/review-fixture/leads", ready: "[data-lead-row]", root: "body" },
  {
    key: "leads-list-open",
    path: "/review-fixture/leads?tab=all&stage=open",
    ready: "[data-lead-row]",
    root: "body",
  },
];

function argument(name) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

async function main() {
  const output = resolve(process.argv[2] ?? "wb-overlap");
  await mkdir(output, { recursive: true });
  const given = argument("--origin");
  let stop = () => undefined;
  let origin = given;
  if (!origin) {
    const matrix = await import("./wb_matrix.mjs");
    origin = matrix.origin;
    ({ stop } = await matrix.fixtureServer());
  }
  const only = argument("--only");
  const pages = only ? PAGES.filter((page) => page.key.startsWith(only)) : PAGES;
  const rows = [];
  let browser;
  try {
    browser = await chromium.launch();
    // Compile each route once, so the first state isn't the compile.
    const warm = await browser.newPage();
    for (const page of pages)
      await warm
        .goto(origin + page.path, { waitUntil: "load", timeout: 180000 })
        .then(() => warm.locator(page.ready).first().waitFor({ timeout: 120000 }))
        .catch(() => undefined);
    await warm.close();
    for (const page of pages)
      for (const state of overlapStates()) {
        const row = { page: page.key, state: tagOfState(state), overlaps: [], clipped: [], runs: 0 };
        const context = await browser.newContext({
          viewport: { width: state.width, height: HEIGHT },
          colorScheme: state.theme,
          isMobile: true,
          hasTouch: true,
          locale: "en-GB",
          reducedMotion: "reduce",
          serviceWorkers: "block",
          acceptDownloads: false,
        });
        try {
          // The app's own theme choice, as a person would pick it in Settings.
          await context.addInitScript((theme) => {
            try {
              window.localStorage.setItem("sales-xray:theme", theme);
            } catch {
              /* storage blocked: the page stays on its default */
            }
          }, state.theme);
          // Same-origin reads only; nothing leaves the runner.
          await context.route("**/*", (route) => {
            const request = route.request();
            const url = new URL(request.url());
            if (url.origin !== origin || request.method() !== "GET") return route.abort();
            return route.continue();
          });
          const tab = await context.newPage();
          await tab.clock.setFixedTime(new Date("2026-10-03T12:00:00Z"));
          // The lead desk keeps reading (pollers), so the page never goes network-idle: wait for its own mark.
          await tab.goto(origin + page.path, { waitUntil: "load", timeout: 90000 });
          await tab.locator(page.ready).first().waitFor({ timeout: 15000 });
          await tab.addStyleTag({
            content: "*,*::before,*::after{animation:none!important;transition:none!important}",
          });
          await tab.evaluate(() => document.fonts.ready);
          await tab.waitForTimeout(300);
          if (state.scale !== 1) await tab.evaluate(textZoom, state.scale);
          await tab.waitForTimeout(200);
          const found = await tab.evaluate(inPage(page.root));
          Object.assign(row, found);
          if (found.overlaps.length || found.clipped.length)
            await tab.screenshot({
              path: resolve(output, `${page.key}-${row.state.replace(/[^a-z0-9]+/gi, "-")}.jpg`),
              type: "jpeg",
              quality: 60,
            });
          if (!found.runs) row.error = "no text found";
        } catch (error) {
          row.error = String(error?.message ?? error).split("\n")[0].slice(0, 160);
        } finally {
          await context.close();
        }
        rows.push(row);
        process.stdout.write(
          `${row.page} @ ${row.state}: ${row.error ? `error ${row.error}` : `${row.overlaps.length} overlapping, ${row.clipped.length} clipped (${row.runs} runs)`}\n`,
        );
      }
  } finally {
    await browser?.close();
    stop();
  }
  const lines = summarise(rows);
  const report = [
    "## Phone overlap check",
    "",
    `${pages.length} screens x ${overlapStates().length} states (360, 363, 412 px; 100% and 130% text; light and dark).`,
    "",
    ...(lines.length ? lines.map((line) => `- ${line}`) : ["Every state is clean: no text runs into other text, none is cut off."]),
    "",
  ].join("\n");
  await writeFile(resolve(output, "overlap.json"), JSON.stringify(rows, null, 2));
  await writeFile(resolve(output, "report.md"), report);
  if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, report);
  console.log(report);
  process.exit(lines.length ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) await main();
