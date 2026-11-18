// The dark contrast check (owner, 17 Nov 2026: "Dark mode: some items can't be seen at all, colour
// combinations"; named again in his 18 Nov recall order). The main screens and sheets from the review fixtures
// (fictional data, no API origin, no credentials) in the app's dark theme at 363 and 1280 px. It fails when a run
// of text is below WCAG AA (4.5:1, or 3:1 for large text) or an icon is below 3:1 (wb_contrast_lib.mjs). wb-ci's
// visual job runs it after the overlap check.
//
//   node scripts/ci/wb_contrast.mjs <output-dir> [--origin http://127.0.0.1:3026] [--only <key prefix>]
//        [--theme light|dark] [--shots]
//
// Without --origin it starts the fixture server itself (as wb_matrix.mjs does). The output: report.md (also the
// step summary), contrast.json and one JPEG per state with a finding (every state with --shots).
import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { HEIGHT, WIDTHS, inPage, summarise } from "./wb_contrast_lib.mjs";

const FIRST_LEAD = "00000000-0000-4000-8000-000000000300";

/**
 * The screens checked. `open` names a control to press first (a sheet or menu), by its accessible name.
 * Ask Dipak is left out while its own redesign runs (its worker checks its dark look).
 */
export const PAGES = [
  { key: "home", path: "/review-fixture/home", ready: "main" },
  { key: "leads-list", path: "/review-fixture/leads", ready: "[data-lead-row]" },
  { key: "leads-open", path: "/review-fixture/leads?tab=all&stage=open", ready: "[data-lead-row]" },
  { key: "lead-page", path: `/review-fixture/leads#lead=${FIRST_LEAD}`, ready: "[data-lead-page]" },
  { key: "chats", path: "/review-fixture/chats", ready: "main" },
  { key: "reports", path: "/review-fixture/reports", ready: "main" },
  { key: "report", path: "/review-fixture/report", ready: "[data-synthetic-report]" },
  { key: "growth", path: "/review-fixture/growth", ready: "main" },
  { key: "insights", path: "/review-fixture/insights", ready: "main" },
  { key: "settings", path: "/review-fixture/settings", ready: "main" },
  { key: "notifications", path: "/review-fixture/notifications", ready: "main" },
  { key: "alerts", path: "/review-fixture/alerts", ready: "main" },
  { key: "upload", path: "/review-fixture/upload", ready: "main" },
  { key: "shell", path: "/review-fixture/shell", ready: "[data-full-shell-fixture]" },
  { key: "sign-in", path: "/review-fixture/sign-in", ready: "main" },
];

function argument(name) {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
}

async function main() {
  const output = resolve(process.argv[2] ?? "wb-contrast");
  await mkdir(output, { recursive: true });
  const given = argument("--origin");
  const theme = argument("--theme") ?? "dark";
  const shots = process.argv.includes("--shots");
  let stop = () => undefined;
  let origin = given;
  if (!origin) {
    const matrix = await import("./wb_matrix.mjs");
    origin = matrix.origin;
    ({ stop } = await matrix.fixtureServer());
  }
  const only = argument("--only");
  const pages = only ? PAGES.filter((page) => only.split(",").some((o) => page.key.startsWith(o))) : PAGES;
  const rows = [];
  let browser;
  try {
    browser = await chromium.launch();
    const warm = await browser.newPage();
    for (const page of pages)
      await warm
        .goto(origin + page.path, { waitUntil: "load", timeout: 180000 })
        .then(() => warm.locator(page.ready).first().waitFor({ timeout: 120000 }))
        .catch(() => undefined);
    await warm.close();
    for (const page of pages)
      for (const width of WIDTHS) {
        const row = { page: page.key, state: `${width} ${theme}`, failures: [], total: 0, runs: 0 };
        // A route that takes the browser down must not take the rest of the check with it.
        if (!browser.isConnected()) browser = await chromium.launch();
        const context = await browser.newContext({
          viewport: { width, height: HEIGHT },
          isMobile: width < 600,
          hasTouch: width < 600,
          locale: "en-GB",
          reducedMotion: "reduce",
          serviceWorkers: "block",
          acceptDownloads: false,
        });
        try {
          // The app goes dark only through its own theme key, as a person picks it in Settings.
          await context.addInitScript((value) => {
            try {
              window.localStorage.setItem("sales-xray:theme", value);
            } catch {
              /* storage blocked: the page stays on its default */
            }
          }, theme);
          await context.route("**/*", (route) => {
            const request = route.request();
            const url = new URL(request.url());
            if (url.origin !== origin || request.method() !== "GET") return route.abort();
            return route.continue();
          });
          const tab = await context.newPage();
          await tab.clock.setFixedTime(new Date("2026-10-03T12:00:00Z"));
          await tab.goto(origin + page.path, { waitUntil: "load", timeout: 90000 });
          await tab.locator(page.ready).first().waitFor({ timeout: 20000 });
          await tab.addStyleTag({
            content: "*,*::before,*::after{animation:none!important;transition:none!important}",
          });
          await tab.evaluate(() => document.fonts.ready);
          await tab.waitForTimeout(400);
          row.theme = await tab.evaluate(() => document.documentElement.dataset.theme ?? "");
          const found = await tab.evaluate(inPage(page.root ?? "body"));
          Object.assign(row, found);
          if (shots || found.total)
            await tab.screenshot({
              path: resolve(output, `${page.key}-${width}-${theme}.jpg`),
              type: "jpeg",
              quality: 60,
            });
          if (!found.runs) row.error = "no text found";
          else if (row.theme !== theme) row.error = `page theme is "${row.theme}", not ${theme}`;
        } catch (error) {
          row.error = String(error?.message ?? error).split("\n")[0].slice(0, 160);
        } finally {
          await context.close().catch(() => undefined);
        }
        rows.push(row);
        process.stdout.write(
          `${row.page} @ ${row.state}: ${row.error ? `error ${row.error}` : `${row.total} below AA (${row.runs} runs, ${row.pictures} over pictures)`}\n`,
        );
      }
  } finally {
    await browser?.close();
    stop();
  }
  const lines = summarise(rows);
  const report = [
    `## ${theme === "dark" ? "Dark" : "Light"} contrast check`,
    "",
    `${pages.length} screens x ${WIDTHS.join(" and ")} px, ${theme}. WCAG AA: text 4.5:1 (large 3:1), icons 3:1.`,
    "",
    ...(lines.length ? lines.map((line) => `- ${line}`) : ["Every screen is clean: all text and icons meet AA."]),
    "",
  ].join("\n");
  await writeFile(resolve(output, "contrast.json"), JSON.stringify(rows, null, 2));
  await writeFile(resolve(output, "report.md"), report);
  if (process.env.GITHUB_STEP_SUMMARY) await appendFile(process.env.GITHUB_STEP_SUMMARY, report);
  console.log(report);
  process.exit(lines.length ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) await main();
