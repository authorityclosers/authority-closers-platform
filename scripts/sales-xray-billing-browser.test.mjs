import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const origin = process.env.AC_BILLING_BROWSER_ORIGIN ?? "http://127.0.0.1:3027";
assert.equal(
  new URL(origin).hostname,
  "127.0.0.1",
  "Use the local development fixture only.",
);

test("fictional plan purchase → server verification → balance → billing → cancel", async () => {
  let server;
  let browser;
  try {
    if (!process.env.AC_BILLING_BROWSER_ORIGIN) {
      const env = { ...process.env, NODE_ENV: "development" };
      delete env.AC_CONVERSATION_API_ORIGIN;
      delete env.AC_SALES_XRAY_STATIC_PREVIEW;
      server = spawn(
        process.execPath,
        [
          fileURLToPath(
            new URL(
              "../apps/sales-xray-web/node_modules/next/dist/bin/next",
              import.meta.url,
            ),
          ),
          "dev",
          "--hostname",
          "127.0.0.1",
          "--port",
          "3027",
        ],
        {
          cwd: fileURLToPath(
            new URL("../apps/sales-xray-web", import.meta.url),
          ),
          env,
          stdio: "ignore",
        },
      );
      const deadline = Date.now() + 60_000;
      let ready = false;
      while (!ready && Date.now() < deadline) {
        assert.equal(
          server.exitCode,
          null,
          "The owned fixture server must remain running.",
        );
        try {
          ready = (
            await fetch(`${origin}/review-fixture/plans`, {
              signal: AbortSignal.timeout(5000),
            })
          ).ok;
        } catch {
          /* Still starting. */
        }
        if (!ready) await new Promise((resolve) => setTimeout(resolve, 250));
      }
      assert.equal(ready, true, "The owned fixture server must become ready.");
    }
    browser = await chromium.launch({ headless: true });
    for (const width of [390, 1440]) {
      const context = await browser.newContext({
        viewport: { width, height: 950 },
        serviceWorkers: "block",
      });
      const external = [];
      const errors = [];
      await context.route("**/*", (route) => {
        if (new URL(route.request().url()).origin === origin)
          return route.continue();
        external.push(new URL(route.request().url()).hostname);
        return route.abort();
      });
      const page = await context.newPage();
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`${origin}/review-fixture/plans`, {
        waitUntil: "networkidle",
      });
      await page.getByText("Current: Trial", { exact: false }).waitFor();
      await page
        .getByRole("button", { name: "Get Personal", exact: true })
        .click();
      await page
        .getByRole("button", {
          name: "Review total with Razorpay",
          exact: true,
        })
        .click();
      await page.getByText("Total confirmed.", { exact: false }).waitFor();
      assert.match(await page.locator("body").innerText(), /₹381\.20 included/);
      assert.equal(new URL(page.url()).pathname, "/review-fixture/plans");
      await page
        .getByRole("button", { name: "Pay ₹2,499 with Razorpay", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "Fictional payment page" })
        .waitFor();
      await page
        .getByRole("button", { name: "Payment confirmed", exact: true })
        .click();
      await page
        .getByRole("heading", { name: "Payment confirmed", exact: true })
        .waitFor();
      await page.getByText("862 analysis minutes", { exact: true }).waitFor();
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("862 analysis minutes", { exact: true }).waitFor();
      await page
        .getByRole("button", { name: "Manage billing", exact: true })
        .click();
      await page.getByText("862 min left", { exact: true }).waitFor();
      await page
        .getByRole("button", { name: "Cancel renewal", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Yes, cancel renewal", exact: true })
        .click();
      await page.getByText("Cancels at period end", { exact: true }).waitFor();
      await page.reload({ waitUntil: "networkidle" });
      await page.getByText("Cancels at period end", { exact: true }).waitFor();
      await page.getByText("862 min left", { exact: true }).waitFor();
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      assert.deepEqual(errors, []);
      assert.deepEqual(external, []);
      await context.close();
    }
  } finally {
    await browser?.close();
    if (server) {
      server.kill("SIGTERM");
      await Promise.race([
        new Promise((resolve) => server.once("exit", resolve)),
        new Promise((resolve) => setTimeout(resolve, 3000)),
      ]);
      if (server.exitCode === null) server.kill("SIGKILL");
    }
  }
});
