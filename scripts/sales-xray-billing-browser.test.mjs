import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

let origin = process.env.AC_BILLING_BROWSER_ORIGIN;
if (origin)
  assert.equal(
    new URL(origin).hostname,
    "127.0.0.1",
    "Use the local development fixture only.",
  );

test("fictional plan purchase → server verification → balance → billing → cancel", async () => {
  let server;
  let serverOutput = "";
  let browser;
  let lastPage;
  try {
    if (!process.env.AC_BILLING_BROWSER_ORIGIN) {
      const port = await new Promise((resolve, reject) => {
        const probe = createServer();
        probe.once("error", reject);
        probe.listen(0, "127.0.0.1", () => {
          const port = probe.address().port;
          probe.close(() => resolve(port));
        });
      });
      origin = `http://127.0.0.1:${port}`;
      const env = {
        PATH: process.env.PATH,
        NODE_ENV: "development",
        NEXT_TELEMETRY_DISABLED: "1",
        AC_CONVERSATION_API_ORIGIN: "",
        AC_SALES_XRAY_STATIC_PREVIEW: "0",
      };
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
          String(port),
        ],
        {
          cwd: fileURLToPath(
            new URL("../apps/sales-xray-web", import.meta.url),
          ),
          env,
          stdio: ["ignore", "pipe", "pipe"],
        },
      );
      const captureOutput = (chunk) => {
        serverOutput = (serverOutput + chunk.toString()).slice(-8000);
      };
      server.stdout.on("data", captureOutput);
      server.stderr.on("data", captureOutput);
      const deadline = Date.now() + 120_000;
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
              // Keep a cold route compilation alive on the shared host.
              signal: AbortSignal.timeout(
                Math.min(60_000, deadline - Date.now()),
              ),
            })
          ).ok;
        } catch {
          /* Still starting. */
        }
        if (!ready) await new Promise((resolve) => setTimeout(resolve, 250));
      }
      assert.equal(ready, true, "The owned fixture server must become ready.");
      for (const path of [
        "/review-fixture/plans/pay",
        "/review-fixture/plans/return",
      ])
        assert.equal(
          (
            await fetch(`${origin}${path}`, {
              signal: AbortSignal.timeout(60_000),
            })
          ).ok,
          true,
        );
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
      lastPage = page;
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(`${origin}/review-fixture/plans`, {
        waitUntil: "domcontentloaded",
      });
      await page.getByText("Current: Trial", { exact: false }).waitFor();
      if (width === 390)
        await page.getByRole("tab", { name: "Personal", exact: true }).click();
      await page
        .getByRole("button", { name: "Get Personal", exact: true })
        .click();
      await page
        .getByRole("button", {
          name: "Review total",
          exact: true,
        })
        .click();
      await page.getByText("Total confirmed.", { exact: false }).waitFor();
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
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
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.getByText("862 analysis minutes", { exact: true }).waitFor();
      await page
        .getByRole("button", { name: "Manage billing", exact: true })
        .click();
      await page
        .getByText("862 min (14 h 22 min) left", { exact: true })
        .waitFor();
      await page
        .getByRole("button", { name: "Cancel renewal", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Yes, cancel renewal", exact: true })
        .click();
      await page.getByText("Cancels at period end", { exact: true }).waitFor();
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.getByText("Cancels at period end", { exact: true }).waitFor();
      await page
        .getByText("862 min (14 h 22 min) left", { exact: true })
        .waitFor();
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      await page
        .getByRole("button", { name: "Start again", exact: true })
        .click();
      await page.goto(`${origin}/review-fixture/plans`, {
        waitUntil: "domcontentloaded",
      });
      await page.getByText("Current: Trial", { exact: false }).waitFor();
      await page
        .getByRole("button", { name: "Get Organisation", exact: true })
        .click();
      const review = page.getByRole("button", {
        name: "Review total",
        exact: true,
      });
      await review.click();
      assert.equal(
        await page.getByText("Total confirmed.", { exact: false }).count(),
        0,
      );
      await page.getByLabel("Organisation name").fill("Fictional Closers");
      await page.getByLabel("GSTIN (optional)").fill("invalid");
      await review.click();
      assert.equal(
        await page.getByText("Total confirmed.", { exact: false }).count(),
        0,
      );
      await page.getByLabel("GSTIN (optional)").fill("27abcde1234f1z5");
      assert.equal(
        await page.getByLabel("GSTIN (optional)").inputValue(),
        "27ABCDE1234F1Z5",
      );
      await review.click();
      await page.getByText("Total confirmed.", { exact: false }).waitFor();
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      await page
        .getByRole("button", { name: "Pay ₹23,600 with Razorpay", exact: true })
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
      await page
        .getByRole("button", { name: "Manage billing", exact: true })
        .click();
      await page.getByText("FIXTURE-1", { exact: true }).waitFor();
      const downloadPromise = page.waitForEvent("download");
      await page
        .getByRole("link", { name: "Invoice for FIXTURE-1", exact: true })
        .click();
      const download = await downloadPromise;
      let invoice = "";
      for await (const chunk of await download.createReadStream())
        invoice += chunk.toString();
      assert.match(invoice, /Fictional Closers/);
      assert.match(invoice, /27ABCDE1234F1Z5/);
      assert.match(invoice, /2360000/);
      assert.equal(await download.failure(), null);
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
  } catch (error) {
    if (serverOutput) console.error(serverOutput);
    if (lastPage && !lastPage.isClosed())
      console.log(
        "Fictional fixture failure:",
        await lastPage.locator("body").innerText(),
      );
    throw error;
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
