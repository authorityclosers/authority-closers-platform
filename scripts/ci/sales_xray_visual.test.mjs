import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";
import { chromium } from "playwright";
import {
  allowedRequest,
  capture,
  frames,
  selectFrames,
  unavailable,
  viewports,
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
  assert.ok(allowed(`${origin}/_next/static/test.js`));
  assert.ok(!allowed(`${origin}/v1/me/workspaces`));
  assert.ok(!allowed(`${origin}/__review/api/frames/a`));
  assert.ok(!allowed(`${origin}/review-fixture/shell`, "POST"));
  assert.ok(
    !allowed("https://salesxray-dev.authorityclosers.com/review-fixture/shell"),
  );
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
  const server = createServer((_request, response) => {
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
    const require = createRequire(import.meta.url);
    const nextRequire = createRequire(
      require.resolve("eslint-config-next", {
        paths: [resolve("apps/sales-xray-web")],
      }),
    );
    const axePath = createRequire(
      nextRequire.resolve("eslint-plugin-jsx-a11y"),
    ).resolve("axe-core");
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
