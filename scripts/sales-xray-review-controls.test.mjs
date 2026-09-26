import assert from "node:assert/strict";
import http from "node:http";
import { after, before, beforeEach, test } from "node:test";
import { chromium } from "playwright";

import { fixtureStateIds } from "../apps/sales-xray-web/app/fixture-review-states.ts";
import { reviewHtml, reviewScript } from "./sales-xray-review-controls.mjs";

const callId = "11111111-2222-4333-8444-555555555555";
const localFrameId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const processingFrameId = "10000000-2000-4000-8000-000000000001";
const reportFrameId = "10000000-2000-4000-8000-000000000002";

let browser;
let server;
let origin;
let calls;

function json(response, value) {
  response.writeHead(200, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
  });
  response.end(JSON.stringify(value));
}

function localCatalog() {
  return {
    expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
    frames: [
      {
        id: localFrameId,
        label: "Upload · empty · observed in this browser",
        observedAt: new Date().toISOString(),
      },
    ],
  };
}

function callCatalog() {
  const observedAt = new Date().toISOString();
  return {
    callId,
    expiresAt: new Date(Date.now() + 10 * 60_000).toISOString(),
    frames: [
      {
        id: processingFrameId,
        state: "processing.c2.running",
        observedAt,
      },
      { id: reportFrameId, state: "report.available", observedAt },
    ],
  };
}

before(async () => {
  browser = await chromium.launch({ headless: true });
  calls = { start: [], catalog: 0, localCatalog: 0, reset: 0, other: [] };
  server = http.createServer(async (request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (request.method === "GET" && url.pathname === "/__review/") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(reviewHtml);
      return;
    }
    if (request.method === "GET" && url.pathname === "/__review/controls.js") {
      response.writeHead(200, {
        "content-type": "text/javascript; charset=utf-8",
      });
      response.end(reviewScript);
      return;
    }
    if (url.pathname === "/__review/api/local/catalog") {
      calls.localCatalog += 1;
      json(response, localCatalog());
      return;
    }
    if (url.pathname === "/__review/api/start") {
      let body = "";
      for await (const chunk of request) body += chunk;
      const value = JSON.parse(body);
      calls.start.push(value.call_id);
      json(response, callCatalog());
      return;
    }
    if (url.pathname === "/__review/api/catalog") {
      calls.catalog += 1;
      json(response, callCatalog());
      return;
    }
    if (url.pathname === "/__review/api/reset") {
      calls.reset += 1;
      json(response, { reset: true });
      return;
    }
    if (request.method === "GET" && url.pathname === "/") {
      response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      response.end(
        "<!doctype html><title>Local app test endpoint</title><main>App endpoint</main>",
      );
      return;
    }
    calls.other.push(`${request.method} ${url.pathname}`);
    response.writeHead(404, { "content-type": "application/json" });
    response.end('{"detail":"not found"}');
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  origin = `http://127.0.0.1:${server.address().port}`;
});

beforeEach(() => {
  calls = { start: [], catalog: 0, localCatalog: 0, reset: 0, other: [] };
});

after(async () => {
  await browser?.close();
  if (server?.listening)
    await new Promise((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
});

async function newPage(viewport = { width: 1440, height: 1000 }) {
  const context = await browser.newContext({
    viewport,
  });
  await context.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: async (value) => (window.__copiedUrl = value) },
    });
    Object.defineProperty(HTMLIFrameElement.prototype, "requestFullscreen", {
      configurable: true,
      value: async function () {
        window.__fullscreenFrame = this.name;
      },
    });
  });
  const page = await context.newPage();
  return { context, page };
}

test("workbench selects only observed states and restores bookmarkable app URLs", async () => {
  const { context, page } = await newPage();
  try {
    await page.goto(`${origin}/__review/`);
    assert.equal(
      await page.locator("#annotations li").first().textContent(),
      "Top section · “Add a call to review…” heading area. First review item: inspect its hierarchy, spacing and responsive wrapping on the actual empty upload screen.",
    );
    const frame = page.locator("iframe#sales-xray-canvas");
    assert.equal(await frame.getAttribute("name"), "sales-xray-canvas");
    await page.getByText("Upload · empty · observed in this browser").waitFor();
    assert.equal(new URL(await frame.getAttribute("src")).origin, origin);

    await page
      .locator("#call")
      .fill(`https://attacker.example/?call=${callId}`);
    await page.getByRole("button", { name: "Load observed states" }).click();
    await page
      .getByText("Enter one valid saved call ID or Sales Xray call URL.")
      .waitFor();
    assert.deepEqual(calls.start, []);

    await page
      .locator("#call")
      .fill(`https://salesxray.authorityclosers.com/?call=${callId}`);
    await page.getByRole("button", { name: "Load observed states" }).click();
    await page
      .locator("#selected-name")
      .getByText("processing.c2.running", { exact: true })
      .waitFor();
    assert.equal(calls.start.at(-1), callId);

    const direct = page.locator("#direct-url");
    let directUrl = new URL(await direct.inputValue());
    assert.equal(directUrl.origin, origin);
    assert.equal(directUrl.searchParams.get("call"), callId);
    assert.equal(
      new URL(page.url()).hash.includes(`frame=${processingFrameId}`),
      true,
    );

    await page.getByRole("button", { name: "Next state" }).click();
    await page
      .locator("#selected-name")
      .getByText("report.available", { exact: true })
      .waitFor();
    assert.equal(page.url().includes(`frame=${reportFrameId}`), true);
    assert.equal(
      await page
        .getByRole("button", { name: "Next state" })
        .isDisabled(),
      true,
    );
    await page.getByRole("button", { name: "Previous state" }).click();
    await page
      .locator("#selected-name")
      .getByText("processing.c2.running", { exact: true })
      .waitFor();

    await page.getByRole("button", { name: "Next state" }).click();
    await page
      .locator("#selected-name")
      .getByText("report.available", { exact: true })
      .waitFor();
    const bookmarked = page.url();
    await page.reload();
    await page
      .locator("#selected-name")
      .getByText("report.available", { exact: true })
      .waitFor();
    assert.equal(page.url(), bookmarked);
    assert.equal(calls.start.filter((id) => id === callId).length, 2);
    directUrl = new URL(await direct.inputValue());
    assert.equal(directUrl.origin, origin);
    assert.equal(directUrl.searchParams.get("call"), callId);

    await page
      .locator(`#state-list [data-state-key="local:${localFrameId}"]`)
      .click();
    await page
      .getByText("Browser-local · observed", { exact: false })
      .first()
      .waitFor();
    directUrl = new URL(await direct.inputValue());
    assert.equal(directUrl.origin, origin);
    assert.equal(directUrl.searchParams.get("sx-review-local"), localFrameId);
    const localBookmark = page.url();
    await page.reload();
    await page
      .locator(`#state-list [data-state-key="local:${localFrameId}"]`)
      .waitFor();
    assert.equal(page.url(), localBookmark);
    assert.equal(
      new URL(await direct.inputValue()).searchParams.get("sx-review-local"),
      localFrameId,
    );

    await page.getByRole("button", { name: "Mobile · 390 px" }).click();
    assert.equal(
      await page.locator("#canvas-viewport").getAttribute("data-width"),
      "mobile",
    );
    assert.match(page.url(), /width=mobile/);
    await page.setViewportSize({ width: 390, height: 844 });
    const dimensions = await page.evaluate(() => ({
      pageWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      canvasWidth: document
        .querySelector("#sales-xray-canvas")
        .getBoundingClientRect().width,
    }));
    assert.ok(dimensions.pageWidth <= dimensions.viewportWidth);
    assert.ok(dimensions.canvasWidth <= dimensions.viewportWidth);

    await page.getByRole("button", { name: "Copy" }).click();
    assert.equal(
      await page.evaluate(() => window.__copiedUrl),
      await direct.inputValue(),
    );
    await page.getByRole("button", { name: "Open full screen" }).click();
    assert.equal(
      await page.evaluate(() => window.__fullscreenFrame),
      "sales-xray-canvas",
    );
    assert.deepEqual(calls.other, []);
  } finally {
    await context.close();
  }
});

test("workbench opens pauseable fixture URLs without contacting the call API", async () => {
  const { context, page } = await newPage();
  try {
    const bookmark = `${origin}/__review/#sx-workbench=v1&kind=fixture&id=processing.paused&width=desktop`;
    await page.goto(bookmark);
    await page.locator("#selected-name").getByText("Analysis paused").waitFor();
    assert.deepEqual(
      await page.locator("#fixture-list [data-state-key]").evaluateAll((buttons) =>
        buttons.map((button) => button.dataset.stateKey.slice("fixture:".length)),
      ),
      [...fixtureStateIds],
    );
    assert.equal(await page.locator("#fixture-navigation").getAttribute("open"), "");
    let direct = new URL(await page.locator("#direct-url").inputValue());
    assert.equal(direct.origin, origin);
    assert.equal(direct.searchParams.get("sx-fixture"), "processing.paused");
    assert.equal(direct.searchParams.get("new"), "1");
    assert.equal(calls.start.length, 0);

    await page.reload();
    await page.locator("#selected-name").getByText("Analysis paused").waitFor();
    assert.equal(page.url(), bookmark);
    await page.getByRole("button", { name: "Next state" }).click();
    await page.locator("#selected-name").getByText("Analysis needs attention").waitFor();
    direct = new URL(await page.locator("#direct-url").inputValue());
    assert.equal(direct.searchParams.get("sx-fixture"), "processing.failed");
    assert.equal(calls.start.length, 0);

    await page
      .locator('#fixture-list [data-state-key="fixture:auth.email"]')
      .click();
    direct = new URL(await page.locator("#direct-url").inputValue());
    assert.equal(direct.searchParams.get("sx-fixture"), "auth.email");
    assert.equal(
      await page.locator("#sales-xray-canvas").getAttribute("src"),
      direct.href,
    );
    assert.deepEqual(calls.other, []);
  } finally {
    await context.close();
  }
});

test("canvas is immediately visible at desktop and mobile editor sizes", async () => {
  const { context, page } = await newPage({ width: 846, height: 698 });
  try {
    await page.goto(`${origin}/__review/`);
    await page
      .locator(`#state-list [data-state-key="local:${localFrameId}"]`)
      .waitFor();
    const desktop = await page.evaluate(() => {
      const canvas = document
        .querySelector("#sales-xray-canvas")
        .getBoundingClientRect();
      return {
        canvasTop: canvas.top,
        canvasVisibleHeight: Math.max(
          0,
          Math.min(canvas.bottom, innerHeight) - Math.max(canvas.top, 0),
        ),
        pageWidth: document.documentElement.scrollWidth,
        viewportWidth: innerWidth,
        navOpen: document.querySelector("#state-navigation").open,
        reviewNoteOpen: document.querySelector(".review-note").open,
      };
    });
    assert.ok(desktop.canvasTop < 380, JSON.stringify(desktop));
    assert.ok(desktop.canvasVisibleHeight > 200, JSON.stringify(desktop));
    assert.ok(
      desktop.pageWidth <= desktop.viewportWidth,
      JSON.stringify(desktop),
    );
    assert.equal(desktop.navOpen, true);
    assert.equal(desktop.reviewNoteOpen, false);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(
      () => !document.querySelector("#state-navigation").open,
    );
    const mobile = await page.evaluate(() => {
      const canvas = document
        .querySelector("#sales-xray-canvas")
        .getBoundingClientRect();
      const summary = document
        .querySelector("#state-navigation > summary")
        .getBoundingClientRect();
      return {
        canvasTop: canvas.top,
        canvasVisibleHeight: Math.max(
          0,
          Math.min(canvas.bottom, innerHeight) - Math.max(canvas.top, 0),
        ),
        summaryHeight: summary.height,
        pageWidth: document.documentElement.scrollWidth,
        viewportWidth: innerWidth,
      };
    });
    assert.ok(mobile.canvasTop < 500, JSON.stringify(mobile));
    assert.ok(mobile.canvasVisibleHeight > 200, JSON.stringify(mobile));
    assert.ok(mobile.summaryHeight >= 40, JSON.stringify(mobile));
    assert.ok(mobile.pageWidth <= mobile.viewportWidth, JSON.stringify(mobile));

    await page.locator("#state-navigation > summary").click();
    await page
      .locator(`#state-list [data-state-key="local:${localFrameId}"]`)
      .click();
    assert.match(
      await page.locator("#selected-name").innerText(),
      /Upload · empty/,
    );
    assert.equal(
      new URL(await page.locator("#direct-url").inputValue()).searchParams.get(
        "sx-review-local",
      ),
      localFrameId,
    );
  } finally {
    await context.close();
  }
});

test("invalid bookmark destinations fail closed and never reach the call API", async () => {
  const { context, page } = await newPage();
  try {
    const unsafeCall = `https://attacker.example/?call=${callId}`;
    await page.goto(
      `${origin}/__review/#sx-workbench=v1&kind=processing&call=invalid&frame=${processingFrameId}&width=desktop`,
    );
    await page.locator("#direct-url").waitFor();
    await page.locator("#call").fill(unsafeCall);
    await page.getByRole("button", { name: "Load observed states" }).click();
    await page
      .getByText("Enter one valid saved call ID or Sales Xray call URL.")
      .waitFor();
    assert.deepEqual(calls.start, []);
    const frameUrl = new URL(
      await page.locator("#sales-xray-canvas").getAttribute("src"),
    );
    assert.equal(frameUrl.origin, origin);
    assert.equal(frameUrl.pathname, "/");
    assert.deepEqual(calls.other, []);
  } finally {
    await context.close();
  }
});
