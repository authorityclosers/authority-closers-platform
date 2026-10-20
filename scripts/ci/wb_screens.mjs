// Workbench screenshots on GitHub-hosted runners (wb-ci, 20 Oct 2026). Reuses the Sales Xray visual advisory helpers:
// the same fictional fixture server (next dev, AC_SALES_XRAY_REVIEW=1, no API origin, no credentials), the same
// request filter, frozen time and capture/measure code. Adds explicit routes, both colour schemes and two pages at once.
//
//   node scripts/ci/wb_screens.mjs <output-dir> [.wb-ci/request.json]
//
// request.routes: explicit routes, each captured as its own frame (it must render without the API: /review-fixture/*
// routes and ?sx-fixture= states do). Otherwise a changed-files request captures the frames the visual advisory selects
// for those paths, and a full request captures every frame. Report-tab frames are left out: they click a "Tabbed view"
// control the review fixture no longer has (they failed in every run on 20 Oct).
import { createRequire } from "node:module";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { chromium } from "playwright";
import {
  capture,
  frames,
  routeFixtureRequest,
  selectFrames,
  unavailable,
  viewports,
  waitForFixtureServer,
} from "./sales_xray_visual.mjs";

const origin = "http://127.0.0.1:18216";
const schemes = ["light", "dark"];

function slug(route) {
  return (
    route
      .replace(/^\/+/, "")
      .replace(/[^a-zA-Z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "root"
  );
}

export function selectedFrames(request) {
  if (request.routes?.length)
    return request.routes.map((route) => ({
      id: slug(route),
      route,
      ready: "body",
      group: "custom",
    }));
  const picked =
    Array.isArray(request.changed_files) && !request.full
      ? selectFrames(request.changed_files)
      : frames;
  return picked.filter((item) => !item.tab);
}

async function main() {
  const [output, requestPath = ".wb-ci/request.json"] = process.argv.slice(2);
  await mkdir(output, { recursive: true });
  let request = {};
  try {
    request = JSON.parse(await readFile(requestPath, "utf8"));
  } catch {}
  const base = selectedFrames(request);
  const jobs = schemes.flatMap((scheme) =>
    base.flatMap((item) =>
      viewports.map((viewport) => ({
        item: { ...item, id: `${item.id}-${scheme}` },
        scheme,
        viewport,
      })),
    ),
  );
  const rows = new Array(jobs.length);
  const started = Date.now();
  const require = createRequire(import.meta.url);
  const nextRequire = createRequire(
    require.resolve("eslint-config-next", {
      paths: [resolve("apps/sales-xray-web")],
    }),
  );
  const axePath = createRequire(
    nextRequire.resolve("eslint-plugin-jsx-a11y"),
  ).resolve("axe-core");
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
  const deadline = setTimeout(() => {
    stop();
    process.exit(1);
  }, 600000);
  let browser;
  try {
    await waitForFixtureServer(
      `${origin}/review-fixture/shell`,
      () => server.exitCode === null,
    );
    browser = await chromium.launch();
    const routes = new Set(base.map((item) => item.route));
    let next = 0;
    const worker = async () => {
      while (next < jobs.length) {
        const index = next++;
        const { item, scheme, viewport } = jobs[index];
        const context = await browser.newContext({
          viewport,
          deviceScaleFactor: 1,
          locale: "en-GB",
          timezoneId: "UTC",
          colorScheme: scheme,
          reducedMotion: "reduce",
          serviceWorkers: "block",
          acceptDownloads: false,
        });
        try {
          await context.route("**/*", (route) =>
            routeFixtureRequest(route, origin, routes),
          );
          const page = await context.newPage();
          page.setDefaultTimeout(8000);
          rows[index] = {
            ...(await capture(page, item, viewport, output, axePath)),
            scheme,
          };
        } catch {
          rows[index] = { ...unavailable(item, viewport), scheme };
        } finally {
          await context.close();
        }
      }
    };
    await Promise.all([worker(), worker()]);
  } finally {
    clearTimeout(deadline);
    await browser?.close();
    stop();
  }
  const done = rows.filter(Boolean);
  const measured = done.filter((row) => row.capture_status === "measured");
  await writeFile(
    resolve(output, "receipt.json"),
    JSON.stringify(
      {
        schema: "wb-ci-screens/1",
        source_sha: request.source_sha ?? null,
        elapsed_seconds: Math.round((Date.now() - started) / 1000),
        captured: measured.length,
        total: jobs.length,
        rows: done,
      },
      null,
      2,
    ),
  );
  const table = [
    "### Screenshots",
    "",
    `${measured.length} of ${jobs.length} captured (light and dark, ${viewports.map((v) => v.width).join(" and ")} px).`,
    "",
    "| frame | scheme | width | result | overflow px | console errors | axe critical |",
    "|---|---|---|---|---|---|---|",
    ...done.map(
      (row) =>
        `| ${row.id.replace(/-(light|dark)-\d+x\d+$/, "")} | ${row.scheme} | ${row.viewport.width} | ${row.capture_status === "measured" ? "ok" : row.failure_stage} | ${row.overflow_px ?? "-"} | ${row.console_error_count ?? "-"} | ${row.axe_critical_count ?? "-"} |`,
    ),
  ].join("\n");
  if (process.env.GITHUB_STEP_SUMMARY)
    await writeFile(process.env.GITHUB_STEP_SUMMARY, `${table}\n`, {
      flag: "a",
    });
  console.log(table);
  process.exit(measured.length === jobs.length ? 0 : 1);
}

await main();
