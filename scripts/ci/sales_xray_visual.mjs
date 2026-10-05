import { createRequire } from "node:module";
import { readFile, writeFile, mkdir, rename, access } from "node:fs/promises";
import { spawn } from "node:child_process";
import { createConnection } from "node:net";
import { get as httpGet } from "node:http";
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
  const params = new URLSearchParams(url.search);
  params.delete("_rsc");
  const query = params.toString();
  const normalized = url.pathname + (query ? `?${query}` : "");
  const shellNavigation =
    routes.has(shell) &&
    url.pathname === shell &&
    [...params.keys()].every(
      (key) =>
        ["call", "view", "section"].includes(key) &&
        params.getAll(key).length === 1,
    ) &&
    (!params.has("call") ||
      params.get("call") === "00000000-0000-4000-8000-000000000002") &&
    (!params.has("view") ||
      ["reading", "tabs", "document"].includes(params.get("view"))) &&
    (!params.has("section") ||
      ["overview", "moments", "transcript", "analysis", "coaching"].includes(
        params.get("section"),
      ));
  return (
    url.origin === origin &&
    request.method() === "GET" &&
    (url.pathname.startsWith("/_next/static/") ||
      routes.has(normalized) ||
      shellNavigation ||
      /^\/(brand|brands|fonts|lightbox|experience-kit|media)\//.test(
        url.pathname,
      ) ||
      url.pathname === "/favicon.ico")
  );
}

export async function routeFixtureRequest(route, origin, routes) {
  const request = route.request();
  const url = new URL(request.url());
  // Existing acquisition fixtures require the read-only review capability.
  // Supply only that fixed fictional flag; no health/API request reaches Next.
  if (
    url.origin === origin &&
    url.pathname === "/health" &&
    !url.search &&
    request.method() === "GET"
  ) {
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"analysis_read_only":true}',
    });
  }
  if (!allowedRequest(request, origin, routes)) return route.abort();
  if (route.request().resourceType() !== "document") return route.continue();
  // Native HMR is required for Turbopack hydration. CSP blocks external sockets,
  // frames and workers without replacing the browser WebSocket constructor.
  const local = new URL(origin);
  const response = await route.fetch({ maxRedirects: 0, timeout: 35000 });
  await route.fulfill({
    response,
    headers: {
      ...response.headers(),
      "content-security-policy": `connect-src ${origin} ws://${local.host}/_next/hmr; worker-src 'none'; frame-src 'none'`,
    },
  });
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

export async function waitForFixtureServer(url, alive = () => true) {
  const parsed = new URL(url);
  if (
    parsed.protocol !== "http:" ||
    parsed.hostname !== "127.0.0.1" ||
    parsed.pathname !== "/review-fixture/shell"
  )
    throw new Error();
  const readyDeadline = Date.now() + 15000;
  while (true) {
    try {
      await new Promise((done, reject) => {
        const request = httpGet(parsed, { timeout: 60000 }, (response) => {
          response.on("error", () => {});
          response.resume();
          if (response.statusCode === 200) done();
          else reject(new Error());
        });
        request.once("error", reject);
        request.once("timeout", () => request.destroy(new Error()));
      });
      return;
    } catch (error) {
      if (
        error?.code !== "ECONNREFUSED" ||
        Date.now() >= readyDeadline ||
        !alive()
      )
        throw error;
      await new Promise((done) => setTimeout(done, 250));
    }
  }
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
    if (item.tab) {
      row.failure_stage = "section_selection";
      await page
        .getByRole("button", { name: "Tabbed view", exact: true })
        .click({ timeout: 5000 });
      await page
        .getByRole("tab", { name: item.tab, exact: true })
        .click({ timeout: 5000 });
    }
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
    setup_stage: "dependencies",
    started_at: new Date().toISOString(),
  };
  const started = Date.now();
  // Persist unavailable rows before launching: dependency/server/deadline failures
  // still yield a truthful advisory receipt.
  let saving = Promise.resolve();
  const save = () => {
    const data = JSON.stringify(receipt, null, 2);
    saving = saving.then(async () => {
      await writeFile(resolve(output, "receipt.pending"), data);
      await rename(
        resolve(output, "receipt.pending"),
        resolve(output, "receipt.json"),
      );
    });
    return saving;
  };
  await save();
  let server;
  let browser;
  const deadline = setTimeout(() => process.emit("SIGTERM"), 270000);
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
    receipt.renderer_status = "partial";
    receipt.elapsed_seconds = Math.round((Date.now() - started) / 1000);
    await save();
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
    receipt.setup_stage = "env_file_check";
    for (const name of [
      ".env",
      ".env.local",
      ".env.development",
      ".env.development.local",
    ]) {
      try {
        await access(resolve("apps/sales-xray-web", name));
        throw new Error("env_file_present");
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
    }
    receipt.setup_stage = "port_check";
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
    if (occupied) {
      receipt.setup_stage = "port_occupied";
      throw new Error();
    }
    // No credentials inherited by the app process, and no configured API origin.
    const env = Object.fromEntries(
      ["PATH", "HOME", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH"]
        .filter((key) => process.env[key])
        .map((key) => [key, process.env[key]]),
    );
    receipt.setup_stage = "server_start";
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
    // Compile the common shell once before timed browser captures. No API is
    // configured and this is the same fictional route used in every selection.
    receipt.setup_stage = "server_warmup";
    await waitForFixtureServer(
      "http://127.0.0.1:18216/review-fixture/shell",
      () => server.exitCode === null,
    );
    receipt.setup_stage = "browser_launch";
    browser = await chromium.launch();
    receipt.browser_version = browser.version();
    receipt.setup_stage = "capturing";
    const routes = new Set(selected.map((item) => item.route));
    // Parallel captures stay on the hosted Actions runner. Local use remains
    // one context at a time because this VPS also serves production.
    const concurrency = process.env.GITHUB_ACTIONS === "true" ? 2 : 1;
    receipt.capture_concurrency = concurrency;
    for (
      let startIndex = 0;
      startIndex < rows.length;
      startIndex += concurrency
    ) {
      await Promise.all(
        Array.from(
          { length: Math.min(concurrency, rows.length - startIndex) },
          (_, offset) => startIndex + offset,
        ).map(async (index) => {
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
          try {
            await context.route("**/*", (route) =>
              routeFixtureRequest(route, "http://127.0.0.1:18216", routes),
            );
            const page = await context.newPage();
            page.setDefaultTimeout(8000);
            rows[index] = await capture(page, item, viewport, output, axePath);
          } finally {
            await context.close();
          }
        }),
      );
      receipt.elapsed_seconds = Math.round((Date.now() - started) / 1000);
      await save();
    }
    receipt.renderer_status = rows.every(
      (row) => row.capture_status === "measured",
    )
      ? "measured"
      : "partial";
  } catch (error) {
    receipt.setup_failure_class = [
      "Error",
      "TypeError",
      "TimeoutError",
      "AbortError",
    ].includes(error?.name)
      ? error.name
      : "unavailable";
    receipt.setup_failure_code = [
      "ECONNREFUSED",
      "ECONNRESET",
      "UND_ERR_SOCKET",
      "ETIMEDOUT",
    ].includes(error?.cause?.code)
      ? error.cause.code
      : null;
    receipt.renderer_status = "unavailable";
  } finally {
    receipt.elapsed_seconds = Math.round((Date.now() - started) / 1000);
    clearTimeout(deadline);
    await browser?.close();
    await stop();
    await save();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href)
  await main();
