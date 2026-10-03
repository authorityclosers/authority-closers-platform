import { createRequire } from "node:module";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createConnection } from "node:net";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";

export const viewports = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];
const shell = "/review-fixture/shell";
const frame = (id, route, ready, group, tab) => ({
  id,
  route,
  ready,
  group,
  tab,
});
export const frames = [
  frame("shell", shell, "[data-full-shell-fixture]", "shell"),
  ...[
    "Moments",
    "Prospect",
    "Next-call plan",
    "Sales skills",
    "Call signals",
    "Transcript",
    "Raw data",
  ].map((tab) =>
    frame(
      `report-${tab.toLowerCase().replaceAll(" ", "-")}`,
      shell,
      "[data-full-shell-fixture]",
      "report",
      tab,
    ),
  ),
  frame(
    "report-overview",
    "/review-fixture/report",
    "[data-synthetic-report]",
    "report",
  ),
  frame("document", "/review-fixture/document", "main h1", "report"),
  frame("plans", "/review-fixture/plans", "main", "plans"),
  frame("billing", "/review-fixture/plans?view=billing", "main", "plans"),
  ...[
    "auth.email",
    "auth.code",
    "auth.error",
    "upload.selected",
    "processing.report",
    "processing.failed",
  ].map((id) =>
    frame(
      id.replaceAll(".", "-"),
      `/?new=1&sx-fixture=${id}`,
      "[data-fixture]",
      "acquisition",
    ),
  ),
];

// Broad component changes select every existing fictional frame. Route-specific
// changes select their family. The shell always runs, including backend-only PRs.
export function selectFrames(paths, all = false) {
  if (all) return frames;
  const groups = new Set(["shell"]);
  for (const path of paths) {
    if (path.startsWith("packages/typescript/ui/")) return frames;
    if (!path.startsWith("apps/sales-xray-web/")) continue;
    if (/\.(test|spec)\.[cm]?[jt]sx?$/.test(path)) continue;
    if (
      /\/((review-fixture\/)?plans|billing|account\/billing)(\/|\.)/.test(path)
    )
      groups.add("plans");
    else if (
      /report|transcript|prospect|coaching|dipak|call-(map|signals)|key-facts|overview|next-call|sales-skills/.test(
        path,
      )
    )
      groups.add("report");
    else if (
      /auth|login|profile|upload|processing|new-analysis|analysis\/new/.test(
        path,
      )
    )
      groups.add("acquisition");
    else return frames;
  }
  return frames.filter((item) => groups.has(item.group));
}

export function allowedRequest(request, origin, routes) {
  const url = new URL(request.url());
  return (
    url.origin === origin &&
    request.method() === "GET" &&
    (url.pathname.startsWith("/_next/static/") ||
      routes.has(url.pathname + url.search) ||
      /^\/(brand|brands|fonts|lightbox|experience-kit|media)\//.test(
        url.pathname,
      ) ||
      url.pathname === "/favicon.ico")
  );
}

export function unavailable(item, viewport) {
  return {
    id: `${item.id}-${viewport.width}x${viewport.height}`,
    route: item.route,
    state: item.tab ?? item.id,
    viewport,
    screenshot: null,
    capture_status: "unavailable",
    overflow_count: null,
    overflow_px: null,
    console_error_count: null,
    uncaught_exception_count: null,
    axe_critical_count: null,
    axe_incomplete_count: null,
    failure_stage: "not_started",
  };
}

export async function capture(
  page,
  item,
  viewport,
  output,
  axePath,
  origin = "http://127.0.0.1:18216",
) {
  const row = unavailable(item, viewport);
  let consoleErrors = 0;
  let uncaught = 0;
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors++;
  });
  page.on("pageerror", () => {
    uncaught++;
  });
  try {
    row.failure_stage = "navigation";
    await page.clock.setFixedTime(new Date("2026-10-03T12:00:00Z"));
    if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin)) return row;
    const response = await page.goto(`${origin}${item.route}`, {
      waitUntil: "networkidle",
      timeout: 35000,
    });
    if (!response?.ok()) {
      row.failure_stage = `http_${response?.status() ?? "unavailable"}`;
      return row;
    }
    row.failure_stage = "fixture_ready";
    await page.locator(item.ready).first().waitFor({ timeout: 8000 });
    await page.addStyleTag({
      content:
        "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}",
    });
    if (item.tab)
      await page
        .getByRole("tab", { name: item.tab, exact: true })
        .click({ timeout: 5000 });
    row.failure_stage = "fonts_and_images";
    await page.evaluate(async () => {
      await Promise.race([
        Promise.all([
          document.fonts.ready,
          ...[...document.images].map((image) =>
            image.decode().catch(() => {}),
          ),
        ]),
        new Promise((_, reject) => setTimeout(() => reject(new Error()), 8000)),
      ]);
    });
    const overflow = await page.evaluate(() => {
      const width = document.documentElement.clientWidth;
      const visible = [...document.querySelectorAll("body *")].filter(
        (element) => {
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          // Children inside intentionally clipped/scrollable panels do not cause
          // page overflow. document.scrollWidth remains the primary measurement.
          return (
            rect.width > 0 &&
            rect.height > 0 &&
            style.visibility !== "hidden" &&
            (rect.right > width + 1 || rect.left < -1)
          );
        },
      );
      const px = Math.max(
        0,
        document.documentElement.scrollWidth - width,
        document.body.scrollWidth - width,
      );
      return { px, count: px > 1 ? visible.length : 0 };
    });
    row.overflow_count = overflow.count;
    row.overflow_px = overflow.px;
    try {
      await page.addScriptTag({ path: axePath });
      const result = await page.evaluate(async () => {
        const results = await Promise.race([
          window.axe.run(document, {
            resultTypes: ["violations", "incomplete"],
          }),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error()), 8000),
          ),
        ]);
        return {
          critical: results.violations.filter((v) => v.impact === "critical")
            .length,
          incomplete: results.incomplete.length,
        };
      });
      row.axe_critical_count = result.critical;
      row.axe_incomplete_count = result.incomplete;
    } catch {
      /* Failed measurements remain null. Never save axe DOM excerpts. */
    }
    row.failure_stage = "screenshot";
    await page.screenshot({
      path: resolve(output, `${row.id}.png`),
      animations: "disabled",
      caret: "hide",
      timeout: 8000,
    });
    row.screenshot = `${row.id}.png`;
    row.capture_status = "measured";
    row.console_error_count = consoleErrors;
    row.uncaught_exception_count = uncaught;
    row.failure_stage = null;
  } catch {
    /* Save only availability, never exception content or request URLs. */
  }
  return row;
}

async function main() {
  const [output, selectionPath] = process.argv.slice(2);
  await mkdir(output, { recursive: true });
  const selection = JSON.parse(await readFile(selectionPath, "utf8"));
  const selected = selectFrames(selection.paths, selection.all);
  const rows = selected.flatMap((item) =>
    viewports.map((viewport) => unavailable(item, viewport)),
  );
  const receipt = {
    schema: "ac-sales-xray-visual/1",
    advisory: true,
    source_sha: selection.source_sha,
    run_id: selection.run_id,
    rows,
    elapsed_seconds: null,
    renderer_status: "unavailable",
    started_at: new Date().toISOString(),
  };
  const started = Date.now();
  // Persist unavailable rows before launching: dependency/server/deadline failures
  // still yield a truthful advisory receipt.
  const save = () =>
    writeFile(
      resolve(output, "receipt.json"),
      JSON.stringify(receipt, null, 2),
    );
  await save();
  let server;
  let browser;
  const deadline = setTimeout(() => process.emit("SIGTERM"), 240000);
  const stop = async () => {
    if (server?.pid) {
      try {
        process.kill(-server.pid, "SIGTERM");
      } catch {}
      if (server.exitCode === null)
        await new Promise((done) => {
          const timer = setTimeout(() => {
            try {
              process.kill(-server.pid, "SIGKILL");
            } catch {}
            done();
          }, 3000);
          server.once("exit", () => {
            clearTimeout(timer);
            done();
          });
        });
    }
  };
  process.once("SIGTERM", async () => {
    await browser?.close();
    await stop();
    process.exit(0);
  });
  try {
    const require = createRequire(import.meta.url);
    if (require("playwright/package.json").version !== "1.58.2")
      throw new Error();
    const nextRequire = createRequire(
      require.resolve("eslint-config-next", {
        paths: [resolve("apps/sales-xray-web")],
      }),
    );
    const axeRequire = createRequire(
      nextRequire.resolve("eslint-plugin-jsx-a11y"),
    );
    const axePath = axeRequire.resolve("axe-core");
    receipt.axe_version = axeRequire("axe-core/package.json").version;
    receipt.playwright_version = "1.58.2";
    const occupied = await new Promise((done) => {
      const socket = createConnection({ host: "127.0.0.1", port: 18216 });
      socket.once("connect", () => {
        socket.destroy();
        done(true);
      });
      socket.once("error", () => {
        socket.destroy();
        done(false);
      });
      socket.setTimeout(1000, () => {
        socket.destroy();
        done(true);
      });
    });
    if (occupied) throw new Error();
    // No credentials inherited by the app process, and no configured API origin.
    const env = Object.fromEntries(
      ["PATH", "HOME", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH"]
        .filter((key) => process.env[key])
        .map((key) => [key, process.env[key]]),
    );
    server = spawn(
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
          NODE_OPTIONS: "--max-old-space-size=1024",
          UV_THREADPOOL_SIZE: "2",
        },
      },
    );
    // Avoid accepting an unrelated listener on the test port.
    server.on("error", () => {
      void stop();
    });
    await new Promise((resolveReady) => setTimeout(resolveReady, 1500));
    if (server.exitCode !== null) throw new Error();
    browser = await chromium.launch();
    receipt.browser_version = browser.version();
    const routes = new Set(selected.map((item) => item.route));
    for (let index = 0; index < rows.length; index++) {
      const item = selected[Math.floor(index / viewports.length)];
      const viewport = viewports[index % viewports.length];
      const context = await browser.newContext({
        viewport,
        deviceScaleFactor: 1,
        locale: "en-GB",
        timezoneId: "UTC",
        colorScheme: "light",
        reducedMotion: "reduce",
        serviceWorkers: "block",
        acceptDownloads: false,
      });
      await context.route("**/*", (route) =>
        allowedRequest(route.request(), "http://127.0.0.1:18216", routes)
          ? route.continue()
          : route.abort(),
      );
      await context.routeWebSocket(/.*/, (socket) => socket.close());
      const page = await context.newPage();
      page.setDefaultTimeout(8000);
      rows[index] = await capture(page, item, viewport, output, axePath);
      receipt.elapsed_seconds = Math.round((Date.now() - started) / 1000);
      await save();
      await context.close();
    }
    receipt.renderer_status = rows.every(
      (row) => row.capture_status === "measured",
    )
      ? "measured"
      : "partial";
  } catch {
    receipt.renderer_status = "unavailable";
  } finally {
    clearTimeout(deadline);
    await browser?.close();
    await stop();
    await save();
  }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) await main();
