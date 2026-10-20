// Workbench screenshots on GitHub-hosted runners (wb-ci, 20 Oct 2026). Reuses the Sales Xray visual advisory helpers:
// the same fictional fixture server (next dev, AC_SALES_XRAY_REVIEW=1, no API origin, no credentials), the same
// request filter, frozen time and capture/measure code. Adds explicit routes and both colour schemes.
//
//   node scripts/ci/wb_screens.mjs <output-dir> [.wb-ci/request.json]
//
// request.routes: [] = every fictional frame of the visual advisory; otherwise each route is captured as its own
// frame (it must render without the API: /review-fixture/* routes and ?sx-fixture= states do).
import { createRequire } from "node:module";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { chromium } from "playwright";
import {
  capture,
  frames,
  routeFixtureRequest,
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

export function selectedFrames(routes) {
  if (!routes?.length) return frames;
  return routes.map((route) => ({
    id: slug(route),
    route,
    ready: "body",
    group: "custom",
  }));
}

async function main() {
  const [output, requestPath = ".wb-ci/request.json"] = process.argv.slice(2);
  await mkdir(output, { recursive: true });
  let request = {};
  try {
    request = JSON.parse(await readFile(requestPath, "utf8"));
  } catch {}
  const base = selectedFrames(request.routes);
  const items = schemes.flatMap((scheme) =>
    base.map((item) => ({ ...item, id: `${item.id}-${scheme}`, scheme })),
  );
  const rows = [];
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
      env: {
        ...env,
        AC_SALES_XRAY_REVIEW: "1",
        NEXT_TELEMETRY_DISABLED: "1",
      },
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
  }, 900000);
  let browser;
  try {
    await waitForFixtureServer(
      `${origin}/review-fixture/shell`,
      () => server.exitCode === null,
    );
    browser = await chromium.launch();
    const routes = new Set(base.map((item) => item.route));
    for (const item of items) {
      for (const viewport of viewports) {
        const context = await browser.newContext({
          viewport,
          deviceScaleFactor: 1,
          locale: "en-GB",
          timezoneId: "UTC",
          colorScheme: item.scheme,
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
          const row = await capture(page, item, viewport, output, axePath);
          rows.push({ ...row, scheme: item.scheme });
        } catch {
          rows.push({ ...unavailable(item, viewport), scheme: item.scheme });
        } finally {
          await context.close();
        }
      }
    }
  } finally {
    clearTimeout(deadline);
    await browser?.close();
    stop();
  }
  const measured = rows.filter((row) => row.capture_status === "measured");
  const receipt = {
    schema: "wb-ci-screens/1",
    source_sha: request.source_sha ?? null,
    elapsed_seconds: Math.round((Date.now() - started) / 1000),
    captured: measured.length,
    total: rows.length,
    rows,
  };
  await writeFile(
    resolve(output, "receipt.json"),
    JSON.stringify(receipt, null, 2),
  );
  const table = [
    "### Screenshots",
    "",
    `${measured.length} of ${rows.length} captured (light and dark, ${viewports.map((v) => v.width).join(" and ")} px).`,
    "",
    "| frame | scheme | size | result | overflow px | console errors | axe critical |",
    "|---|---|---|---|---|---|---|",
    ...rows.map(
      (row) =>
        `| ${row.id.replace(/-(light|dark)-\d+x\d+$/, "")} | ${row.scheme} | ${row.viewport.width} | ${row.capture_status === "measured" ? "ok" : row.failure_stage} | ${row.overflow_px ?? "-"} | ${row.console_error_count ?? "-"} | ${row.axe_critical_count ?? "-"} |`,
    ),
  ].join("\n");
  if (process.env.GITHUB_STEP_SUMMARY)
    await writeFile(process.env.GITHUB_STEP_SUMMARY, `${table}\n`, {
      flag: "a",
    });
  console.log(table);
  process.exit(measured.length === rows.length ? 0 : 1);
}

await main();
