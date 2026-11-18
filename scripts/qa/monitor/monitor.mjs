// The production monitor (QA system stage 1, step 8a; owner, 18 Nov 2026: "Yes, start stage 1"). Every 15 minutes
// the QA account (a fictional person in the TEST · Sahyadri Homes workspace, never a real seller) opens the main
// Sales X-Ray screens on production and runs the checks a script can be certain of: the screen drew its own words,
// nothing a person would be stuck behind, no junk ("undefined", "NaN", "Invalid Date"), no sideways scroll at
// 360 px, no uncaught error, no 5xx from the API. No model, no tokens.
//
// READ-ONLY. The browser may only read: every request that is not a GET is refused before it leaves, except the two
// the QA account's own session needs: its sign-in (POST /v1/auth/password/login, at most once a day: the session is
// kept in state/session.json, mode 0600) and choosing its TEST workspace for that session (/v1/context). It adds,
// edits, calls, uploads and analyses nothing; the nightly check (scripts/qa/nightly) does the one analysis a night.
//
// It runs on ac against production's edge on loopback (127.0.0.1:8080), as the nightly does, so Cloudflare's bot
// check is not in the path. Credentials come from the environment and are never printed.
//
//   node scripts/qa/monitor/monitor.mjs            one run; exit 0 green, 1 red
//
// Output in $SX_MONITOR_ROOT (default /home/acdev/qa-monitor): state/status.json (the latest run),
// state/history.jsonl (one line a run, the newest 3,000 kept), state/RED.md while the same failure has shown twice
// in a row (the rule for a top-priority card; removed on the next green), and runs/<time>/ with pictures of a red
// run only (the newest 30 kept).
import {
  appendFileSync,
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { pathToFileURL } from "node:url";
import { isJunk } from "../../ci/wb_readability_lib.mjs";

export const HOST = process.env.SX_HOST || "salesxray.authorityclosers.com";
const ORIGIN = `https://${HOST}`;
const EDGE = process.env.SX_EDGE || "http://127.0.0.1:8080";
const ROOT = process.env.SX_MONITOR_ROOT || "/home/acdev/qa-monitor";
const CHROME =
  process.env.SX_CHROME ||
  "/home/acdev/.cache/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell";
const WIDTH = 360;

/** The screens, in order. Leads comes first: it is where the QA account steps into its TEST workspace. */
export const SCREENS = [
  { name: "leads", path: "/leads", words: /lead/i },
  { name: "home", path: "/dashboard", words: /lead|call|today|home/i },
  { name: "calls", path: "/analysis/calls", words: /call/i },
  { name: "new-analysis", path: "/analysis/new", words: /upload|record|drop|analy/i },
];

/** Screens a person would be stuck behind count as failures, not passes. */
export const BLOCKERS = [
  [/updated our terms/i, "the updated-terms box covers the screen"],
  [/Leads work inside an organisation/i, "the QA account has no organisation"],
  [/Performing security verification|Verify you are human/i, "Cloudflare's bot check"],
  [/Something went wrong|Application error|This page could not be found/i, "an error page"],
];

/** The only requests that may change anything: the QA account's own sign-in and its session's workspace. */
export const ALLOWED_WRITES = ["/v1/auth/password/login", "/v1/context"];
export const mayLeave = (method, pathname) =>
  ["GET", "HEAD", "OPTIONS"].includes(method) || ALLOWED_WRITES.includes(pathname);

/** The QA account only: the production QA alias on the company domain. */
export const isQaAccount = (email) => /\+ac-qa-production@authorityclosers\.com$/.test(String(email ?? ""));

/** One screen's verdict from what it showed. */
export function judge(screen, { text, overflow, errors, serverErrors }) {
  const blocked = BLOCKERS.find(([pattern]) => pattern.test(text));
  if (blocked) return blocked[1];
  if (!screen.words.test(text)) return "key words missing";
  const junk = text.split("\n").find((line) => isJunk(line));
  if (junk !== undefined) return "junk on screen";
  if (overflow > 1) return `scrolls sideways by ${Math.round(overflow)} px`;
  if (errors.length) return `uncaught error: ${errors[0]}`;
  if (serverErrors.length) return `API ${serverErrors[0]}`;
  return null;
}

/** What the run's failures are called when comparing one run with the last ("the same reason twice"). */
export const reasonOf = (steps) =>
  steps
    .filter((step) => !step.ok)
    .map((step) => `${step.name}: ${String(step.note ?? "").replace(/\d+/g, "N")}`)
    .join("; ");

/** RED.md's words, or null when no card is due: the same reason, two runs in a row. */
export function redNote(previous, current) {
  if (current.ok || !previous || previous.ok) return null;
  if (reasonOf(previous.steps) !== reasonOf(current.steps)) return null;
  return [
    "# Sales X-Ray production monitor: RED twice in a row",
    "",
    `First seen ${previous.at}, again ${current.at}.`,
    "",
    ...current.steps.filter((step) => !step.ok).map((step) => `- ${step.name}: ${step.note}`),
    "",
    "The QA account only reads. This file goes away on the next green run.",
    "",
  ].join("\n");
}

/** The QA account's session, kept for the next run in a file only acdev can read. */
async function keepSession(context, file) {
  await context.storageState({ path: file });
  chmodSync(file, 0o600);
}

async function playwright() {
  try {
    return (await import("playwright-core")).chromium;
  } catch {
    return (await import("playwright")).chromium;
  }
}

async function main() {
  const at = new Date().toISOString();
  const stamp = at.replace(/[:.]/g, "-");
  mkdirSync(`${ROOT}/state`, { recursive: true });
  const result = { schema: "ac.sales-xray.qa-monitor/1", at, host: HOST, steps: [], refused_writes: 0, ok: false };
  const step = (name, ok, extra = {}) => {
    result.steps.push({ name, ok, ...extra });
    console.log(`${ok ? "ok" : "FAIL"} ${name}${extra.note ? ` (${extra.note})` : ""}`);
  };
  const email = process.env.AC_SMOKE_EMAIL || "";
  const password = process.env.AC_SMOKE_PASSWORD || "";
  const sessionFile = `${ROOT}/state/session.json`;
  let browser;
  let page;
  const shots = [];
  try {
    if (!isQaAccount(email) || !password) {
      step("qa identity", false, { note: "not the production QA account" });
      throw new Error("stop");
    }
    const chromium = await playwright();
    browser = await chromium.launch({ executablePath: CHROME, args: ["--no-sandbox"] });
    const context = await browser.newContext({
      viewport: { width: WIDTH, height: 780 },
      isMobile: true,
      hasTouch: true,
      ...(existsSync(sessionFile) ? { storageState: sessionFile } : {}),
    });
    const serverErrors = [];
    await context.route(
      (url) => url.host === HOST,
      async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (!mayLeave(request.method(), url.pathname)) {
          result.refused_writes += 1;
          return route.abort().catch(() => {});
        }
        try {
          const headers = { ...(await request.allHeaders()), host: HOST, "x-forwarded-proto": "https" };
          const response = await route.fetch({
            url: EDGE + url.pathname + url.search,
            headers,
            maxRedirects: 0,
            timeout: 60000,
          });
          if (response.status() >= 500 && url.pathname.startsWith("/v1/"))
            serverErrors.push(`${response.status()} on ${url.pathname.replace(/[0-9a-f-]{36}/g, ":id")}`);
          await route.fulfill({ response });
        } catch {
          await route.abort().catch(() => {});
        }
      },
    );
    // Anything off the app's own host stays inside: the monitor talks to production's edge only.
    await context.route((url) => url.host !== HOST, (route) => route.abort().catch(() => {}));
    page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error.message).split("\n")[0].slice(0, 100)));
    const read = () => page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
    const api = (method, path, json) =>
      page.evaluate(
        async ({ method, path, json }) => {
          const init = { method, credentials: "include", headers: {} };
          if (json !== undefined) {
            init.headers["content-type"] = "application/json";
            init.body = JSON.stringify(json);
          }
          const response = await fetch(path, init);
          return response.status;
        },
        { method, path, json },
      );

    await page.goto(`${ORIGIN}/dashboard`, { waitUntil: "domcontentloaded", timeout: 60000 });
    // The kept session, or one sign-in (the QA account's own).
    let signedIn = (await api("GET", "/v1/me/workspaces")) === 200;
    if (!signedIn) {
      const status = await api("POST", "/v1/auth/password/login", { email, password });
      signedIn = status < 400;
      step("sign in", signedIn, signedIn ? {} : { note: `HTTP ${status}` });
      if (!signedIn) throw new Error("stop");
      await keepSession(context, sessionFile);
    } else step("session kept", true);

    for (const screen of SCREENS) {
      errors.length = 0;
      serverErrors.length = 0;
      const started = Date.now();
      let note = null;
      try {
        await page.goto(ORIGIN + screen.path, { waitUntil: "domcontentloaded", timeout: 60000 });
        let text = "";
        for (let i = 0; i < 30 && !screen.words.test(text); i++) {
          await page.waitForTimeout(1000);
          text = await read();
        }
        await page.waitForTimeout(1500);
        text = await read();
        if (/Leads work inside an organisation/i.test(text)) {
          // Its personal workspace: the app's own "Switch to ..." button, as a person would. TEST workspaces only.
          const go = page.getByRole("button", { name: /^Switch to TEST\b/ }).first();
          if (await go.count().catch(() => 0)) {
            await go.click().catch(() => {});
            for (let i = 0; i < 30; i++) {
              await page.waitForTimeout(1000);
              text = await read();
              if (text && !/Leads work inside an organisation/i.test(text) && screen.words.test(text)) break;
            }
            await page.waitForTimeout(1500);
            text = await read();
            await keepSession(context, sessionFile);
          }
        }
        const overflow = await page
          .evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
          .catch(() => 0);
        note = judge(screen, { text, overflow, errors: [...errors], serverErrors: [...serverErrors] });
      } catch (error) {
        note = String(error.message).split("\n")[0].slice(0, 120);
      }
      const seconds = Math.round((Date.now() - started) / 100) / 10;
      step(screen.name, !note, note ? { note, seconds } : { seconds });
      if (note) shots.push(screen.name);
      if (note) {
        mkdirSync(`${ROOT}/runs/${stamp}`, { recursive: true });
        await page.screenshot({ path: `${ROOT}/runs/${stamp}/${screen.name}.png`, scale: "css" }).catch(() => {});
      }
    }
  } catch (error) {
    if (String(error.message) !== "stop")
      step("run", false, { note: String(error.message).split("\n")[0].slice(0, 120) });
  } finally {
    await browser?.close().catch(() => {});
  }
  result.ok = result.steps.length > 0 && result.steps.every((s) => s.ok);

  // The record, and the "red twice for the same reason" note.
  const statusFile = `${ROOT}/state/status.json`;
  let previous = null;
  try {
    previous = JSON.parse(readFileSync(statusFile, "utf8"));
  } catch {
    /* the first run */
  }
  writeFileSync(statusFile, JSON.stringify(result, null, 2));
  const historyFile = `${ROOT}/state/history.jsonl`;
  appendFileSync(historyFile, JSON.stringify({ at, ok: result.ok, reason: reasonOf(result.steps) }) + "\n");
  const history = readFileSync(historyFile, "utf8").split("\n").filter(Boolean);
  if (history.length > 3000) writeFileSync(historyFile, history.slice(-3000).join("\n") + "\n");
  const note = redNote(previous, result);
  if (note) writeFileSync(`${ROOT}/state/RED.md`, note);
  else if (result.ok) rmSync(`${ROOT}/state/RED.md`, { force: true });
  if (existsSync(`${ROOT}/runs`)) {
    const kept = readdirSync(`${ROOT}/runs`).sort();
    for (const old of kept.slice(0, Math.max(0, kept.length - 30)))
      rmSync(`${ROOT}/runs/${old}`, { recursive: true, force: true });
  }
  console.log(`result ${result.ok ? "GREEN" : "RED"}${note ? " (twice in a row: state/RED.md)" : ""}`);
  return result.ok ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) process.exit(await main());
