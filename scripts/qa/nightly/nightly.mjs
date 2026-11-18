// Sales Xray signed-in nightly on production (owner approval relayed 19 Oct: the
// existing QA test account, one analysis a night, calls kept out of real metrics).
// Runs on ac against production's edge on loopback (127.0.0.1:8080), so Cloudflare's
// bot check is not in the path: the browser still asks for
// https://salesxray.authorityclosers.com and every such request is answered from
// loopback with the public Host header.
//
// The one analysis uploads the bundled canary recording (sales_call_v1.wav), which
// recording_is_canary() keeps out of usage, recordings, review, gold and the library.
// Guards: QA identity only, one analysis per IST day (ledger claimed before upload),
// a quote over ₹450 stops before accepting. Credentials come from the environment and
// are never printed; an error body is reduced to type/loc/msg (a 422 echoes input).
//
//   DRY=1 node nightly.mjs   sign in and capture screens, no analysis
//
// The repo copy is scripts/qa/nightly/ (this file and run.sh); the running copy is /home/acdev/qa-nightly on ac
// (unit ac-qa-nightly, 21:00 UTC). Change both.
import { createHash, randomUUID } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright-core";

const HOST = "salesxray.authorityclosers.com";
const ORIGIN = `https://${HOST}`;
const EDGE = process.env.SX_EDGE || "http://127.0.0.1:8080";
const ROOT = "/home/acdev/qa-nightly";
const FIXTURE = process.env.SX_FIXTURE;
const FIXTURE_SHA256 = "78cb1194e987db6b8d06d0aa2a4d2e66d21bbdf0c3de6960e4e26da36ed207af";
const MAX_QUOTE_PAISE = 45_000;
const PREFIX = "/v1/conversation/acquisition";
const DRY = process.env.DRY === "1";
const CHROME =
  process.env.SX_CHROME || "/home/acdev/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell";

const day = new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10); // IST date
const stamp = new Date().toISOString().replace(/[:.]/g, "-");
const out = `${ROOT}/runs/${stamp}${DRY ? "-dry" : ""}`;
mkdirSync(out, { recursive: true });
const result = { schema: "ac.sales-xray.qa-nightly/1", day, dry: DRY, steps: [], ok: false };
const step = (name, ok, extra = {}) => {
  result.steps.push({ name, ok, ...extra });
  console.log(`${ok ? "ok" : "FAIL"} ${name}${extra.note ? ` (${extra.note})` : ""}`);
};
const finish = () => {
  result.ok = result.steps.length > 0 && result.steps.every((s) => s.ok);
  writeFileSync(`${out}/result.json`, JSON.stringify(result, null, 2));
  console.log(`result ${result.ok ? "PASS" : "FAIL"} -> ${out}`);
  process.exit(result.ok ? 0 : 1);
};

const email = process.env.AC_SMOKE_EMAIL || "";
const password = process.env.AC_SMOKE_PASSWORD || "";
if (!email.endsWith("+ac-qa-production@authorityclosers.com") || !password) {
  step("qa identity", false, { note: "not the production QA account" });
  finish();
}

const ledger = `${ROOT}/ledger.jsonl`;
let wav = null;
if (!DRY) {
  const used = existsSync(ledger)
    ? readFileSync(ledger, "utf8").split("\n").filter(Boolean).map((line) => JSON.parse(line))
    : [];
  if (used.some((entry) => entry.day === day)) {
    step("one analysis per night", false, { note: `already used on ${day}` });
    finish();
  }
  wav = readFileSync(FIXTURE);
  if (createHash("sha256").update(wav).digest("hex") !== FIXTURE_SHA256) {
    step("canary recording", false, { note: "fixture changed" });
    finish();
  }
}

const browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
});
await context.route(
  (url) => url.host === HOST,
  async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    try {
      const headers = { ...(await request.allHeaders()), host: HOST, "x-forwarded-proto": "https" };
      const response = await route.fetch({
        url: EDGE + url.pathname + url.search,
        headers,
        maxRedirects: 0,
        timeout: 60000,
      });
      await route.fulfill({ response });
    } catch {
      await route.abort().catch(() => {});
    }
  },
);
const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error.message).slice(0, 160)));

const BLOCKERS = [
  [/updated our terms/i, "the updated-terms box covers the screen"],
  [/Leads work inside an organisation/i, "the QA account has no organisation"],
  [/Performing security verification|Verify you are human/i, "Cloudflare's bot check"],
];
async function shot(name) {
  await page.screenshot({ path: `${out}/${name}.png` }).catch(() => {});
}
// The QA account lives in a TEST organisation (QA stage 1, owner 18 Nov 2026), but a fresh sign-in can open its
// personal workspace, where Leads says "Leads work inside an organisation" beside the app's own "Switch to ..."
// button. Press it, as a person would, and read the page again. Only a TEST organisation is ever entered.
async function intoOrganisation(text) {
  if (!/Leads work inside an organisation/i.test(text)) return text;
  const go = page.getByRole("button", { name: /^Switch to TEST\b/ }).first();
  if (!(await go.count().catch(() => 0))) return text;
  await go.click().catch(() => {});
  let now = text;
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(1000);
    now = await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
    if (now && !/Leads work inside an organisation/i.test(now) && /lead/i.test(now)) break;
  }
  await page.waitForTimeout(1500);
  return page.locator("body").innerText({ timeout: 5000 }).catch(() => now);
}
async function open(name, path, words) {
  try {
    await page.goto(ORIGIN + path, { waitUntil: "domcontentloaded", timeout: 60000 });
    let text = "";
    for (let i = 0; i < 30 && !words.test(text); i++) {
      await page.waitForTimeout(1000);
      text = await page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
    }
    await page.waitForTimeout(1500);
    text = await page.locator("body").innerText({ timeout: 5000 }).catch(() => text);
    text = await intoOrganisation(text);
    await shot(name);
    // Screens a person would be stuck behind count as failures, not passes.
    const blocked = BLOCKERS.find(([pattern]) => pattern.test(text));
    const ok = words.test(text) && !blocked;
    step(name, ok, ok ? {} : { note: blocked ? blocked[1] : "key words missing" });
    return ok;
  } catch (error) {
    await shot(`${name}-FAILED`);
    step(name, false, { note: String(error.message).split("\n")[0].slice(0, 120) });
    return false;
  }
}
// API calls run in the page (its cookies, its origin). Only status and a reduced body
// come back; an error body keeps only type/loc/msg.
async function api(method, path, { json, headers = {}, b64 } = {}) {
  return page.evaluate(
    async ({ method, path, json, headers, b64 }) => {
      const init = { method, headers: { ...headers }, credentials: "include" };
      if (json !== undefined) {
        init.headers["content-type"] = "application/json";
        init.body = JSON.stringify(json);
      }
      if (b64) init.body = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const response = await fetch(path, init);
      let body = null;
      try {
        body = await response.json();
      } catch {}
      if (!response.ok) {
        const detail = Array.isArray(body?.detail)
          ? body.detail.map((d) => ({ type: d.type, loc: d.loc, msg: d.msg }))
          : typeof body?.detail === "string"
            ? body.detail.slice(0, 120)
            : null;
        return { status: response.status, error: detail };
      }
      return { status: response.status, body };
    },
    { method, path, json, headers, b64 },
  );
}

try {
  await open("signed-out", "/dashboard", /sign in|email|continue/i);
  const login = await api("POST", "/v1/auth/password/login", { json: { email, password } });
  step(
    "sign in",
    login.status < 400,
    login.status < 400 ? {} : { note: `HTTP ${login.status} ${JSON.stringify(login.error)}` },
  );
  if (login.status >= 400) throw new Error("stop");
  await open("calls", "/analysis/calls", /call/i);
  await open("new-analysis", "/analysis/new", /upload|record|drop|analy/i);
  await open("leads", "/leads", /lead/i);

  if (!DRY) {
    const policy = await api("GET", `${PREFIX}/upload-policy`);
    if (policy.status >= 400) {
      step("upload policy", false, { note: `HTTP ${policy.status}` });
      throw new Error("stop");
    }
    const submission = randomUUID();
    appendFileSync(ledger, JSON.stringify({ day, at: new Date().toISOString(), submission }) + "\n");
    result.submission = submission;
    const path = `${PREFIX}/submissions/${submission}`;
    const uploaded = await api("PUT", `${path}/source`, {
      b64: wav.toString("base64"),
      headers: {
        "content-type": "application/octet-stream",
        "x-source-sha256": FIXTURE_SHA256,
        "x-upload-policy": policy.body.policy_sha256,
        "x-upload-consent": "accepted",
      },
    });
    step("upload canary recording", uploaded.status < 400, { note: `HTTP ${uploaded.status}` });
    if (uploaded.status >= 400) throw new Error("stop");
    let accepted = false;
    let report = false;
    const deadline = Date.now() + 20 * 60e3;
    while (Date.now() < deadline) {
      const progress = (await api("GET", path)).body || {};
      if (progress.has_report) {
        report = true;
        break;
      }
      if (
        ["failed", "cancelled"].includes(progress.local_state) ||
        ["held", "failed", "cancelled"].includes(progress.state) ||
        progress.execution_hold
      ) {
        step("analysis", false, { note: `state ${progress.state}/${progress.local_state}` });
        throw new Error("stop");
      }
      if (progress.local_state === "completed" && !accepted) {
        const quote = await api("POST", `${path}/plan/quote`, {
          headers: { "idempotency-key": `qa-nightly-quote:${submission}` },
        });
        const cost = quote.body?.max_cost_paise;
        if (quote.status >= 400 || typeof cost !== "number" || cost > MAX_QUOTE_PAISE) {
          step("quote within cap", false, { note: `HTTP ${quote.status}, max ${cost} paise` });
          throw new Error("stop");
        }
        step("quote within cap", true, { note: `max ${cost} paise` });
        const accept = await api("POST", `${path}/plan`, {
          headers: { "idempotency-key": `qa-nightly-accept:${submission}` },
          json: {
            plan_id: quote.body.id,
            plan_fingerprint: quote.body.plan_fingerprint,
            privacy_revision: quote.body.privacy_revision,
            accepted: true,
          },
        });
        step("accept plan", accept.status < 400, { note: `HTTP ${accept.status}` });
        if (accept.status >= 400) throw new Error("stop");
        accepted = true;
      }
      await page.waitForTimeout(5000);
    }
    step("report ready", report, report ? {} : { note: "not ready in 20 min" });
    if (report) {
      await open("call", `/analysis/calls/${submission}`, /report|summary|prospect|coach/i);
      for (const tab of ["Report", "Prospect", "Coaching"]) {
        const target = page
          .getByRole("tab", { name: tab })
          .or(page.getByRole("button", { name: tab, exact: true }))
          .first();
        if (await target.count()) {
          await target.click().catch(() => {});
          await page.waitForTimeout(2500);
          await shot(`call-${tab.toLowerCase()}`);
          step(`call ${tab}`, true);
        } else {
          await shot(`call-${tab.toLowerCase()}-missing`);
          step(`call ${tab}`, false, { note: "tab not found" });
        }
      }
      await open("calls-after", "/analysis/calls", /call/i);
    }
  }
} catch (error) {
  if (String(error.message) !== "stop") {
    step("run", false, { note: String(error.message).split("\n")[0].slice(0, 120) });
  }
} finally {
  result.page_errors = [...new Set(pageErrors)].slice(0, 5);
  await browser.close();
}
finish();
