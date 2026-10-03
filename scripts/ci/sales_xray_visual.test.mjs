import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";
import { chromium } from "playwright";
import {
  allowedRequest,
  routeFixtureRequest,
  capture,
  frames,
  selectFrames,
  unavailable,
  viewports,
  waitForFixtureServer,
} from "./sales_xray_visual.mjs";

test("selects touched families and always includes shell", () => {
  assert.deepEqual(
    selectFrames(["packages/python/ac_platform/http/app.py"]).map((f) => f.id),
    ["shell"],
  );
  assert.deepEqual(
    new Set(
      selectFrames(["apps/sales-xray-web/app/report-modes.tsx"]).map(
        (f) => f.group,
      ),
    ),
    new Set(["shell", "report"]),
  );
  assert.deepEqual(
    new Set(
      selectFrames(["apps/sales-xray-web/app/plans/page.tsx"]).map(
        (f) => f.group,
      ),
    ),
    new Set(["shell", "plans"]),
  );
  assert.equal(
    selectFrames(["apps/sales-xray-web/app/globals.css"]).length,
    frames.length,
  );
  assert.equal(selectFrames([], true).length, frames.length);
  assert.equal(
    selectFrames(["packages/typescript/ui/src/button.tsx"]).length,
    frames.length,
  );
});

test("rejects providers, API writes/reads and off-origin requests", () => {
  const origin = "http://127.0.0.1:18216";
  const routes = new Set(["/review-fixture/shell"]);
  const allowed = (path, method = "GET") =>
    allowedRequest({ url: () => path, method: () => method }, origin, routes);
  assert.ok(allowed(`${origin}/review-fixture/shell`));
  assert.ok(
    allowed(
      `${origin}/review-fixture/shell?call=00000000-0000-4000-8000-000000000002&view=tabs&section=moments&_rsc=local`,
    ),
  );
  for (const section of ["analysis", "coaching"])
    assert.ok(
      allowed(
        `${origin}/review-fixture/shell?call=00000000-0000-4000-8000-000000000002&view=tabs&section=${section}`,
      ),
    );
  assert.ok(!allowed(`${origin}/review-fixture/shell?section=raw-data`));
  assert.ok(
    !allowed(`${origin}/review-fixture/shell?call=other-person&view=tabs`),
  );
  assert.ok(!allowed(`${origin}/review-fixture/shell?unexpected=private`));
  assert.ok(allowed(`${origin}/_next/static/test.js`));
  assert.ok(!allowed(`${origin}/v1/me/workspaces`));
  assert.ok(!allowed(`${origin}/__review/api/frames/a`));
  assert.ok(!allowed(`${origin}/review-fixture/shell`, "POST"));
  assert.ok(
    !allowed("https://salesxray-dev.authorityclosers.com/review-fixture/shell"),
  );
});

test("capture tabs cover the current fictional shell panels", async () => {
  const fixture = await readFile(
    "apps/sales-xray-web/app/review-fixture/shell/full-shell-preview.tsx",
    "utf8",
  );
  const panelLabels = [...fixture.matchAll(/id: "[\w-]+",\s+label: "([^"]+)"/g)]
    .map((match) => match[1])
    .filter((label) => label !== "Overview");
  const captureLabels = frames
    .filter((item) => item.tab)
    .map((item) => item.tab);
  assert.deepEqual(new Set(captureLabels), new Set(panelLabels));
});

test("unavailable measurements never become zero", () => {
  const row = unavailable(frames[0], viewports[1]);
  for (const key of [
    "screenshot",
    "overflow_count",
    "console_error_count",
    "uncaught_exception_count",
    "axe_critical_count",
  ])
    assert.equal(row[key], null);
});

test("browser measures actual overflow, console, uncaught and critical axe violations without saving content", async () => {
  const directory = await mkdtemp(
    join(
      process.env.PAPERCLIP_RUN_SCRATCH_DIR ??
        process.env.RUNNER_TEMP ??
        tmpdir(),
      "visual-test-",
    ),
  );
  const serverRequests = [];
  const server = createServer((request, response) => {
    serverRequests.push(request.url);
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(
      '<!doctype html><html lang="en"><head><title>Fictional test</title></head><body><main id="fixture"><div style="width:2000px">Fictional overflow</div><button></button></main><script>console.error("fixture-private-message");throw new Error("fixture-private-exception")</script></body></html>',
    );
  });
  let browser;
  try {
    await new Promise((ready, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", ready);
    });
    browser = await chromium.launch();
    await waitForFixtureServer(
      `http://127.0.0.1:${server.address().port}/review-fixture/shell`,
    );
    const require = createRequire(import.meta.url);
    const nextRequire = createRequire(
      require.resolve("eslint-config-next", {
        paths: [resolve("apps/sales-xray-web")],
      }),
    );
    const axePath = createRequire(
      nextRequire.resolve("eslint-plugin-jsx-a11y"),
    ).resolve("axe-core");
    const origin = `http://127.0.0.1:${server.address().port}`;
    const policyContext = await browser.newContext();
    await policyContext.route("**/*", (route) =>
      routeFixtureRequest(route, origin, new Set(["/"])),
    );
    const policyPage = await policyContext.newPage();
    await policyPage.goto(origin);
    assert.deepEqual(
      await policyPage.evaluate(async () => (await fetch("/health")).json()),
      { analysis_read_only: true },
    );
    assert.ok(!serverRequests.includes("/health"));
    assert.equal(
      await policyPage.evaluate(() =>
        fetch("/health", { method: "POST" }).then(
          () => false,
          () => true,
        ),
      ),
      true,
    );
    assert.equal(
      await policyPage.evaluate(() =>
        fetch("/v1/me").then(
          () => false,
          () => true,
        ),
      ),
      true,
    );
    const blockedSocket = await policyPage.evaluate(
      () =>
        new Promise((done) => {
          const socket = new WebSocket("wss://external.invalid/socket");
          socket.onerror = () => done(true);
          socket.onopen = () => done(false);
          setTimeout(() => done(false), 1000);
        }),
    );
    assert.equal(blockedSocket, true);
    await policyContext.close();
    const page = await browser.newPage({ viewport: viewports[1] });
    const row = await capture(
      page,
      { id: "test", route: "/", ready: "#fixture" },
      viewports[1],
      directory,
      axePath,
      `http://127.0.0.1:${server.address().port}`,
    );
    assert.equal(row.capture_status, "measured");
    assert.ok(row.overflow_px > 0);
    assert.ok(row.overflow_count > 0);
    assert.ok(row.console_error_count >= 1);
    assert.equal(row.uncaught_exception_count, 1);
    assert.ok(row.axe_critical_count > 0);
    assert.ok(!JSON.stringify(row).includes("fixture-private"));
    const missingPage = await browser.newPage({ viewport: viewports[1] });
    const missing = await capture(
      missingPage,
      { id: "missing", route: "/", ready: "#absent" },
      viewports[1],
      directory,
      axePath,
      `http://127.0.0.1:${server.address().port}`,
    );
    assert.equal(missing.console_error_count, null);
    assert.equal(missing.axe_critical_count, null);
  } finally {
    await browser?.close();
    await new Promise((done) => server.close(done));
    await rm(directory, { recursive: true, force: true });
  }
});
