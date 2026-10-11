// Sales Xray release journeys (AUT-1663, owner 11 Oct 03:30 IST).
//
// Real click-through flows on a production build (`next build` + the
// standalone server), against fictional API answers (page-matrix fixtures):
//   sign-in -> Dashboard; Dashboard -> Calls -> filter, search -> a call;
//   New analysis -> choose a recording; Coaching (mine, team); Settings.
// Each at 1440 and 390 px in light and dark. Then every overlay opens and
// closes 50 times (workspace switcher, profile menu, account card, settings,
// the phone's More sheet, the corner card): each time it must open, close,
// give focus back and leave nothing behind.
//
// Fails on any page error, error screen, missing step, or an overlay that
// sticks, leaks or loses focus. Writes receipts.json (and a screenshot of
// each failure) to --out.
//
//   node apps/sales-xray-web/scripts/release-journeys.mjs \
//     --origin http://127.0.0.1:3016 --out "$RUNNER_TEMP/journeys" \
//     [--only sign-in,calls] [--repeat 50]
import { readFileSync } from "node:fs";
import { mkdir, writeFile, appendFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  fictionalCallCoaching,
  fictionalCoaching,
  fictionalTeamCoaching,
} from "../app/coaching/coaching.fixture.ts";
import { answer, fixtureFor } from "./page-matrix-fixtures.mjs";

/** The call whose coaching the per-call journey opens (Strike D's fixture). */
export const COACHING_CALL = fictionalCallCoaching.submission_id;

export const VARIANTS = [
  [1440, 900, "light"],
  [1440, 900, "dark"],
  [390, 844, "light"],
  [390, 844, "dark"],
];

const SNAG =
  /This screen hit a snag|Application error: a client-side exception/;
const ACQ = "/v1/conversation/acquisition";

/**
 * A saved call with a ready report, built like tests/acquisition-fixture.ts
 * from the invented Dipak overview (transcript + report): what the report
 * preload reads for /analysis/calls/<id>.
 */
export const REPORT_CALL = "7b6443d3-9b2d-4f97-9e70-5e82e54f8738";
function savedReport() {
  const fixture = JSON.parse(
    readFileSync(
      join(
        dirname(fileURLToPath(import.meta.url)),
        "../tests/fixtures/dipak-overview.json",
      ),
      "utf8",
    ),
  );
  const recordingId = "fd4b05b1-bfc9-4d28-a379-f3d032faf7af";
  const { source_sha256, transcript_revision, source_label, review_status } =
    fixture.report;
  // The report's content without the envelope fields (as the studio tests do).
  const content = { ...fixture.report };
  for (const key of [
    "source_sha256",
    "transcript_revision",
    "source_label",
    "review_status",
    "report_sections",
  ])
    delete content[key];
  const base = `${ACQ}/submissions/${REPORT_CALL}`;
  return {
    [base]: {
      submission_id: REPORT_CALL,
      recording_id: recordingId,
      source_sha256,
      state: "report_ready",
      local_state: "completed",
      has_report: true,
      automatic_progression: false,
      stages: [],
    },
    [`${base}/transcript`]: fixture.transcript,
    [`${base}/report`]: {
      schema: "ac.sales-xray.report-envelope/2",
      submission_id: REPORT_CALL,
      recording_id: recordingId,
      run_id: "02de89cf-8e5e-4bde-8eb6-c8fcd79ed4de",
      source_sha256,
      transcript_revision,
      source_label,
      report: {
        schema: "ac.sales-xray.report-access/2",
        access: "guest_preview",
        review_status,
        numeric_publication: false,
        content: { ...content, next_action: content.improvements[0] },
        sections: [],
        unlock: null,
      },
    },
  };
}

/** Who the page-matrix owner is (page-matrix-fixtures.mjs). */
const OWNER_SCOPE = {
  person_id: "00000000-0000-4000-8000-000000000001",
  tenant_id: "22222222-2222-4222-8222-222222222222",
};

/** The page-matrix owner, plus the studio's reads and a sign-in switch. */
export function journeyApi({ signedIn = true, failing = [] } = {}) {
  const state = { signedIn, writes: [] };
  const table = {
    ...fixtureFor("owner"),
    [`${ACQ}/entry`]: {
      enabled: true,
      auth_mode: "account",
      site_key: null,
      challenge_action: null,
      policy_revision: "policy-2026-10",
      // The entry contract caps the advertised trial at 100 minutes.
      allowance_seconds: 6_000,
    },
    [`${ACQ}/upload-policy`]: {
      schema: "ac.sales-xray.private-upload-consent/1",
      max_cost_paise: 0,
      policy_sha256: "a".repeat(64),
      title: "Private analysis",
      description: "Your recording stays private to your workspace.",
      maximum_file_bytes: 32 * 1024 ** 2,
      maximum_call_seconds: 3600,
      retention_days: 30,
    },
    [`${ACQ}/availability`]: { paused: false },
    ...savedReport(),
    // Coaching (Strike D): its own invented contract fixtures, for the
    // page-matrix owner in the page-matrix organisation.
    "/v1/me/coaching": { ...fictionalCoaching, ...OWNER_SCOPE },
    "/v1/me/coaching/team": { ...fictionalTeamCoaching, ...OWNER_SCOPE },
    [`/v1/me/coaching/calls/${COACHING_CALL}`]: {
      ...fictionalCallCoaching,
      ...OWNER_SCOPE,
    },
  };
  const respond = (method, pathname, search) => {
    if (method === "POST" && pathname === "/v1/auth/password/login") {
      state.signedIn = true;
      return { status: 200, body: { ok: true } };
    }
    if (failing.includes(pathname))
      return { status: 503, body: { detail: "Temporarily unavailable." } };
    if (!state.signedIn) return answer({}, "guest", method, pathname, search);
    if (method !== "GET" && method !== "HEAD")
      state.writes.push(`${method} ${pathname}`);
    return answer(table, "owner", method, pathname, search);
  };
  return { state, respond };
}

/** One second of silence as a WAV file: a real recording the picker accepts. */
export function silentWav(seconds = 1, rate = 8000) {
  const samples = seconds * rate;
  const buffer = Buffer.alloc(44 + samples * 2);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + samples * 2, 4);
  buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(rate, 24);
  buffer.writeUInt32LE(rate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(samples * 2, 40);
  return buffer;
}

const phoneOf = (page) => (page.viewportSize()?.width ?? 1440) < 768;

async function settled(page) {
  await page
    .waitForLoadState("networkidle", { timeout: 15_000 })
    .catch(() => {});
  await page
    .waitForFunction(
      () => !document.querySelector('[aria-busy="true"]'),
      null,
      {
        timeout: 15_000,
      },
    )
    .catch(() => {});
}

/** Run one step; a failure names the step. */
async function step(name, body) {
  try {
    return await body();
  } catch (error) {
    throw new Error(
      `${name}: ${String(error.message ?? error).split("\n")[0]}`,
    );
  }
}

async function noSnag(page, where) {
  const text = await page.locator("body").innerText({ timeout: 5_000 });
  if (SNAG.test(text)) throw new Error(`${where}: the error screen showed`);
}

/** The journeys: each gets a fresh page signed in (or not) at one variant. */
export const JOURNEYS = {
  async "sign-in"(page, { origin }) {
    await page.goto(`${origin}/login`, { waitUntil: "domcontentloaded" });
    await page
      .getByRole("button", { name: /Use my existing password/ })
      .first()
      .click();
    await page
      .locator("#account-password-email")
      .fill("asha@brightline.example.in");
    await page.locator("#account-password").fill("fictional-password-1");
    await page.getByRole("button", { name: /^Sign in/ }).click();
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
    await settled(page);
    await page.locator("main h1").waitFor({ timeout: 10_000 });
    await page
      .locator('dl[aria-label="Dashboard figures"]')
      .waitFor({ timeout: 10_000 });
    await noSnag(page, "dashboard after sign-in");
  },

  async calls(page, { origin }) {
    await page.goto(`${origin}/dashboard`, { waitUntil: "domcontentloaded" });
    await settled(page);
    await page.getByRole("link", { name: /View all calls/ }).click();
    await page.waitForURL(/\/analysis\/calls/, { timeout: 15_000 });
    await settled(page);
    const rows = page.locator("main button.calls-library-item");
    await rows.first().waitFor({ timeout: 10_000 });
    const all = await rows.count();
    if (all < 3)
      throw new Error(`Calls lists ${all} calls (expected the 7 saved)`);
    await page
      .locator('[aria-label="Filter loaded calls by status"] button', {
        hasText: "Report ready",
      })
      .click();
    await page.waitForFunction(
      (count) =>
        document.querySelectorAll("main button.calls-library-item").length <
        count,
      all,
      { timeout: 5_000 },
    );
    await page
      .locator('[aria-label="Filter loaded calls by status"] button', {
        hasText: "All",
      })
      .click();
    await page
      .getByRole("searchbox", { name: /Search loaded calls/ })
      .fill("Discovery");
    await page.waitForFunction(
      () =>
        document.querySelectorAll("main button.calls-library-item").length ===
        1,
      null,
      { timeout: 5_000 },
    );
    if (!/[?&]q=Discovery/.test(page.url()))
      throw new Error("the search is not kept in the address");
    await rows.first().click();
    await page.waitForURL(/\/analysis\/calls\/[0-9a-f-]{36}/, {
      timeout: 15_000,
    });
    await settled(page);
    await noSnag(page, "the call");
  },

  async report(page, { origin }) {
    await page.goto(`${origin}/analysis/calls/${REPORT_CALL}`, {
      waitUntil: "domcontentloaded",
    });
    await settled(page);
    await step("the report's Overview", () =>
      page
        .getByRole("heading", { name: "Overview" })
        .waitFor({ timeout: 15_000 }),
    );
    await noSnag(page, "the saved report");
    // The fixture has no prospect service: its corner card says so; close it
    // so it does not cover the page on a phone.
    const dismiss = page.getByRole("button", { name: "Dismiss" });
    if (await dismiss.count()) await dismiss.first().click();
    // The chart's three views (phones show "Stages" and "Talk share"; their
    // names then read "StagesCall stages": matched by the shared word).
    for (const view of [/stages/i, /Talk share/, /Who talked/]) {
      await step(`the chart view ${view.source}`, () =>
        page
          .getByRole("group", { name: "What the map shows" })
          .getByRole("button", { name: view })
          .filter({ visible: true })
          .first()
          .click(),
      );
      await noSnag(page, `the report's ${view.source}`);
    }
    // A section of "Explore the call" (the report's own navigation then
    // takes over; its full walk belongs with the report's owners, Strike B).
    await step("the Moments section", () =>
      page
        .locator("main button", { hasText: /^Moments/ })
        .first()
        .click(),
    );
    await noSnag(page, "the report's Moments");
    // The transcript reader opens and closes.
    await step("the transcript reader", async () => {
      await page
        .getByRole("button", { name: "Open transcript reader" })
        .click();
      await page
        .locator("dialog[open], [role='dialog']")
        .first()
        .waitFor({ timeout: 5_000 });
    });
    await page.keyboard.press("Escape");
    await noSnag(page, "the transcript reader");
  },

  async "new-analysis"(page, { origin }) {
    await page.goto(`${origin}/analysis/new`, {
      waitUntil: "domcontentloaded",
    });
    await settled(page);
    const choose = page.getByRole("button", { name: "Choose a file" });
    await choose.waitFor({ timeout: 10_000 });
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll("main button")].some(
          (button) =>
            button.textContent?.trim() === "Choose a file" && !button.disabled,
        ),
      null,
      { timeout: 10_000 },
    );
    await page
      .locator(
        'main [aria-label="Add sales call audio files"] input[type="file"]',
      )
      .setInputFiles({
        name: "fictional-discovery-call.wav",
        mimeType: "audio/wav",
        buffer: silentWav(),
      });
    // The recording is staged and the private-upload consent comes next;
    // the journey stops before anything is sent.
    const analyse = page.getByRole("button", { name: /Analyse my call/ });
    await analyse.waitFor({ timeout: 10_000 });
    if (!(await analyse.isDisabled()))
      throw new Error("Analyse my call is enabled before consent");
    await page.getByRole("checkbox", { name: /I agree/ }).check();
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll("main button")].some(
          (button) =>
            /Analyse my call/.test(button.textContent ?? "") &&
            !button.disabled,
        ),
      null,
      { timeout: 5_000 },
    );
    await noSnag(page, "a chosen recording");
  },

  async coaching(page, { origin }) {
    // Mine: the focus skill; team: the team's skills; one call: its coaching.
    for (const [path, expected] of [
      ["/coaching", fictionalCoaching.focus.label],
      ["/coaching?view=team", fictionalTeamCoaching.suggestions?.[0]?.label],
      [`/coaching?call=${COACHING_CALL}`, "Coaching for this call"],
    ]) {
      await page.goto(`${origin}${path}`, { waitUntil: "domcontentloaded" });
      await settled(page);
      await noSnag(page, path);
      if (expected)
        await page
          .locator("main")
          .getByText(expected, { exact: false })
          .first()
          .waitFor({ timeout: 10_000 })
          .catch(() => {
            throw new Error(`${path}: "${expected}" did not show`);
          });
    }
  },

  async settings(page, { origin }) {
    await page.goto(`${origin}/dashboard`, { waitUntil: "domcontentloaded" });
    await settled(page);
    await openAccountCard(page);
    await page
      .getByRole("dialog", { name: "Account menu" })
      .getByRole("button", { name: /^Settings/ })
      .click();
    await page.waitForFunction(
      () => location.hash.startsWith("#settings"),
      null,
      {
        timeout: 5_000,
      },
    );
    await page.locator("dialog[open]").first().waitFor({ timeout: 5_000 });
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector("dialog[open]"),
      null,
      {
        timeout: 5_000,
      },
    );
    await noSnag(page, "settings");
  },
};

async function openAccountCard(page) {
  if (phoneOf(page))
    await page
      .getByRole("navigation", { name: "Mobile Sales Xray navigation" })
      .getByRole("button", { name: /More/ })
      .click();
  else
    await page
      .locator('aside [aria-label="Account"][aria-haspopup="dialog"]')
      .click();
  await page
    .getByRole("dialog", { name: "Account menu" })
    .waitFor({ timeout: 5_000 });
}

/**
 * Overlays: open, check, close, check focus came back, n times. `open`
 * returns the locator of what opened; `close` defaults to Escape.
 */
export const OVERLAYS = {
  "workspace switcher": {
    desktopOnly: true,
    trigger: (page) =>
      page.getByRole("button", { name: /^Current workspace:/ }),
    opened: (page) => page.getByRole("menu", { name: "Switch account" }),
  },
  "profile menu": {
    desktopOnly: true,
    trigger: (page) =>
      page.locator("header").getByRole("button", { expanded: false }).last(),
    opened: (page) => page.getByRole("region", { name: "Profile actions" }),
  },
  "account card": {
    trigger: (page) =>
      phoneOf(page)
        ? page
            .getByRole("navigation", { name: "Mobile Sales Xray navigation" })
            .getByRole("button", { name: /More/ })
        : page.locator('aside [aria-label="Account"][aria-haspopup="dialog"]'),
    opened: (page) => page.getByRole("dialog", { name: "Account menu" }),
  },
  settings: {
    trigger: (page) =>
      phoneOf(page)
        ? page
            .getByRole("navigation", { name: "Mobile Sales Xray navigation" })
            .getByRole("button", { name: /More/ })
        : page.locator('aside [aria-label="Account"][aria-haspopup="dialog"]'),
    then: async (page) =>
      page
        .getByRole("dialog", { name: "Account menu" })
        .getByRole("button", { name: /^Settings/ })
        .click(),
    opened: (page) => page.locator("dialog[open]").first(),
    focusBack: false,
  },
};

async function repeatOverlay(page, name, overlay, times) {
  const before = await page.evaluate(
    () => document.querySelectorAll("*").length,
  );
  for (let round = 1; round <= times; round += 1) {
    const trigger = overlay.trigger(page);
    await trigger.click({ timeout: 5_000 });
    if (overlay.then) await overlay.then(page);
    const opened = overlay.opened(page);
    await opened.waitFor({ state: "visible", timeout: 5_000 }).catch(() => {
      throw new Error(`${name}: did not open on round ${round}`);
    });
    await page.keyboard.press("Escape");
    await opened.waitFor({ state: "hidden", timeout: 5_000 }).catch(() => {
      throw new Error(`${name}: did not close on round ${round}`);
    });
    if (overlay.focusBack !== false) {
      const back = await trigger.evaluate(
        (node) => node === document.activeElement,
      );
      if (!back)
        throw new Error(
          `${name}: focus did not return to its button on round ${round}`,
        );
    }
  }
  const after = await page.evaluate(
    () => document.querySelectorAll("*").length,
  );
  if (after > before * 1.05 + 20)
    throw new Error(
      `${name}: the page grew from ${before} to ${after} elements after ${times} rounds`,
    );
}

/** The corner card: a read that keeps failing; Try again n times. */
async function repeatCornerCard(page, origin, times) {
  await page.goto(`${origin}/dashboard`, { waitUntil: "domcontentloaded" });
  await settled(page);
  const card = page.getByRole("alert").filter({ hasText: /could not load/ });
  for (let round = 1; round <= times; round += 1) {
    await card.waitFor({ timeout: 5_000 }).catch(() => {
      throw new Error(`corner card: not shown on round ${round}`);
    });
    if (
      (await page
        .getByRole("alert")
        .filter({ hasText: /could not load/ })
        .count()) !== 1
    )
      throw new Error(`corner card: more than one on round ${round}`);
    await page.getByRole("button", { name: /Try again/ }).click();
  }
}

function argument(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : fallback;
}

async function run({ browser, origin, output, only, times }) {
  const results = [];
  const log = (result) => {
    results.push(result);
    console.log(
      `${result.ok ? "ok  " : "FAIL"} ${result.name.padEnd(28)} ${result.variant}${result.ok ? "" : ` :: ${result.problem}`}`,
    );
  };
  const attempt = async (
    name,
    variant,
    { signedIn = true, failing = [] },
    body,
  ) => {
    const [width, height, scheme] = variant;
    const phone = width < 768;
    const context = await browser.newContext({
      viewport: { width, height },
      colorScheme: scheme,
      isMobile: phone,
      hasTouch: phone,
      deviceScaleFactor: 1,
      reducedMotion: "reduce",
      timezoneId: "Asia/Kolkata",
    });
    const api = journeyApi({ signedIn, failing });
    await context.route("**/v1/**", async (request) => {
      const url = new URL(request.request().url());
      const { status, body } = api.respond(
        request.request().method(),
        url.pathname,
        url.search,
      );
      await request.fulfill({ status, json: body });
    });
    // First-call guide: a first visit's card; journeys test the pages.
    await context.addInitScript(() => {
      try {
        localStorage.setItem(
          "sx.guide.off:00000000-0000-4000-8000-000000000001:first-call",
          "1",
        );
      } catch {}
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) =>
      errors.push(String(error.message ?? error).slice(0, 240)),
    );
    const started = Date.now();
    let problem = null;
    try {
      await body(page);
      if (errors.length) problem = `page error: ${errors[0]}`;
      // The report asks the prospect service to read the call (Strike B).
      const unexpected = api.state.writes.filter(
        (write) =>
          !write.startsWith("POST /v1/updates/seen") &&
          !/^POST \/v1\/conversation\/prospects\/calls\/[0-9a-f-]+\/detect$/.test(
            write,
          ),
      );
      if (!problem && unexpected.length)
        problem = `unexpected writes: ${unexpected.slice(0, 3).join(", ")}`;
    } catch (error) {
      problem = String(error.message ?? error).split("\n")[0];
    }
    const label = `${width} ${scheme}`;
    if (problem)
      await page
        .screenshot({
          path: join(
            output,
            `${name.replace(/\W+/g, "-")}-${width}-${scheme}.png`,
          ),
        })
        .catch(() => {});
    await context.close();
    log({
      name,
      variant: label,
      ok: !problem,
      problem,
      ms: Date.now() - started,
    });
  };

  for (const [name, journey] of Object.entries(JOURNEYS)) {
    if (only.length && !only.includes(name)) continue;
    for (const variant of VARIANTS)
      await attempt(name, variant, { signedIn: name !== "sign-in" }, (page) =>
        journey(page, { origin }),
      );
  }
  for (const [name, overlay] of Object.entries(OVERLAYS)) {
    const key = `overlay ${name}`;
    if (only.length && !only.includes(key) && !only.includes("overlays"))
      continue;
    for (const variant of [VARIANTS[0], VARIANTS[3]]) {
      if (overlay.desktopOnly && variant[0] < 768) continue;
      await attempt(`${key} ×${times}`, variant, {}, async (page) => {
        await page.goto(`${origin}/dashboard`, {
          waitUntil: "domcontentloaded",
        });
        await settled(page);
        await repeatOverlay(page, name, overlay, times);
      });
    }
  }
  if (
    !only.length ||
    only.includes("overlays") ||
    only.includes("overlay corner card")
  )
    await attempt(
      `overlay corner card ×${times}`,
      VARIANTS[0],
      { failing: [`${ACQ}/submissions/summary`] },
      (page) => repeatCornerCard(page, origin, times),
    );
  return results;
}

async function main() {
  const origin = argument("origin", "http://127.0.0.1:3016");
  const output = argument("out", "journeys");
  const only = argument("only", "")?.split(",").filter(Boolean);
  const times = Number(argument("repeat", "50"));
  await mkdir(output, { recursive: true });
  const { chromium } = await import("playwright");
  const browser = await chromium.launch();
  const started = Date.now();
  let results = [];
  try {
    results = await run({ browser, origin, output, only, times });
  } finally {
    await browser.close();
  }
  const failures = results.filter((result) => !result.ok);
  await writeFile(
    join(output, "receipts.json"),
    JSON.stringify(
      {
        origin,
        checked: results.length,
        failures: failures.length,
        seconds: Math.round((Date.now() - started) / 1000),
        results,
      },
      null,
      2,
    ),
  );
  const summary = [
    `### Sales Xray release journeys: ${failures.length ? `${failures.length} of ${results.length} failed` : `all ${results.length} passed`} (${Math.round((Date.now() - started) / 1000)} s)`,
    "",
    ...failures.map(
      (result) => `- ${result.name} at ${result.variant}: ${result.problem}`,
    ),
  ].join("\n");
  if (process.env.GITHUB_STEP_SUMMARY)
    await appendFile(process.env.GITHUB_STEP_SUMMARY, `${summary}\n`);
  console.log(`\n${summary}`);
  process.exitCode = failures.length ? 1 : 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
