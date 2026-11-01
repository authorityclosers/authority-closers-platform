// Browser sessions for the robot: one headless Chromium, a few contexts (alias x size x theme x state), signed in
// through persona-qa's proxy at /__as/<alias> (it holds the sandbox passwords; this process never sees them).
// A context's cookies are kept in memory only, never written to disk.
const fs = require("fs");
const path = require("path");
const cfg = require("./config.cjs");
const { INIT } = require("./invariants.cjs");

const { chromium } = require(cfg.PLAYWRIGHT);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// What dev prints that is not a finding: our own blocked calls, third-party analytics, the dev reload socket.
const NOISE = [
  /ERR_NETWORK_CHANGED/, // the robot's own network emulation
  /ERR_INTERNET_DISCONNECTED/,
  /status of (502|503|504)\b/, // the dev API restarting
  /WebSocket connection to .*\/_next\/hmr/, // the dev reload socket
  /ERR_BLOCKED_BY_CLIENT/,
  /ERR_ABORTED/,
  /\[Fast Refresh\]/,
  /\[HMR\]/,
  /Download the React DevTools/,
  /clarity\.ms|google-analytics|googletagmanager|facebook\.net|doubleclick/,
  /webpack-hmr|\.hot-update|__nextjs/,
];
const isNoise = (text) => NOISE.some((re) => re.test(text));

let browser = null;
const cookies = new Map(); // alias -> storageState (memory only)
const live = []; // open tabs, oldest first

let launching = null;
async function ensureBrowser() {
  if (browser && browser.isConnected()) return browser;
  // Several workers ask at once: one launch, shared.
  launching ||= chromium
    .launch({ args: ["--no-sandbox", "--disable-dev-shm-usage"], chromiumSandbox: false })
    .then((b) => {
      browser = b;
      b.on("disconnected", () => {
        if (browser === b) browser = null;
        console.log("browser disconnected (crash or kill); contexts will reopen");
      });
      return b;
    })
    .finally(() => {
      launching = null;
    });
  return launching;
}

function instrument(tab) {
  const { page, log } = tab;
  const watched = (url) => !isNoise(url);
  page.on("request", (r) => {
    if (watched(r.url())) tab.inflight++;
  });
  const done = (r) => {
    if (watched(r.url())) tab.inflight = Math.max(0, tab.inflight - 1);
  };
  page.on("requestfinished", done);
  page.on("requestfailed", (r) => {
    done(r);
    const why = (r.failure() || {}).errorText || "";
    try {
      if (new URL(r.url()).pathname.startsWith("/_next/")) log.nextErrors.push(Date.now());
    } catch {
      /* ignore */
    }
    if (!isNoise(r.url()) && !isNoise(why)) log.failed.push({ url: new URL(r.url()).pathname, why: why.slice(0, 80), method: r.method() });
  });
  page.on("response", (r) => {
    try {
      const u = new URL(r.url());
      if (u.pathname.startsWith("/_next/") && r.status() >= 400) log.nextErrors.push(Date.now());
      if (u.pathname.startsWith("/v1/") && r.status() >= 400) {
        log.http.push({ status: r.status(), method: r.request().method(), path: u.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id") });
      }
    } catch {
      /* ignore */
    }
  });
  page.on("pageerror", (e) => {
    const text = String(e && e.message ? e.message : e).split("\n")[0].slice(0, 220);
    if (!isNoise(text)) log.pageerrors.push(text);
  });
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    let text = m.text().split("\n")[0].slice(0, 220);
    if (/^Failed to load resource/.test(text)) {
      const raw = (m.location() || {}).url || "";
      if (/^blob:/i.test(raw)) {
        // keep the prefix: a revoked blob: URL is the reporter's own preview, not a page address
        text += ` [blob:${raw.replace(/^blob:/i, "").replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id")}]`;
      } else {
        try {
          const where = new URL(raw);
          text += ` [${where.host}${where.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id")}]`;
        } catch {
          /* no location */
        }
      }
    }
    if (!isNoise(text)) log.console.push(text);
  });
  page.on("crash", () => log.pageerrors.push("page crashed"));
}

async function applyState(tab, state) {
  // Only the states a script can make on its own: a slow network and no network. The rest need fixture data.
  if (state === "slow network") {
    const cdp = await tab.context.newCDPSession(tab.page);
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false,
      latency: 400,
      downloadThroughput: (400 * 1024) / 8,
      uploadThroughput: (150 * 1024) / 8,
    });
    tab.cdp = cdp;
  }
}

// Sign in as a fictional person through persona-qa's proxy with a plain HTTP call (no browser needed): the proxy
// answers /__as/<alias> with a redirect and the session cookie. The cookie is kept in memory as a Playwright state.
function parseSetCookie(line) {
  const parts = line.split(";").map((p) => p.trim());
  const eq = parts[0].indexOf("=");
  const cookie = { name: parts[0].slice(0, eq), value: parts[0].slice(eq + 1), domain: "localhost", path: "/", secure: true, httpOnly: false, sameSite: "Lax", expires: -1 };
  for (const attr of parts.slice(1)) {
    const [k, v] = attr.split("=");
    const key = k.toLowerCase();
    if (key === "httponly") cookie.httpOnly = true;
    else if (key === "samesite") cookie.sameSite = /strict/i.test(v) ? "Strict" : /none/i.test(v) ? "None" : "Lax";
    else if (key === "max-age" && Number(v) > 0) cookie.expires = Math.floor(Date.now() / 1000) + Number(v);
    else if (key === "expires" && cookie.expires === -1 && Date.parse(v) > Date.now()) cookie.expires = Math.floor(Date.parse(v) / 1000);
  }
  return cookie;
}

function httpSignIn(alias) {
  const http = require("http");
  const target = new URL(`${cfg.PROXY}/__as/${alias}?next=/robots.txt`);
  return new Promise((resolve, reject) => {
    const req = http.get({ host: target.hostname, port: target.port, path: target.pathname + target.search, timeout: 60000 }, (res) => {
      res.resume();
      const set = [].concat(res.headers["set-cookie"] || []);
      if (res.statusCode >= 400 || !set.length) return reject(new Error(`sign-in as ${alias} failed (HTTP ${res.statusCode})`));
      resolve({ cookies: set.map(parseSetCookie), origins: [] });
    });
    req.on("timeout", () => req.destroy(new Error("sign-in timed out")));
    req.on("error", reject);
  });
}

async function signedIn(alias) {
  if (cookies.has(alias)) return;
  cookies.set(alias, await httpSignIn(alias));
}

// The Cookie header for a signed-in person, for calls made from this process (the reporter). Memory only.
async function cookieHeader(alias) {
  await signedIn(alias);
  return cookies.get(alias).cookies.filter((c) => /localhost/.test(c.domain)).map((c) => `${c.name}=${c.value}`).join("; ");
}

// opts: { alias, device (matrix name), theme, state, locale, fontScale }
async function openTab(opts) {
  const dev = cfg.DEVICES[opts.device];
  if (!dev) throw new Error(`no headless size for "${opts.device}"`);
  await signedIn(opts.alias);
  while (!opts.keep && live.length >= cfg.LIMITS.contexts) {
    const old = live.shift();
    await old.context.close().catch(() => null);
  }
  const b = await ensureBrowser();
  const context = await b.newContext({
    viewport: dev.viewport,
    deviceScaleFactor: dev.deviceScaleFactor,
    isMobile: dev.isMobile,
    hasTouch: dev.hasTouch,
    userAgent: dev.phone ? cfg.ANDROID_UA : undefined,
    colorScheme: opts.theme === "dark" ? "dark" : "light",
    locale: opts.locale || "en-IN",
    timezoneId: "Asia/Kolkata",
    storageState: cookies.get(opts.alias),
    reducedMotion: "reduce",
  });
  await context.addInitScript(INIT);
  // the app ignores the browser's dark setting; its own theme key is what makes it dark (found 1 Nov 2026: every "dark" run before was light)
  if (opts.theme === "dark") await context.addInitScript(`try { localStorage.setItem("sales-xray:theme", "dark"); } catch (e) {}`);
  await context.route(/clarity\.ms|google-analytics|googletagmanager|facebook\.net|doubleclick/, (route) => route.abort());
  const page = await context.newPage();
  const tab = {
    opts,
    dev,
    context,
    page,
    inflight: 0,
    log: { console: [], pageerrors: [], http: [], failed: [], nextErrors: [] },
    mark() {
      return { console: this.log.console.length, pageerrors: this.log.pageerrors.length, http: this.log.http.length, failed: this.log.failed.length };
    },
    since(m) {
      return {
        console: this.log.console.slice(m.console),
        pageerrors: this.log.pageerrors.slice(m.pageerrors),
        http: this.log.http.slice(m.http),
        failed: this.log.failed.slice(m.failed),
      };
    },
  };
  instrument(tab);
  await applyState(tab, opts.state);
  live.push(tab);
  return tab;
}

async function closeTab(tab) {
  const i = live.indexOf(tab);
  if (i >= 0) live.splice(i, 1);
  await tab.context.close().catch(() => null);
}

// The page has loaded and its API calls are quiet for 700 ms (or `max` ms passed). The dev server compiles a
// route on its first visit, so the first wait is longer.
async function settle(tab, max = 25000) {
  const start = Date.now();
  let quiet = 0;
  while (Date.now() - start < max) {
    if (tab.inflight === 0) {
      quiet ||= Date.now();
      if (Date.now() - quiet > 700) return Date.now() - start;
    } else quiet = 0;
    await sleep(100);
  }
  return -1;
}

// First sign-in prompts on the fictional dev accounts: the 18+ terms (owner's yes, 31 Oct 2026, fictional accounts
// only) and "Not now" on the optional prompts. Returns what it did.
async function dismissGates(tab) {
  const did = [];
  const page = tab.page;
  for (let round = 0; round < 4; round++) {
    let acted = false;
    const dialog = page.getByRole("dialog").filter({ visible: true });
    if (await dialog.count()) {
      const box = dialog.first().getByRole("checkbox");
      if ((await box.count()) && /terms|18/i.test((await dialog.first().innerText().catch(() => "")) || "")) {
        const first = box.first();
        if (!(await first.isChecked().catch(() => true))) await first.check().catch(() => null);
        const accept = dialog.first().getByRole("button", { name: /accept|agree|continue/i });
        if (await accept.count()) {
          await accept.first().click().catch(() => null);
          did.push("terms accepted (fictional dev account)");
          acted = true;
        }
      }
    }
    for (const name of ["Not now", "Skip", "Maybe later"]) {
      const later = page.getByRole("button", { name, exact: true }).filter({ visible: true });
      if (await later.count()) {
        await later.first().click().catch(() => null);
        did.push(`"${name}"`);
        acted = true;
      }
    }
    if (!acted) break;
    await sleep(1200);
  }
  return did;
}

async function go(tab, address, { wait = 25000, onLoad } = {}) {
  const url = address.startsWith("http") ? address : `${cfg.PROXY}${address}`;
  try {
    await tab.page.goto(url, { waitUntil: "load", timeout: 120000 });
  } catch (error) {
    return { ok: false, error: String(error).split("\n")[0].slice(0, 160) };
  }
  if (tab.opts.alias === "owner") {
    // the owner belongs to the real AC organisation too: only the sandbox organisations may be touched
    await settle(tab, 8000);
    const label = await tab.page.evaluate(() => (document.querySelector('[aria-label*="orkspace:"]') || {}).ariaLabel || "").catch(() => "");
    if (!/sandbox/i.test(label)) {
      await tab.page.goto("about:blank").catch(() => null);
      return { ok: false, error: `the owner session is in "${String(label).slice(0, 60) || "an unknown workspace"}", not a sandbox organisation: not used` };
    }
  }
  if (onLoad) await onLoad().catch(() => null);
  const waited = await settle(tab, wait);
  const gates = ["aditya", "vikas"].includes(tab.opts.alias) ? [] : await dismissGates(tab); // those two keep their first sign-in untouched
  if (gates.length) await settle(tab, 8000);
  return { ok: true, waited, gates };
}

async function shutdown() {
  for (const tab of [...live]) await closeTab(tab);
  if (browser) await browser.close().catch(() => null);
  browser = null;
}

module.exports = { cookieHeader, openTab, closeTab, go, settle, dismissGates, shutdown, isNoise, sleep };
