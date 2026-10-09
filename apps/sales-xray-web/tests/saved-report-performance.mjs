// Card 7 extension of ea-study/reports/artifacts/browser-study.cjs:
// same Playwright request timestamps, fictional responses and 150 ms delay.
// Measures the actual observer, not dashboard paint or provider execution.
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { writeFile } from "node:fs/promises";

const require = createRequire(import.meta.url);
const vitestRequire = createRequire(require.resolve("vitest/package.json"));
const { createServer } = await import(vitestRequire.resolve("vite"));
const { chromium } = require("playwright");
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const scratch = process.env.PAPERCLIP_RUN_SCRATCH_DIR;
if (!scratch || !process.argv[2])
  throw new Error(
    "Set PAPERCLIP_RUN_SCRATCH_DIR and provide an output JSON path",
  );
const server = await createServer({
  configFile: false,
  root,
  cacheDir: resolve(scratch, "vite-cache"),
  server: { host: "127.0.0.1", port: 0 },
  plugins: [
    {
      name: "fictional-performance-harness",
      configureServer(server) {
        server.middlewares.use("/performance-harness", (_req, res) => {
          res.setHeader("Content-Type", "text/html");
          res.end(
            "<!doctype html><title>Fictional saved-report measurement</title>",
          );
        });
      },
    },
  ],
});
let browser;
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage();
  let delayMs = 150;
  let start = 0;
  let requests = [];
  const fixture = await server.ssrLoadModule("/tests/acquisition-fixture.ts");
  page.on("request", (req) => {
    if (new URL(req.url()).pathname.startsWith("/v1/"))
      requests.push({
        path: new URL(req.url()).pathname,
        startMs: Date.now() - start,
      });
  });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (!url.pathname.startsWith("/v1/")) return route.continue();
    const payload = url.pathname.endsWith("/transcript")
      ? fixture.transcript
      : url.pathname.endsWith("/report")
        ? fixture.envelope
        : { ...fixture.progress, has_report: true };
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
  await page.goto(`${origin}/performance-harness`);
  await page.evaluate(async () => {
    window.observer = await import("/app/observe-submission.ts");
    window.fixture = await import("/tests/acquisition-fixture.ts");
  });
  const samples = [];
  for (delayMs of [150, 300]) {
    for (let rep = 1; rep <= 3; rep++) {
      requests = [];
      start = Date.now();
      const elapsedMs = await page.evaluate(async () => {
        const { submissionId, recordingId, progress } = window.fixture;
        const start = performance.now();
        const observed = await window.observer.observeSubmission(
          { id: submissionId, recordingId, sha: progress.source_sha256 },
          new AbortController().signal,
        );
        if (!observed.result?.report)
          throw new Error("Verified report missing");
        return performance.now() - start;
      });
      samples.push({ delayMs, rep, elapsedMs, requests });
    }
  }
  await writeFile(
    process.argv[2],
    JSON.stringify(
      {
        method:
          "Playwright, actual observer via Vite, fictional canary, 3 GETs",
        samples,
      },
      null,
      2,
    ) + "\n",
  );
  console.log(JSON.stringify(samples));
} finally {
  await browser?.close();
  await server.close();
}
