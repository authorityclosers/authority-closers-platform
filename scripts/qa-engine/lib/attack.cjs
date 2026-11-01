// State attacks (orchestrator's order, 31 Oct 2026): put every page into the states real people meet and see whether it
// holds. Eight families, each judged by what is on screen and in the network log, never by AI:
//   fault     a 500 on each /v1 call in turn; a 429, a 10 s delay and an empty 200 on all calls at once. Each must give a
//             calm message or Retry: never a blank page, a stuck spinner, a crash, raw error words or a false "nothing here".
//   3g        every /v1 answer takes the time Fast 3G gives it (1.6 Mbit, 560 ms): the outline shows while it waits, no layout
//             shift over 0.1, no false "no leads" while the call is still in flight. (Dev's unminified bundles cannot load on
//             3G in useful time, so the delay is put on the API calls; the full-bundle case needs the staging build.)
//   extremes  API answers rewritten in flight: 1,000 rows, 300-character names, emoji, Hindi and Marathi, zero-width
//             characters, 13-digit numbers. Judged against the same page without them.
//   zoom      text 130 % and 200 % (every text element's font size scaled, the way Android's font size does).
//   keyboard  Tab through the page: focus trap, invisible focus, focus under a bar, unreachable and click-only controls.
//   dark      the app's own dark theme: white islands, white fields, contrast that fails only in dark.
//   history   Back, Forward and refresh with text typed in every sheet and form: no lost work without a warning.
//   double    every Save and Send pressed twice in 120 ms: one write only, counted from the network log.
// Read-only like the walks: every write is held 1.2 s and refused (lib/sim.cjs holdWrites), and any other same-origin write
// is refused outright. A cell is one page x size x role x family; the least recently run cell goes next (state/attack-cells.json).
// One finding per page, rule and viewport, with the first picture of it.
const fs = require("fs");
const path = require("path");
const cfg = require("./config.cjs");
const session = require("./session.cjs");
const report = require("./report.cjs");
const inv = require("./invariants.cjs");
const { headroom, sleep } = require("./guard.cjs");
const { controls } = require("./crawler.cjs");
const { rebuilding, waitOutRebuild } = require("./rebuild.cjs");
const clickmap = require("./clickmap.cjs");
const sim = require("./sim.cjs");

const log = (text) => console.log(`${new Date().toISOString().slice(11, 19)} ${text}`);

const FAMILIES = ["fault", "3g", "extremes", "zoom", "keyboard", "dark", "history", "double"];
const SIZES = ["360 px", "390 px", "1440"];
const PAGES = {
  seller: [
    "/dashboard", "/leads", "/leads?view=follow_ups", "/leads?view=all", "/leads?tab=tasks", "/leads?side=cold", "/leads?view=all&lead={lead}",
    "/leads/notes", "/analysis/calls", "/analysis/new", "/performance", "/coaching", "/reports", "/account", "/settings/selling", "/settings/notifications",
  ],
  owner: [
    "/dashboard", "/performance", "/performance/sellers", "/reports", "/organisation", "/organisation?tab=members",
    "/organisation?tab=leads&part=stages", "/coaching?view=team", "/account",
  ],
};
const SELLERS = ["priya", "rohan", "farah", "karan", "pooja"];
const OWNER_COOKIE = "/tmp/pw/owner-cookie.txt";

// ---- state ----------------------------------------------------------------------------------------------------------
const FILE = path.join(cfg.STATE, "attack-cells.json");
let state = { cells: {}, flows: {}, cursor: {}, since: new Date().toISOString() };
try {
  state = { ...state, ...JSON.parse(fs.readFileSync(FILE, "utf8")) };
} catch {
  /* first run */
}
const save = () => fs.writeFileSync(FILE, JSON.stringify(state));
let aliasTurn = Math.floor(Math.random() * 100);

function ownerAvailable() {
  try {
    return Date.now() - fs.statSync(OWNER_COOKIE).mtimeMs < 8 * 3600 * 1000;
  } catch {
    return false;
  }
}
const keyOf = (c) => `${c.role}|${c.route}|${c.size}|${c.family}`;

// families switched off without a restart: names in state/attack-off.txt
function offFamilies() {
  try {
    return new Set(fs.readFileSync(path.join(cfg.STATE, "attack-off.txt"), "utf8").split(/[\s,]+/).filter(Boolean));
  } catch {
    return new Set();
  }
}

function allCells(filter = {}) {
  const out = [];
  const off = filter.family ? new Set() : offFamilies();
  for (const role of ["seller", "owner"]) {
    if (filter.role && filter.role !== role) continue;
    if (!filter.role && role === "owner" && !ownerAvailable()) continue;
    for (const route of PAGES[role]) {
      if (filter.page && filter.page !== route) continue;
      for (const size of SIZES) {
        if (filter.size && filter.size !== size) continue;
        for (const family of FAMILIES) {
          if (filter.family && filter.family !== family) continue;
          if (off.has(family)) continue;
          out.push({ role, route, size, family });
        }
      }
    }
  }
  return out;
}

function pickCell(filter) {
  let best = null;
  let bestScore = Infinity;
  for (const c of allCells(filter)) {
    const done = state.cells[keyOf(c)];
    const score = (done ? done.at : 0) + Math.random() * 1000;
    if (score < bestScore) {
      best = c;
      bestScore = score;
    }
  }
  return best;
}

// Lines for the digest: cells run since the last digest and how much of the grid has been covered.
function digestLine(sinceIso) {
  const since = Date.parse(sinceIso) || 0;
  const recent = {};
  let n = 0;
  for (const [k, v] of Object.entries(state.cells)) {
    if (v.at >= since) {
      const family = k.split("|")[3];
      recent[family] = (recent[family] || 0) + 1;
      n++;
    }
  }
  const sellers = allCells({ role: "seller" });
  const covered = sellers.filter((c) => state.cells[keyOf(c)]).length;
  const owners = ownerAvailable() ? allCells({ role: "owner" }) : [];
  const ownerCovered = owners.filter((c) => state.cells[keyOf(c)]).length;
  const by = Object.entries(recent).map(([k, v]) => `${k} ${v}`).join(", ") || "none";
  return `State attacks: ${n} cells run since the last digest (${by}); grid covered once: seller ${covered}/${sellers.length}${owners.length ? `, owner ${ownerCovered}/${owners.length}` : ", owner side waiting for a fresh owner session"}.`;
}

// ---- helpers ------------------------------------------------------------------------------------------------------
const tpl = (p) => p.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id").replace(/\/\d+(?=\/|$)/g, "/:n");
const stripQ = (s) => String(s || "").replace(/"[^"]*"/g, '""');
const SKIP_CALL = /telemetry|analytics|\/events\b|metrics|heartbeat|\/ping\b|\/health|beacon|presence/i;
// extremes rewrite lists of leads, notes, calls and chats; who the person is, which workspaces they have, the branding and the badges stay as they are (a thousand workspaces is not a case)
const SKIP_DATA = /^\/v1\/(me\/|app\/|organisation|people\/characters|sales-xray\/review\/badge|lead-desk\/badge)/;
const EXPECTED = /Failed to fetch|NetworkError|Load failed|AbortError|ERR_/i;
const CODE_BUG = /TypeError|ReferenceError|RangeError|Cannot read|is not a function|is not iterable|undefined/i;
const FRIENDLY = /couldn['’]?t|could not|can['’]?t|unable|try again|retry|something went wrong|didn['’]?t load|did not load|not available|offline|too many|problem|failed|went wrong/i;
const TECH = /\b(?:500|429|502|503)\b|internal server error|too many requests|\b(?:TypeError|SyntaxError|ReferenceError)\b|unexpected token|\bJSON\b|failed to fetch|networkerror|\bundefined\b|\bNaN\b|\[object|"detail"/i;
const EMPTY = /\b(?:no|nothing|haven['’]t|have no|none)\b[^.]{0,40}\b(?:leads?|calls?|tasks?|follow-?ups?|reports?|notes?|results?|activity)\b/i;

const FACTS = () => {
  const visible = (el) => el.checkVisibility && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
  const main = document.querySelector("main") || document.body;
  const text = (main.innerText || "").replace(/\s+/g, " ").trim();
  const loadingEls = [...document.querySelectorAll('[role=progressbar],[aria-busy="true"],[class*="skeleton" i],[class*="spinner" i],[class*="shimmer" i]')].filter(visible);
  const loading = loadingEls.length;
  const loadingIn = loadingEls.slice(0, 3).map((e) => ({ s: window.__qaSem ? window.__qaSem(e) : e.tagName, main: main.contains(e) }));
  const BITS = /couldn['’]?t|could not|can['’]?t|unable|try again|retry|something went wrong|didn['’]?t load|did not load|not available|offline|too many|problem|failed|went wrong|\b(?:500|429|502|503)\b|internal server error|too many requests|TypeError|SyntaxError|unexpected token|JSON|failed to fetch|networkerror|undefined|\bNaN\b|\[object|"detail"/i;
  const bits = [];
  for (const el of document.querySelectorAll("p,span,div,li,h1,h2,h3,h4,button,a,[role=alert],[role=status]")) {
    if (bits.length >= 8) break;
    if (!visible(el)) continue;
    const t = (el.innerText || "").replace(/\s+/g, " ").trim();
    if (t.length < 3 || t.length > 260 || !BITS.test(t)) continue;
    if ([...el.children].some((c) => (c.innerText || "").trim().length >= 3 && BITS.test(c.innerText || ""))) continue;
    if (!bits.includes(t.slice(0, 160))) bits.push(t.slice(0, 160));
  }
  const retry = [...document.querySelectorAll("button,a,[role=button]")].filter(visible).some((e) => /^(retry|try again|reload|refresh|tap to retry)\b/i.test((e.getAttribute("aria-label") || e.textContent || "").trim()));
  const portal = document.querySelector("nextjs-portal");
  const shadow = portal && portal.shadowRoot;
  const overlayText = shadow ? [...shadow.children].filter((e) => e.tagName !== "STYLE").map((e) => e.textContent || "").join(" ").replace(/\s+/g, " ") : "";
  return { textLength: text.length, text: text.slice(0, 3000), loading, loadingIn, bits, retry, overlay: /unhandled runtime error|application error/i.test(overlayText) ? overlayText.slice(0, 160) : "", theme: document.documentElement.getAttribute("data-theme") || "" };
};

const SHIFT_INIT = `(() => { const s = (window.__qaShifts = []); try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput && e.value > 0.002) s.push({ v: e.value, t: Math.round(e.startTime), src: (e.sources || []).slice(0, 3).map((x) => { try { return x.node && x.node.nodeType === 1 && window.__qaSem ? window.__qaSem(x.node) : "(text)"; } catch (err) { return "?"; } }) }); }).observe({ type: "layout-shift", buffered: true }); } catch (e) {} })();`;

async function facts(tab) {
  return tab.page.evaluate(FACTS).catch(() => ({ textLength: 0, text: "", loading: 0, bits: [], retry: false, overlay: "", theme: "", unreadable: true }));
}

// Writes are refused. lib/sim.cjs holds /v1 writes 1.2 s and aborts them (so a double press can be counted); any other
// same-origin write (a server action, an API route) is aborted at once.
async function prepare(tab) {
  await tab.context.route("**/*", async (route) => {
    const req = route.request();
    const m = req.method();
    if (m === "GET" || m === "HEAD" || m === "OPTIONS") return route.fallback();
    let u;
    try {
      u = new URL(req.url());
    } catch {
      return route.fallback();
    }
    if (u.origin !== new URL(cfg.PROXY).origin || u.pathname.startsWith("/_next/") || u.pathname.startsWith("/__")) return route.fallback();
    tab.stray = (tab.stray || 0) + 1;
    return route.abort("blockedbyclient");
  });
  await sim.holdWrites(tab);
  await tab.context.addInitScript(SHIFT_INIT);
  tab.api = { inflight: 0 };
  tab.page.on("request", (r) => {
    if (r.url().includes("/v1/")) tab.api.inflight++;
  });
  const done = (r) => {
    if (r.url().includes("/v1/")) tab.api.inflight = Math.max(0, tab.api.inflight - 1);
  };
  tab.page.on("requestfinished", done);
  tab.page.on("requestfailed", done);
}

function trackCalls(tab) {
  const seen = new Map();
  const on = (res) => {
    try {
      if (res.request().method() !== "GET") return;
      const u = new URL(res.url());
      if (!u.pathname.startsWith("/v1/") || SKIP_CALL.test(u.pathname)) return;
      const p = tpl(u.pathname);
      if (!seen.has(p)) seen.set(p, res.status());
    } catch {
      /* ignore */
    }
  };
  tab.page.on("response", on);
  return { seen, stop: () => tab.page.off("response", on) };
}

async function shotOf(tab) {
  try {
    return await tab.page.screenshot({ type: "png", timeout: 15000 });
  } catch {
    return null;
  }
}

// ---- a cell's context -----------------------------------------------------------------------------------------------
function makeCtx(tab, cell, alias) {
  const ctx = {
    tab,
    cell,
    alias,
    items: [],
    pngs: new Map(),
    notes: [],
    area: null,
    note: (text) => {
      ctx.notes.push(text);
      if (ctx.verbose) log(`    ${text}`);
    },
    async add(rule, severity, what, detail, shot = true) {
      ctx.items.push({ rule, severity, what: String(what).slice(0, 160), detail: String(detail || "").slice(0, 400) });
      if (shot && !ctx.pngs.has(rule)) ctx.pngs.set(rule, await shotOf(tab));
    },
  };
  return ctx;
}

async function loadPage(ctx, route, wait = 25000) {
  const r = await session.go(ctx.tab, route, { wait });
  if (!r.ok) {
    ctx.note(`did not open ${route}: ${String(r.error).slice(0, 100)}`);
    return false;
  }
  await sleep(500);
  // a cold load on a shared box can be slow to paint: give it up to 15 s before anything is judged
  for (let i = 0; i < 10; i++) {
    const n = await ctx.tab.page.evaluate(() => ((document.querySelector("main") || document.body).innerText || "").trim().length).catch(() => 0);
    if (n >= 25) break;
    await sleep(1500);
  }
  return true;
}

const badGateway = (tab, mark) => tab.since(mark).http.some((h) => [502, 503, 504].includes(h.status));

// ---- family: fault --------------------------------------------------------------------------------------------------
async function famFault(ctx, route) {
  const { tab } = ctx;
  const calls = trackCalls(tab);
  if (!(await loadPage(ctx, route))) return;
  await sleep(700);
  const base = await facts(tab);
  calls.stop();
  if (base.textLength < 25 || base.overlay) return ctx.note("the page itself is blank or crashed without a fault: no trials");
  const endpoints = [...calls.seen.keys()].slice(0, 8);
  ctx.note(`calls on load: ${endpoints.join(", ") || "none"}`);
  if (!endpoints.length) return;
  for (const target of endpoints) await faultTrial(ctx, route, "500", target, base);
  for (const kind of ["429", "empty", "delay"]) await faultTrial(ctx, route, kind, null, base);
}

async function faultTrial(ctx, route, kind, target, base, attempt = 0) {
  const { tab } = ctx;
  if ((await headroom(() => {})) === "stop") throw new Error("stop");
  const label = target ? `GET ${target}` : "all calls";
  const what = `${kind === "delay" ? "10 s delay" : kind === "empty" ? "empty 200" : kind} on ${label}`;
  let hits = 0;
  const handler = async (rt) => {
    const req = rt.request();
    const u = new URL(req.url());
    if (req.method() !== "GET" || !u.pathname.startsWith("/v1/") || SKIP_CALL.test(u.pathname) || (target && tpl(u.pathname) !== target)) return rt.fallback();
    hits++;
    if (kind === "500") return rt.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"Internal Server Error"}' });
    if (kind === "429") return rt.fulfill({ status: 429, contentType: "application/json", headers: { "retry-after": "5" }, body: '{"detail":"Too Many Requests"}' });
    if (kind === "empty") return rt.fulfill({ status: 200, contentType: "application/json", body: "" });
    await sleep(10000);
    return rt.fallback();
  };
  let routed = true;
  await tab.context.route("**/v1/**", handler);
  const off = async () => {
    if (routed) await tab.context.unroute("**/v1/**", handler).catch(() => null);
    routed = false;
  };
  const mark = tab.mark();
  const items = [];
  const add = async (rule, severity, text) => items.push({ rule, severity, text, png: await shotOf(tab) });
  try {
    await session.go(tab, route, { wait: kind === "delay" ? 1 : 15000 });
    if (kind === "delay") {
      await sleep(3000);
      const mid = await facts(tab);
      const pending = tab.api.inflight > 0;
      if (pending && mid.textLength < 25 && mid.loading === 0) await add("fault:blank-while-waiting", "MAJOR", `${what}: blank, with no outline or loading mark, 3 s after opening`);
      else if (pending && EMPTY.test(mid.text) && !EMPTY.test(base.text)) await add("fault:false-empty", "MAJOR", `${what}: says there is nothing (${(EMPTY.exec(mid.text) || [""])[0]}) while the call is still waiting`);
      // eight calls delayed 10 s each queue behind the browser's six connections: give the page up to 50 s to fill
      let end = null;
      for (let wait = 0; wait < 10; wait++) {
        await session.settle(tab, 8000);
        await sleep(2500);
        end = await facts(tab);
        if (end.loading === 0 && end.textLength >= base.textLength * 0.6) break;
      }
      ctx.note(`${what}: at 3 s ${mid.textLength} chars, loading marks ${mid.loading}, call pending ${pending}; at the end ${end.textLength} chars (was ${base.textLength}), loading marks ${end.loading}`);
      // an app that gives up after its own timeout and says so, with Retry, is doing what it should
      const calmEnd = end.bits.some((x) => FRIENDLY.test(x) && !TECH.test(x) && !base.bits.includes(x)) || end.retry;
      ctx.note(`${what}: end text "${end.text.slice(0, 140)}", calm message ${calmEnd}`);
      if (hits && !calmEnd && (end.textLength < base.textLength * 0.6 || end.loading > 0 || end.overlay)) await add("fault:no-recovery", "MAJOR", `${what}: the answer came after 10 s but the page stayed ${end.loading ? "on its loading mark" : end.overlay ? "crashed" : "empty"}`);
    } else {
      await sleep(1200);
      const a = await facts(tab);
      await sleep(2400);
      const b = await facts(tab);
      const bits = [...new Set([...a.bits, ...b.bits])].filter((x) => !base.bits.includes(x));
      const calm = bits.some((x) => FRIENDLY.test(x) && !TECH.test(x)) || a.retry || b.retry;
      const tech = bits.filter((x) => TECH.test(x));
      const techOnly = tech.filter((x) => !FRIENDLY.test(x));
      const errs = tab.since(mark).pageerrors.filter((e) => !EXPECTED.test(e));
      if (hits) {
        if (b.textLength < 25 && b.loading === 0) await add("fault:blank", "MAJOR", `${what}: the page went blank${errs[0] ? ` (${errs[0].slice(0, 80)})` : ""}`);
        if (b.overlay) await add("fault:crash", "MAJOR", `${what}: crash screen "${b.overlay.slice(0, 80)}"`);
        if (techOnly.length) await add("fault:raw-error", "MAJOR", `${what}: shows raw error words "${techOnly[0].slice(0, 90)}"`);
        else if (tech.length) await add("fault:raw-error", "MINOR", `${what}: shows a code in the message "${tech[0].slice(0, 90)}"`);
        ctx.note(`${what}: ${b.textLength} chars (was ${base.textLength}), loading marks ${b.loading}, calm message ${calm}, Retry ${a.retry || b.retry}, new text ${JSON.stringify(bits.slice(0, 2)).slice(0, 150)}`);
        if (b.loading > 0 && !calm) {
          // a loaded box paints slowly: look again 9 s later before calling it stuck
          await sleep(9000);
          const c = await facts(tab);
          const calmLater = c.bits.some((x) => FRIENDLY.test(x) && !TECH.test(x) && !base.bits.includes(x)) || c.retry;
          if (c.loading > 0 && !calmLater) {
            const inMain = (c.loadingIn || []).some((x) => x.main);
            await add("fault:stuck-loading", inMain ? "MAJOR" : "MINOR", `${what}: still on its loading mark 13 s after the call failed, with no message (${(c.loadingIn || []).map((x) => `${x.main ? "in the page" : "in the header or side"}: ${x.s}`).join("; ").slice(0, 150)})`);
          }
        }
        if (b.textLength >= 25 && b.loading === 0 && !calm && !techOnly.length) {
          if (EMPTY.test(b.text) && !EMPTY.test(base.text)) await add("fault:false-empty", "MAJOR", `${what}: says there is nothing (${(EMPTY.exec(b.text) || [""])[0]}) when the call failed`);
          else if (base.textLength - b.textLength > 80) await add("fault:silent", "MINOR", `${what}: part of the page vanished (${base.textLength - b.textLength} characters) with no message and no Retry`);
        }
        const bug = errs.find((e) => CODE_BUG.test(e));
        if (bug) await add("fault:unhandled-error", "MINOR", `${what}: an unhandled script error was thrown: ${bug.slice(0, 100)}`);
        // Retry must work once the call works again
        if (kind === "500" && (a.retry || b.retry) && !ctx.retryTried) {
          ctx.retryTried = true;
          await off();
          const btn = tab.page.getByRole("button", { name: /^(retry|try again|reload|refresh|tap to retry)/i }).filter({ visible: true }).first();
          await btn.click({ timeout: 5000 }).catch(() => null);
          // give the page up to 24 s to recover on a loaded box
          let after = null;
          for (let wait = 0; wait < 12; wait++) {
            await session.settle(tab, 6000);
            await sleep(2000);
            after = await facts(tab);
            if (after.textLength >= base.textLength * 0.6 && !after.bits.some((x) => FRIENDLY.test(x) && !base.bits.includes(x))) break;
          }
          if (after.textLength < base.textLength * 0.6 || after.bits.some((x) => FRIENDLY.test(x) && !base.bits.includes(x))) await add("fault:retry-fails", "MAJOR", `${what}: Retry was pressed after the call worked again and the page stayed broken`);
        }
      }
    }
    if (badGateway(tab, mark)) {
      if (attempt === 0) {
        ctx.note(`${what}: dev API answered 502/503/504 during the trial, retried`);
        await off();
        await sleep(20000);
        return faultTrial(ctx, route, kind, target, base, 1);
      }
      return ctx.note(`${what}: dev API unstable, trial dropped`);
    }
    for (const it of items) {
      ctx.items.push({ rule: it.rule, severity: it.severity, what: it.text, detail: "" });
      if (!ctx.pngs.has(it.rule)) ctx.pngs.set(it.rule, it.png);
    }
    if (!hits) ctx.note(`${what}: the page made no such call this time`);
  } finally {
    await off();
  }
}

// ---- family: 3g -----------------------------------------------------------------------------------------------------
async function fam3g(ctx, route) {
  const { tab } = ctx;
  const handler = async (rt) => {
    const req = rt.request();
    if (req.method() !== "GET" || !new URL(req.url()).pathname.startsWith("/v1/")) return rt.fallback();
    let res;
    try {
      res = await rt.fetch();
    } catch {
      return rt.fallback();
    }
    const body = await res.body().catch(() => Buffer.alloc(0));
    await sleep(1700 + body.length / 200);
    return rt.fulfill({ status: res.status(), headers: { "content-type": res.headers()["content-type"] || "application/json" }, body });
  };
  await tab.context.route("**/v1/**", handler);
  try {
    const base = {};
    await session.go(tab, route, { wait: 1 });
    await sleep(700);
    const early = await facts(tab);
    base.pending = tab.api.inflight > 0;
    if (base.pending && early.textLength < 25 && early.loading === 0) await ctx.add("net3g:blank-while-loading", "MINOR", "blank with no outline or loading mark while the first calls wait", "");
    await sleep(900);
    const mid = await facts(tab);
    if (tab.api.inflight > 0 && EMPTY.test(mid.text)) await ctx.add("net3g:false-empty", "MAJOR", `says there is nothing (${(EMPTY.exec(mid.text) || [""])[0]}) while a call is still on its way`, "");
    await session.settle(tab, 60000);
    await sleep(1500);
    const shifts = await tab.page.evaluate(() => window.__qaShifts || []).catch(() => []);
    const total = shifts.reduce((a, s) => a + s.v, 0);
    ctx.note(`3G: first look ${early.textLength} chars, loading marks ${early.loading}, call pending ${base.pending}; layout shift ${total.toFixed(2)} in ${shifts.length} moves`);
    if (total > 0.1) {
      const worst = [...shifts].sort((a, b) => b.v - a.v).slice(0, 3);
      await ctx.add("net3g:layout-shift", total > 0.25 ? "MAJOR" : "MINOR", `layout shift ${total.toFixed(2)} over the load`, worst.map((s) => `${s.v.toFixed(2)} at ${s.t} ms: ${(s.src || []).join(" + ").slice(0, 100)}`).join(" | "));
    }
  } finally {
    await tab.context.unroute("**/v1/**", handler).catch(() => null);
  }
}

// ---- family: extremes -----------------------------------------------------------------------------------------------
const NAME_KEY = /name|title|note|text|summary|message|label|reason|company|city|body|description|subject|heading|comment|remark|address|location/i;
const NOT_TEXT_KEY = /(^|_)(id|ids|url|href|uri|email|phone|status|stage|kind|type|state|code|key|role|at|date|time|token|slug|currency|locale|lang|language|timezone|color|colour|icon|channel|source|direction|outcome|priority|scope|view|side|format|mime|unit|period)(_|$)|_id$|Id$|_at$|At$/;
const NUM_KEY = /count|total|amount|value|score|duration|seconds|minutes|number|rate|percent|revenue|price|calls|leads|sum|avg|average|attempts|late|overdue|today|pending|connected/i;
const NOT_NUM_KEY = /(^|_)(id|at|ts|time|date|year|month|day|hour|offset|version|status|port|page|limit|index|order|position|rank)(_|$)|_id$/i;
const PHONE_KEY = /phone|mobile|msisdn|whatsapp/i;
const SKIP_ARRAY = /^(stages|tabs|steps|columns|series|buckets|options|plans|sizes|languages|weekdays|hours|points)$/i;
const SENTENCE = "Needs a callback about the advanced course fee plan and the batch timing ";
const HI = "राहुल शर्मा क्षत्रिय श्रीमती ज्ञानेश्वर ";
const MR = "सुनिता पाटील ग्रामपंचायत कार्यालय, उद्या दुपारी फोन करा ";
const ZW = ["​", "‌", "‍", "⁠", "﻿", "­", "‎", "‏"];

function textFor(variant, original, idx) {
  switch (variant) {
    case "long300":
      return idx % 2 ? "Subramaniam".repeat(28).slice(0, 300) : SENTENCE.repeat(5).slice(0, 300);
    case "emoji":
      return `\u{1F525}\u{1F4DE} ${original} ❤️‍\u{1F525}\u{1F64F}\u{1F3FD}\u{1F468}‍\u{1F469}‍\u{1F467}‍\u{1F466}`;
    case "indic":
      return (idx % 2 ? MR : HI).repeat(8).slice(0, 300);
    case "zerowidth":
      return `${original.split("").map((ch, i) => ch + ZW[i % ZW.length]).join("")}⁠`.repeat(1) + "​".repeat(60);
    default:
      return original;
  }
}

function mutate(data, variant) {
  let idx = 0;
  const walk = (value, key, depth) => {
    if (Array.isArray(value)) {
      let list = value.map((v) => walk(v, key, depth + 1));
      if (variant === "rows1000" && depth <= 4 && list.length >= 1 && list.length < 1000 && !SKIP_ARRAY.test(key || "") && list.every((x) => x && typeof x === "object" && !Array.isArray(x) && Object.keys(x).length >= 2)) {
        const seed = list;
        list = [];
        for (let i = 0; i < 1000; i++) {
          const copy = JSON.parse(JSON.stringify(seed[i % seed.length]));
          for (const k of Object.keys(copy)) if (/id$/i.test(k) && typeof copy[k] === "string") copy[k] = `${copy[k]}-${i}`;
          list.push(copy);
        }
      }
      return list;
    }
    if (value && typeof value === "object") {
      const out = {};
      for (const [k, v] of Object.entries(value)) out[k] = walk(v, k, depth + 1);
      return out;
    }
    if (typeof value === "string" && key) {
      if (PHONE_KEY.test(key)) return variant === "bignum" ? `+91${"9".repeat(24)}` : value;
      if (variant !== "rows1000" && variant !== "bignum" && NAME_KEY.test(key) && !NOT_TEXT_KEY.test(key) && value.trim()) return textFor(variant, value, idx++);
      return value;
    }
    if (typeof value === "number" && variant === "bignum" && key && NUM_KEY.test(key) && !NOT_NUM_KEY.test(key)) return 9876543210123;
    return value;
  };
  return walk(data, "", 0);
}

const LAYOUT_RULES = ["layout:overflow-x", "layout:covered", "layout:overlap", "layout:text-clipped"];
async function layoutFindings(tab, route, rules) {
  const phone = tab.dev.phone;
  const s = await tab.page.evaluate(inv.scan, phone).catch(() => null);
  if (!s) return null;
  return inv
    .findingsFrom(s, { route, phone, shift: 0 })
    .filter((f) => rules.includes(f.rule))
    .filter((f) => !/^(span|div|b|i|small|p) "[^"]{1,3}"$/.test(f.selector)) // initials in an avatar are not text to read
    .filter((f) => !/\[role=(status|alert)\]/.test(f.detail || "")); // a notice that came in over the page is passing, not the page's layout
}
const keyOfFinding = (f) => `${f.rule}|${stripQ(f.selector)}`;

async function famExtremes(ctx, route) {
  const { tab } = ctx;
  if (!(await loadPage(ctx, route))) return;
  await sleep(700);
  const base = await facts(tab);
  if (base.textLength < 25 || base.overlay) return ctx.note("the page is blank or crashed without the data: no trials");
  const baseKeys = new Set(((await layoutFindings(tab, route, LAYOUT_RULES)) || []).map(keyOfFinding));
  for (const variant of ["rows1000", "long300", "emoji", "indic", "zerowidth", "bignum"]) {
    if ((await headroom(() => {})) === "stop") throw new Error("stop");
    let changed = 0;
    const handler = async (rt) => {
      const req = rt.request();
      const u = new URL(req.url());
      if (req.method() !== "GET" || !u.pathname.startsWith("/v1/") || SKIP_CALL.test(u.pathname) || SKIP_DATA.test(u.pathname)) return rt.fallback();
      let res;
      try {
        res = await rt.fetch();
      } catch {
        return rt.fallback();
      }
      const ct = res.headers()["content-type"] || "";
      if (!/json/i.test(ct)) return rt.fulfill({ response: res });
      let data;
      try {
        data = await res.json();
      } catch {
        return rt.fulfill({ response: res });
      }
      let out = mutate(data, variant);
      let body = JSON.stringify(out);
      if (body.length > 8e6) {
        out = mutate(data, "long300");
        body = JSON.stringify(out);
      }
      if (body !== JSON.stringify(data)) changed++;
      return rt.fulfill({ status: res.status(), headers: { "content-type": ct }, body });
    };
    await tab.context.route("**/v1/**", handler);
    const mark = tab.mark();
    try {
      await session.go(tab, route, { wait: 30000 });
      await sleep(900);
      if (!changed) {
        ctx.note(`${variant}: no answer on this page had fields to rewrite`);
        continue;
      }
      if (badGateway(tab, mark)) {
        ctx.note(`${variant}: dev API 502/503/504, dropped`);
        continue;
      }
      const f = await facts(tab);
      const errs = tab.since(mark).pageerrors.filter((e) => !EXPECTED.test(e));
      if (f.textLength < 25 && f.loading === 0) await ctx.add("data:blank", "MAJOR", `${variant}: the page went blank${errs[0] ? ` (${errs[0].slice(0, 80)})` : ""}`, "");
      else if (f.overlay) await ctx.add("data:crash", "MAJOR", `${variant}: crash screen "${f.overlay.slice(0, 80)}"`, "");
      else if (errs.find((e) => CODE_BUG.test(e))) await ctx.add("data:unhandled-error", "MINOR", `${variant}: ${errs.find((e) => CODE_BUG.test(e)).slice(0, 100)}`, "");
      for (const found of (await layoutFindings(tab, route, LAYOUT_RULES)) || []) {
        if (baseKeys.has(keyOfFinding(found))) continue;
        await ctx.add(`data:${found.rule.split(":")[1]}`, found.rule === "layout:overflow-x" ? "MAJOR" : found.severity, `${variant}: ${found.selector}`, found.detail);
      }
    } finally {
      await tab.context.unroute("**/v1/**", handler).catch(() => null);
    }
  }
}

// ---- family: zoom ---------------------------------------------------------------------------------------------------
const ZOOM = (k) => {
  const els = [...document.querySelectorAll("body *")].filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()));
  const sizes = els.map((el) => parseFloat(getComputedStyle(el).fontSize));
  els.forEach((el, i) => el.style.setProperty("font-size", `${(sizes[i] * k).toFixed(2)}px`, "important"));
  window.__qaZoomK = k;
  new MutationObserver((list) => {
    for (const m of list) {
      for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        for (const el of [n, ...n.querySelectorAll("*")]) {
          if (el.dataset.qaz || ![...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) continue;
          el.dataset.qaz = "1";
          el.style.setProperty("font-size", `${(parseFloat(getComputedStyle(el).fontSize) * k).toFixed(2)}px`, "important");
        }
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
};
const CUT = () => {
  const visible = (el) => el.checkVisibility && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getBoundingClientRect().width > 0;
  const out = [];
  for (const el of document.querySelectorAll("main *, header *, nav *, [role=dialog] *")) {
    if (out.length >= 15) break;
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    if ((el.textContent || "").trim().length <= 3) continue; // initials in an avatar are not text to read
    const cs = getComputedStyle(el);
    if (!/(hidden|clip)/.test(cs.overflowY) || cs.display === "-webkit-box" || (cs.webkitLineClamp && cs.webkitLineClamp !== "none")) continue;
    if (el.scrollHeight <= el.clientHeight + 2 || el.clientHeight < 8 || !visible(el)) continue;
    out.push({ s: window.__qaSem(el), sh: el.scrollHeight, ch: el.clientHeight });
  }
  return out;
};

async function famZoom(ctx, route) {
  const { tab } = ctx;
  if (!(await loadPage(ctx, route))) return;
  await sleep(700);
  const base = await facts(tab);
  if (base.textLength < 25 || base.overlay) return ctx.note("the page is blank without zoom: no trials");
  const baseKeys = new Set(((await layoutFindings(tab, route, LAYOUT_RULES)) || []).map(keyOfFinding));
  const baseCut = new Set(((await tab.page.evaluate(CUT).catch(() => [])) || []).map((c) => stripQ(c.s)));
  for (const level of [130, 200]) {
    if (level !== 130 && !(await loadPage(ctx, route))) return;
    await tab.page.evaluate(ZOOM, level / 100).catch(() => null);
    await sleep(900);
    for (const found of (await layoutFindings(tab, route, LAYOUT_RULES)) || []) {
      if (baseKeys.has(keyOfFinding(found))) continue;
      await ctx.add(`zoom${level}:${found.rule.split(":")[1]}`, found.rule === "layout:overflow-x" ? "MAJOR" : found.severity, found.selector, found.detail);
    }
    for (const c of (await tab.page.evaluate(CUT).catch(() => [])) || []) {
      if (baseCut.has(stripQ(c.s))) continue;
      await ctx.add(`zoom${level}:text-cut`, "MINOR", c.s, `${c.s}: the text is ${c.sh}px tall in a ${c.ch}px box that hides the rest`);
    }
  }
}

// ---- family: keyboard -----------------------------------------------------------------------------------------------
const SAMPLE = () => {
  window.__qaN = window.__qaN || 0;
  const sig = (el) => {
    const cs = getComputedStyle(el);
    return [cs.outlineStyle, cs.outlineWidth, cs.outlineColor, cs.boxShadow, cs.borderTopColor, cs.borderTopWidth, cs.backgroundColor, cs.color, cs.textDecorationLine, cs.opacity, cs.transform].join("|");
  };
  const prev = window.__qaPrev;
  const prevBlurSig = prev && prev.isConnected ? sig(prev) : null;
  const pr = prev && prev.isConnected ? prev.getBoundingClientRect() : null;
  const prevRect = pr ? { x: pr.left, y: pr.top, w: pr.width, h: pr.height } : null;
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return { body: true, prevBlurSig, prevRect };
  el.__qaId = el.__qaId || ++window.__qaN;
  const r = el.getBoundingClientRect();
  const vw = document.documentElement.clientWidth;
  const vh = window.innerHeight;
  const top = document.elementFromPoint(Math.min(vw - 1, Math.max(0, r.left + r.width / 2)), Math.min(vh - 1, Math.max(0, r.top + Math.min(r.height / 2, 40))));
  window.__qaPrev = el;
  return {
    id: el.__qaId,
    sem: window.__qaSem(el),
    fv: el.matches(":focus-visible"),
    sig: sig(el),
    prevBlurSig,
    prevRect,
    rect: { x: r.left, y: r.top, w: r.width, h: r.height },
    off: r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw,
    tiny: r.width < 2 || r.height < 2,
    coveredBy: top && top !== el && !el.contains(top) && !top.contains(el) ? window.__qaSem(top) : "",
    inDialog: !!el.closest("dialog[open],[role=dialog],[aria-modal=true]"),
  };
};
const INVENTORY = () => {
  window.__qaN = window.__qaN || 0;
  const visible = (el) => el.checkVisibility && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
  const roving = "[role=tablist],[role=radiogroup],[role=toolbar],[role=listbox],[role=menu],[role=menubar],[role=tree],[role=grid]";
  const focusables = [];
  for (const el of document.querySelectorAll("a[href],button,input:not([type=hidden]),select,textarea,summary,[tabindex]")) {
    if (el.disabled || el.tabIndex < 0 || !visible(el) || el.closest("[inert]") || el.closest("[aria-hidden=true]") || el.closest(roving)) continue;
    el.__qaId = el.__qaId || ++window.__qaN;
    focusables.push({ id: el.__qaId, sem: window.__qaSem(el) });
  }
  const nat = "a[href],button,input,select,textarea,summary,[tabindex]";
  const clicky = [];
  for (const el of document.querySelectorAll("main *, header *, nav *, [role=dialog] *")) {
    if (clicky.length >= 12) break;
    if (!visible(el) || el.matches(nat) || el.closest(nat) || el.closest("label")) continue;
    const role = el.getAttribute("role");
    const looks = getComputedStyle(el).cursor === "pointer" || /^(button|link|tab|menuitem|switch|checkbox|radio)$/.test(role || "");
    if (!looks) continue;
    const par = el.parentElement;
    if (par && !par.matches(nat) && getComputedStyle(par).cursor === "pointer") continue;
    const r = el.getBoundingClientRect();
    if (r.width < 16 || r.height < 16 || el.querySelector(nat)) continue;
    clicky.push({ sem: window.__qaSem(el) });
  }
  return { focusables, clicky };
};

const STILL = (ids) => {
  const want = new Set(ids);
  const out = [];
  for (const el of document.querySelectorAll("a[href],button,input:not([type=hidden]),select,textarea,summary,[tabindex]")) {
    if (want.has(el.__qaId) && el.isConnected && !el.disabled && el.tabIndex >= 0 && el.checkVisibility && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getBoundingClientRect().width > 0) out.push(el.__qaId);
  }
  return out;
};

// A picture of the control and 8 px around it, to see whether anything changes when it takes focus (a ring drawn by a
// pseudo-element or a child is not in the computed style of the control itself).
async function clipOf(page, rect, vp) {
  if (!rect || rect.w < 1 || rect.h < 1 || rect.y + rect.h < 0 || rect.y > vp.height) return null;
  const pad = 8;
  const x = Math.max(0, Math.floor(rect.x - pad));
  const y = Math.max(0, Math.floor(rect.y - pad));
  const width = Math.min(vp.width - x, Math.ceil(rect.w + pad * 2));
  const height = Math.min(vp.height - y, Math.ceil(rect.h + pad * 2));
  if (width < 4 || height < 4) return null;
  return page.screenshot({ type: "png", clip: { x, y, width, height }, timeout: 5000 }).catch(() => null);
}

async function famKeyboard(ctx, route) {
  const { tab } = ctx;
  const page = tab.page;
  if (!(await loadPage(ctx, route))) return;
  await sleep(900);
  const start = await facts(tab);
  if (start.textLength < 25) return ctx.note("blank page: no Tab walk");
  if (await page.getByRole("dialog").filter({ visible: true }).count()) return ctx.note("a dialog is open over the page: no Tab walk");
  const inventory = await page.evaluate(INVENTORY).catch(() => ({ focusables: [], clicky: [] }));
  await page.evaluate(() => {
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    window.scrollTo(0, 0);
    window.__qaPrev = null;
  });
  const stops = [];
  const visited = new Set();
  const visitedSem = new Set();
  let wrapped = false;
  let bodyStops = 0;
  let trapped = null;
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press("Tab");
    await sleep(110);
    const s = await page.evaluate(SAMPLE).catch(() => null);
    if (!s) break;
    if (s.body) {
      if (++bodyStops > 2) {
        wrapped = true;
        break;
      }
      continue;
    }
    const prevStop = stops[stops.length - 1];
    if (prevStop && s.prevBlurSig && prevStop.sig === s.prevBlurSig && !prevStop.noted) {
      // the control's own style does not change: look at the pixels around it, focused and not
      prevStop.noted = true;
      const blurred = await clipOf(page, s.prevRect, tab.dev.viewport);
      if (prevStop.clip && blurred && prevStop.clip.equals(blurred)) await ctx.add("kbd:no-focus-indicator", "MAJOR", prevStop.sem, `${prevStop.sem}: nothing changes on screen when it takes keyboard focus`, false);
      else if (!prevStop.clip || !blurred) ctx.note(`${prevStop.sem}: focus look not checkable (off screen)`);
    }
    if (stops.length && s.id === stops[0].id) {
      wrapped = true;
      break;
    }
    if (visited.has(s.id)) {
      if (prevStop && prevStop.id === s.id) {
        trapped = `${s.sem}: focus stays on it after Tab`;
        break;
      }
      if (!s.inDialog) {
        trapped = `focus loops through ${stops.length} controls and comes back to ${s.sem} without reaching the rest of the page`;
        break;
      }
      wrapped = true;
      break;
    }
    visited.add(s.id);
    visitedSem.add(s.sem);
    if (s.coveredBy && !s.inDialog) await ctx.add("kbd:focus-covered", /role=(status|alert)/.test(s.coveredBy) ? "MINOR" : "MAJOR", s.sem, `${s.sem} has keyboard focus but ${s.coveredBy} is on top of it`, true);
    if (s.off || s.tiny) await ctx.add("kbd:focus-lost", "MAJOR", s.sem, `${s.sem} has keyboard focus but ${s.tiny ? "cannot be seen (under 2 px)" : "is off the screen"}`, false);
    s.clip = await clipOf(page, s.rect, tab.dev.viewport);
    stops.push(s);
  }
  if (trapped) await ctx.add("kbd:trap", "MAJOR", `after ${stops.length} stops`, trapped, true);
  if (wrapped && !trapped) {
    let missed = inventory.focusables.filter((f) => !visited.has(f.id) && !visitedSem.has(f.sem));
    if (missed.length) {
      const still = new Set(await page.evaluate(STILL, missed.map((m) => m.id)).catch(() => []));
      missed = missed.filter((m) => still.has(m.id)); // a control the page has since replaced or hidden is not unreachable
    }
    if (missed.length) await ctx.add("kbd:unreachable", "MAJOR", `${missed.length} controls`, missed.slice(0, 8).map((m) => m.sem).join(" | "), true);
  }
  if (inventory.clicky.length) await ctx.add("kbd:clickable-not-focusable", "MINOR", `${inventory.clicky.length} elements`, inventory.clicky.slice(0, 8).map((m) => m.sem).join(" | "), true);
  ctx.note(`Tab walk: ${stops.length} stops${wrapped ? ", wrapped" : ", not wrapped"}`);
}

// ---- family: dark ---------------------------------------------------------------------------------------------------
const ISLANDS = () => {
  const lum = (c) => {
    const m = c.match(/[\d.]+/g);
    if (!m || m.length < 3) return null;
    const [r, g, b] = m.slice(0, 3).map(Number).map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return { L: 0.2126 * r + 0.7152 * g + 0.0722 * b, a: m[3] === undefined ? 1 : Number(m[3]) };
  };
  const visible = (el) => el.checkVisibility && el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && el.getBoundingClientRect().width > 0;
  const bodyL = (lum(getComputedStyle(document.body).backgroundColor) || { L: 0 }).L;
  if (bodyL > 0.25) return { bodyL, islands: [], fields: [] };
  const vh = window.innerHeight;
  const kept = [];
  for (const el of document.querySelectorAll("body *")) {
    if (kept.length >= 14) break;
    if (/^(IMG|VIDEO|CANVAS|SVG|IFRAME|PICTURE|PATH|INPUT|TEXTAREA|SELECT|OPTION)$/i.test(el.tagName) || !visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 100 || r.height < 36 || r.bottom < 0 || r.top > vh * 1.5) continue;
    const cs = getComputedStyle(el);
    const c = lum(cs.backgroundColor);
    if (!c || c.a < 0.9 || c.L < 0.7 || cs.backgroundImage !== "none" || kept.some((k) => k.contains(el))) continue;
    kept.push(el);
  }
  const fields = [...document.querySelectorAll("input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=range]),textarea,select")]
    .filter(visible)
    .filter((el) => {
      const c = lum(getComputedStyle(el).backgroundColor);
      return c && c.a >= 0.9 && c.L >= 0.7;
    })
    .slice(0, 8);
  return { bodyL, islands: kept.map((el) => ({ s: window.__qaSem(el), w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height) })), fields: fields.map((el) => ({ s: window.__qaSem(el) })) };
};

async function contrastNodes(tab) {
  await tab.page
    .evaluate(async () => {
      const running = document.getAnimations().filter((a) => {
        const end = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming().endTime : 0;
        return Number.isFinite(end);
      });
      await Promise.race([Promise.allSettled(running.map((a) => a.finished)), new Promise((resolve) => setTimeout(resolve, 3000))]);
    })
    .catch(() => null);
  await sleep(200);
  try {
    const { AxeBuilder } = require("@axe-core/playwright");
    const res = await new AxeBuilder({ page: tab.page }).withRules(["color-contrast"]).analyze();
    const nodes = [];
    for (const v of res.violations) {
      for (const n of v.nodes) {
        const data = ((n.any || [])[0] || {}).data || {};
        nodes.push({ target: [].concat(n.target || []).join(" "), ratio: data.contrastRatio, fg: data.fgColor, bg: data.bgColor });
      }
    }
    return nodes;
  } catch (error) {
    console.log(`    axe contrast failed: ${String(error).split("\n")[0].slice(0, 200)}`);
    return null;
  }
}

async function famDark(ctx, route) {
  const { tab } = ctx;
  if (!(await loadPage(ctx, route))) return;
  await sleep(900);
  const f = await facts(tab);
  if (f.theme !== "dark") return ctx.note(`the app did not switch to its dark theme (data-theme="${f.theme}"): not judged`);
  const s = await tab.page.evaluate(ISLANDS).catch(() => null);
  if (s && s.islands.length) await ctx.add("dark:light-island", "MINOR", `${s.islands.length} light panels`, s.islands.slice(0, 6).map((i) => `${i.s} ${i.w}x${i.h}`).join(" | "), true);
  if (s && s.fields.length) await ctx.add("dark:light-field", "MINOR", `${s.fields.length} light fields`, s.fields.slice(0, 6).map((i) => i.s).join(" | "), true);
  const dark = await contrastNodes(tab);
  ctx.note(`dark: page background luminance ${s ? s.bodyL.toFixed(2) : "?"}, ${s ? s.islands.length : 0} light panels, ${s ? s.fields.length : 0} light fields, ${dark ? dark.length : "n/a"} contrast failures`);
  if (!dark || !dark.length) return;
  const png = await shotOf(tab);
  const light = await session.openTab({ alias: ctx.alias, device: ctx.cell.size, theme: "light", state: "normal", keep: true });
  let lightNodes = null;
  try {
    await prepare(light);
    if ((await session.go(light, route, { wait: 25000 })).ok) {
      await sleep(900);
      lightNodes = await contrastNodes(light);
    }
  } finally {
    await session.closeTab(light).catch(() => null);
  }
  if (!lightNodes) return ctx.note("no light-theme contrast baseline: dark contrast not judged");
  const lightSet = new Set(lightNodes.map((n) => n.target));
  const fresh = dark.filter((n) => !lightSet.has(n.target));
  if (fresh.length) {
    ctx.items.push({ rule: "dark:contrast", severity: "MINOR", what: `${fresh.length} elements`, detail: fresh.slice(0, 5).map((n) => `${n.target.slice(0, 70)} ${n.ratio ? `${Number(n.ratio).toFixed(1)}:1` : ""} (${n.fg || "?"} on ${n.bg || "?"})`).join(" | ") });
    ctx.pngs.set("dark:contrast", png);
  }
}

// ---- families: history and double (sheets and forms) ------------------------------------------------------------------
const DANGER = /log ?out|sign ?out|delete|remove|erase|reset|close account|dial|whatsapp|\bpay\b|buy|upgrade|checkout|upload|revoke|disconnect|unlink|archive|transfer|record\b|invite|export|download|^call\b|\bsms\b|e-?mail/i;
const OPENER = /add a lead|new lead|add (?:a |an )?(?:note|task|lead|follow)|\bnote\b|\btask\b|follow-?up|schedule|reminder|filter|search|stage|move|edit|ask dipak|report a problem|problem|notifications?|workspace|account|\+/i;
const SUBMIT = /^(save|add|create|submit|send|done|continue|post|confirm|update|apply|finish|log|schedule|set|move|mark)\b/i;
const FIELD = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]):not([type=password]):not([type=submit]):not([type=button]):not([type=date]):not([type=time]):not([type=datetime-local]):not([type=range]):not([type=color]), textarea";
// fields of a form (not a search box or a filter) and the buttons that really save
const FORM_FIELD = `${FIELD.split(", textarea")[0]}:not([type=search]):not([aria-label*="search" i]):not([placeholder*="search" i]), textarea:not([aria-label*="search" i]):not([placeholder*="search" i])`;
const STRONG = /^(save|post|submit|done|send|update|apply|create|confirm|finish)\b|\bsave\b/i;
const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const dlgOf = (page) => page.getByRole("dialog").filter({ visible: true });

async function closeDialogs(page) {
  for (let i = 0; i < 3; i++) {
    if (!(await dlgOf(page).count())) return;
    await page.keyboard.press("Escape").catch(() => null);
    await sleep(500);
    if (await dlgOf(page).count()) {
      const x = dlgOf(page).first().getByRole("button", { name: /close|cancel|back|dismiss|discard/i });
      if (await x.count()) await x.first().click({ timeout: 2000 }).catch(() => null);
      await sleep(500);
    }
  }
}

const SUB_OPENER = /add|new|create|note|task|lead|follow|schedule|reminder|log|edit|change/i;

async function waitDialog(page, ms = 3000) {
  for (let t = 0; t < ms; t += 300) {
    if (await dlgOf(page).count()) return true;
    await sleep(300);
  }
  return false;
}

// What the top sheet offers: text fields to type in and Save-like buttons to press.
async function dialogFacts(page) {
  if (!(await dlgOf(page).count())) return { open: false, fields: 0, submits: 0 };
  const d = dlgOf(page).last();
  return { open: true, fields: await d.locator(FORM_FIELD).filter({ visible: true }).count(), submits: await d.getByRole("button", { name: STRONG }).filter({ visible: true }).count() };
}

// Press the buttons of a flow's path in turn: the first on the page, the next ones inside the sheet that opened.
async function pressButton(scope, name) {
  // the name is a label or the button's text; a card-like button's accessible name has spaces its text does not: try exact, then the start of it
  const exact = scope.getByRole("button", { name, exact: true }).filter({ visible: true });
  const target = (await exact.count()) ? exact.first() : scope.getByRole("button", { name: name.slice(0, 40) }).filter({ visible: true }).first();
  return target.click({ timeout: 5000 }).then(() => true, () => false);
}

async function clickPath(page, flowPath) {
  for (let i = 0; i < flowPath.length; i++) {
    const scope = i > 0 && (await dlgOf(page).count()) ? dlgOf(page).last() : page;
    const before = i > 0 && (await dlgOf(page).count()) ? await dlgOf(page).last().innerText().catch(() => "") : "";
    await pressButton(scope, flowPath[i]);
    if (i === 0) await waitDialog(page, 3000);
    else {
      // the sheet swaps its content: wait for it to change (up to 7 s on a loaded box), then let it settle
      for (let t = 0; t < 7000; t += 400) {
        await sleep(400);
        if (!(await dlgOf(page).count()) || (await dlgOf(page).last().innerText().catch(() => before)) !== before) break;
      }
      await sleep(700);
    }
  }
  return (await dlgOf(page).count()) ? dlgOf(page).last() : null;
}

// The sheets and forms a page offers, found once per page and size class and kept for a day: each is a path of button
// names and what is inside (text fields, Save-like buttons). One level of sheet inside a sheet is followed (the + sheet's forms).
async function discoverFlows(ctx, route) {
  const { tab } = ctx;
  const page = tab.page;
  const key = `${ctx.cell.role}|${route.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id")}|${tab.dev.phone ? "phone" : "desktop"}`;
  const known = state.flows[key];
  if (known && known.v === 3 && Date.now() - known.at < 24 * 3600 * 1000) return known.list;
  const list = [];
  if (!(await loadPage(ctx, route))) return [];
  await sleep(600);
  // a form on the page itself counts when it has a Save-like button (a search box is not a form to lose)
  const pageFields = await page.locator("main").locator(FORM_FIELD).filter({ visible: true }).count();
  const pageSaves = await page.locator("main").getByRole("button", { name: STRONG }).filter({ visible: true }).count();
  const pageToggles = await page.locator("main [role=switch], main input[type=checkbox]").filter({ visible: true }).count();
  if (pageFields || (pageSaves && pageToggles)) list.push({ path: [], name: "(the form on the page)", kind: "page", fields: pageFields, submits: pageSaves });
  // the header's own sheets are the same on every page and are found on /dashboard; elsewhere look at what the page itself offers
  const cands = (await controls(page))
    .filter((c) => c.role === "button" && !c.href && c.name && !DANGER.test(c.name) && OPENER.test(c.name))
    .filter((c) => route === "/dashboard" || !HEADER_FLOW.some(([re]) => re.test(c.name)))
    .slice(0, 8);
  for (const c of cands) {
    try {
      const before = new URL(page.url()).pathname;
      await clickPath(page, [c.name]);
      if (!(await dlgOf(page).count())) {
        if (new URL(page.url()).pathname !== before) {
          await page.goBack().catch(() => null);
          await session.settle(tab, 8000);
        }
        continue;
      }
      const top = await dialogFacts(page);
      const entry = { path: [c.name], name: c.name, kind: "sheet", fields: top.fields, submits: top.submits };
      list.push(entry);
      if (!top.fields) {
        const subs = (
          await dlgOf(page).last().locator("button").evaluateAll((els) => els.filter((e) => e.checkVisibility && e.checkVisibility()).map((e) => (e.getAttribute("aria-label") || e.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60)))
        ).filter((n, i, all) => n && n !== c.name && SUB_OPENER.test(n) && !DANGER.test(n) && !/^(close|cancel|back|dismiss)\b/i.test(n) && all.indexOf(n) === i).slice(0, 4);
        for (const sub of subs) {
          const url0 = page.url();
          await clickPath(page, [c.name, sub]);
          const f2 = await dialogFacts(page);
          if (f2.open && (f2.fields || f2.submits)) list.push({ path: [c.name, sub], name: `${c.name} > ${sub}`, kind: "sheet", fields: f2.fields, submits: f2.submits });
          if (page.url() !== url0 && new URL(page.url()).pathname !== new URL(url0).pathname) {
            await page.goBack().catch(() => null);
            await session.settle(tab, 8000);
          }
          await closeDialogs(page);
          await clickPath(page, [c.name]);
        }
        // a sheet whose buttons open other sheets has nothing of its own to save
        if (list.some((f) => f.path.length === 2 && f.path[0] === c.name)) entry.submits = 0;
      }
      await closeDialogs(page);
    } catch (error) {
      ctx.note(`flow discovery on "${c.name}" stopped: ${String(error).split("\n")[0].slice(0, 80)}`);
      await closeDialogs(page).catch(() => null);
    }
  }
  // the forms the orchestrator named, by their opener names (1 Nov 2026): they are tried whether or not the page offered them above
  for (const [where, paths] of KNOWN_OPENERS) {
    if (!where.test(route)) continue;
    for (const p of paths) {
      try {
        if (list.some((f) => f.path.join(">") === p.join(">"))) continue;
        const first = page.getByRole("button", { name: p[0] }).filter({ visible: true });
        if (!(await first.count())) continue;
        const url0 = page.url();
        await clickPath(page, p);
        const f = await dialogFacts(page);
        if (f.open && (f.fields || f.submits)) list.push({ path: p, name: p.join(" > "), kind: "sheet", fields: f.fields, submits: f.submits });
        await closeDialogs(page);
        if (new URL(page.url()).pathname !== new URL(url0).pathname) {
          await page.goBack().catch(() => null);
          await session.settle(tab, 8000);
        }
      } catch (error) {
        ctx.note(`known opener "${p.join(" > ")}" stopped: ${String(error).split("\n")[0].slice(0, 80)}`);
        await closeDialogs(page).catch(() => null);
      }
    }
  }
  state.flows[key] = { v: 3, at: Date.now(), list };
  save();
  return list;
}

const KNOWN_OPENERS = [
  // the lead page's buttons read "Add a note", "Add a task for <name>", "Schedule a follow-up with <name>" and "Edit"; the names the orchestrator gave are tried too
  [/lead=/, [["Add a note"], ["Add note"], ["Add a task"], ["Add task"], ["Schedule a follow-up"], ["Follow-up"], ["Edit details"], ["Edit"], ["Details", "Edit"], ["Log a call"], ["We talked"], ["Task"]]],
  [/^\/dashboard/, [["Add a lead, a call or a task", "Add lead"], ["Add a lead, a call or a task", "Add a call"], ["Add a lead, a call or a task", "Add task"]]],
];

// prior: open another page of the app first, so that Back has somewhere to go, as it would for a person who came from there
async function openFlow(ctx, route, flow, prior = false) {
  const page = ctx.tab.page;
  if (prior && !(await loadPage(ctx, route === "/dashboard" ? "/leads" : "/dashboard", 20000))) return null;
  if (!(await loadPage(ctx, route))) return null;
  await sleep(500);
  if (flow.kind === "page") return page.locator("main");
  return clickPath(page, flow.path);
}

let markN = 0;
async function typeInto(root) {
  const fields = root.locator(FORM_FIELD).filter({ visible: true });
  const n = Math.min(await fields.count(), 3);
  const typed = [];
  typed.why = [];
  for (let i = 0; i < n; i++) {
    const field = fields.nth(i);
    const info = await field.evaluate((el) => ({ type: (el.getAttribute("type") || (el.tagName === "TEXTAREA" ? "textarea" : "text")).toLowerCase(), label: (el.getAttribute("aria-label") || el.placeholder || el.name || "field").slice(0, 30), ro: el.readOnly || el.disabled })).catch(() => null);
    if (!info || info.ro) {
      typed.why.push(info ? `"${info.label}" is read-only` : "a field could not be read");
      continue;
    }
    const mark = `QA draft ${++markN}`;
    const text = info.type === "tel" ? `98765${String(10000 + markN).slice(-5)}` : info.type === "email" ? `qa.draft${markN}@example.test` : info.type === "number" ? String(4500 + markN) : `${mark} — Rahul ko kal call karna hai`;
    const filled = await field.fill(text, { timeout: 4000 }).then(() => null, (e) => String(e).split("\n")[0].slice(0, 70));
    const got = await field.inputValue().catch(() => "");
    if (got) typed.push({ label: info.label, mark: info.type === "text" || info.type === "textarea" || info.type === "search" ? mark : text, chars: got.length });
    else typed.why.push(`"${info.label}" took no text${filled ? ` (${filled})` : ""}`);
  }
  typed.found = await fields.count();
  return typed;
}

const hasMarks = (page, typed) =>
  page
    .evaluate(
      (marks) => {
        const vals = [...document.querySelectorAll("input,textarea,[contenteditable=true]")].map((e) => e.value || e.textContent || "");
        const body = document.body.innerText || "";
        return marks.every((m) => vals.some((v) => v.includes(m)) || body.includes(m));
      },
      typed.map((t) => t.mark),
    )
    .catch(() => false);

const warnedIn = (page) =>
  page
    .evaluate(() => {
      const visible = (el) => el.getBoundingClientRect().width > 0 && el.checkVisibility && el.checkVisibility();
      return [...document.querySelectorAll("dialog[open],[role=dialog],[role=alertdialog]")].filter(visible).some((d) => /discard|unsaved|leave|lose|keep editing|are you sure|save (?:your )?changes/i.test(d.innerText || ""));
    })
    .catch(() => false);

async function trialHistory(ctx, route, flow) {
  const { tab } = ctx;
  const page = tab.page;
  const natives = [];
  const onDialog = (d) => {
    natives.push(d.type());
    d.accept().catch(() => null);
  };
  page.on("dialog", onDialog);
  try {
    // Back with text typed
    let root = await openFlow(ctx, route, flow, true);
    if (!root) return ctx.note(`${flow.name}: did not open`);
    if (ctx.verbose) {
      const df = await dialogFacts(page);
      ctx.note(`opened ${flow.name}: sheet open ${df.open}, fields ${df.fields}, save buttons ${df.submits}, address ${new URL(page.url()).pathname}`);
    }
    let typed = await typeInto(root);
    if (!typed.length) return ctx.note(`${flow.name}: no text typed (${typed.found} fields found; ${typed.why.join(", ") || "none to type in"})`);
    const chars = typed.reduce((a, t) => a + t.chars, 0);
    const where = typed.map((t) => `"${t.label}"`).join(", ");
    const openUrl = page.url();
    await page.goBack({ timeout: 15000 }).catch(() => null);
    await session.settle(tab, 8000);
    await sleep(900);
    let still = await hasMarks(page, typed);
    const warned = (await warnedIn(page)) || natives.includes("beforeunload");
    ctx.note(`${flow.name}: after Back the text is ${still ? "still there" : warned ? "gone, with a warning" : "gone"}, at ${new URL(page.url()).pathname}`);
    if (!still && !warned) {
      let draft = false;
      if (flow.kind === "sheet" && new URL(page.url()).pathname === new URL(openUrl).pathname) {
        // still on the page: open the sheet again (no reload) and see whether it kept what was typed
        const again = await clickPath(page, flow.path);
        draft = again ? await hasMarks(page, typed) : false;
      }
      if (!draft) {
        const left = new URL(page.url()).pathname !== new URL(openUrl).pathname;
        await ctx.add("flow:lost-on-back", chars >= 80 ? "MAJOR" : "MINOR", `${flow.name}`, `Typed ${chars} characters into ${where} in "${flow.name}"; Back ${left ? `left the page for ${new URL(page.url()).pathname}` : "closed it"} and the text was gone, with no warning and no saved draft`, false);
      }
    }
    // Forward after Back: the sheet comes back empty
    if (flow.kind === "sheet" && !still) {
      await page.goForward({ timeout: 8000 }).catch(() => null);
      await sleep(1200);
      if ((await dlgOf(page).count()) && !(await hasMarks(page, typed))) await ctx.add("flow:forward-empty", "MINOR", `${flow.name}`, `After Back, Forward reopens "${flow.name}" with the text typed before gone`, false);
    }
    // refresh with text typed
    natives.length = 0;
    root = await openFlow(ctx, route, flow);
    if (!root) return;
    typed = await typeInto(root);
    if (!typed.length) return;
    await page.reload({ waitUntil: "load", timeout: 60000 }).catch(() => null);
    await session.settle(tab, 10000);
    await sleep(900);
    still = await hasMarks(page, typed);
    ctx.note(`${flow.name}: after a refresh the text is ${still ? "still there" : natives.includes("beforeunload") ? "gone, with a warning before leaving" : "gone"}`);
    if (!still && !natives.includes("beforeunload")) {
      let draft = false;
      if (flow.kind === "sheet") {
        const again = await clickPath(page, flow.path);
        draft = again ? await hasMarks(page, typed) : false;
      }
      if (!draft) {
        const c2 = typed.reduce((a, t) => a + t.chars, 0);
        await ctx.add("flow:lost-on-refresh", c2 >= 80 ? "MAJOR" : "MINOR", `${flow.name}`, `Typed ${c2} characters into ${typed.map((t) => `"${t.label}"`).join(", ")} in "${flow.name}"; refreshing the page lost it, with no warning before leaving and no saved draft`, false);
      }
    }
  } finally {
    page.off("dialog", onDialog);
  }
}

async function trialDouble(ctx, route, flow) {
  const { tab } = ctx;
  const page = tab.page;
  const root = await openFlow(ctx, route, flow);
  if (!root) return ctx.note(`${flow.name}: did not open`);
  const typed = await typeInto(root);
  // only buttons that really save: "Add a task" and "Log a call" open other screens
  const buttons = root.getByRole("button", { name: STRONG }).filter({ visible: true });
  const total = await buttons.count();
  if (!total) {
    const names = await root.getByRole("button").filter({ visible: true }).evaluateAll((els) => els.map((e) => (e.getAttribute("aria-label") || e.textContent || "").replace(/\s+/g, " ").trim().slice(0, 28)).filter(Boolean).slice(0, 12)).catch(() => []);
    return ctx.note(`${flow.name}: no Save or Send button${typed.length ? " even with text typed" : ""}; buttons seen: ${names.join(" | ")}`);
  }
  for (let i = 0; i < Math.min(total, 2); i++) {
    const btn = buttons.nth(i);
    const name = await btn.evaluate((el) => (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40)).catch(() => "");
    if (!name || DANGER.test(name) || /whatsapp|invite|message to/i.test(name)) continue;
    if (!(await btn.isEnabled().catch(() => false))) {
      ctx.note(`"${name}" is disabled${typed.length ? " even with text typed" : ""}: not pressed`);
      continue;
    }
    const box = await btn.boundingBox().catch(() => null);
    if (!box) continue;
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    tab.holds.clear();
    await page.mouse.click(x, y).catch(() => null);
    await sleep(120);
    const same = await btn
      .evaluate(
        (el, pt) => {
          const t = document.elementFromPoint(pt.x, pt.y);
          return !!t && (el === t || el.contains(t) || t.contains(el));
        },
        { x, y },
      )
      .catch(() => false);
    if (!same) {
      ctx.note(`"${name}": the screen changed after the first press, no second press`);
      await sleep(1400);
      continue;
    }
    await page.mouse.click(x, y).catch(() => null);
    await sleep(1600);
    const entries = [...tab.holds.entries()];
    if (!entries.length) {
      ctx.note(`"${name}": no write was sent (a check refused it first)`);
    } else {
      const writes = entries.map(([, e]) => e);
      const same = entries.find(([, e]) => e.n >= 2);
      const differing = !same && writes.length >= 2 && writes.every((w) => w.path === writes[0].path);
      const sent = writes.reduce((a, w) => a + w.n, 0);
      if (same) {
        // the same body twice: if it carries a command id, the server can drop the second one
        const keyed = /command_id|idempotency/i.test(same[0]);
        await ctx.add("submit:double", keyed ? "MINOR" : "MAJOR", `"${name}" in ${flow.name}`, `Pressed twice in 120 ms: ${same[1].method} ${same[1].path} was sent ${sent} times with the same body${keyed ? " (it carries a command id, so the server should drop the second: check that it does)" : " and no command id"}; the button should not allow a second press`, true);
      } else if (differing) {
        await ctx.add("submit:double", "MAJOR", `"${name}" in ${flow.name}`, `Pressed twice in 120 ms: ${writes[0].method} ${writes[0].path} was sent ${sent} times with different bodies (a new command id each time), so the server will do it twice`, true);
      } else ctx.note(`"${name}": ${sent} write, once`);
    }
    await sleep(1400);
    break;
  }
}

// Sheets that live in the app's header or bottom bar are the same on every page: they are tested on /dashboard only, and a
// finding in one is filed once, under /dashboard and the area that owns the sheet.
const HEADER_FLOW = [
  [/^Workspace:/i, "Settings"],
  [/^Account|log ?out/i, "Settings"],
  [/notifications?/i, "Notifications"],
  [/report a problem|bug/i, "Bug reporter"],
  [/ask dipak/i, "Ask Dipak"],
  [/add a lead, a call or a task/i, "Leads"],
];
const headerAreaOf = (flow) => {
  const h = HEADER_FLOW.find(([re]) => re.test((flow.path && flow.path[0]) || ""));
  return h ? h[1] : null;
};

async function famFlow(ctx, route, which) {
  const all = await discoverFlows(ctx, route);
  // a form is work worth keeping when it has something to type in and a Save-like button; a search box or a filter is not
  const flows = all.filter((f) => (which === "history" ? f.fields > 0 : f.submits > 0 || f.fields > 0)).filter((f) => route === "/dashboard" || !headerAreaOf(f));
  if (!flows.length) return ctx.note(all.length ? `${all.length} sheets found, none with ${which === "history" ? "a text field" : "a Save or Send button"}` : "no sheet or form on this page");
  const cursorKey = `${ctx.cell.role}|${route}|${ctx.cell.size}|${which}`;
  const at = (state.cursor[cursorKey] || 0) % flows.length;
  state.cursor[cursorKey] = at + 1;
  const flow = flows[at];
  ctx.note(`flow ${at + 1} of ${flows.length}: ${flow.name}`);
  const head = headerAreaOf(flow);
  if (head) {
    ctx.area = head;
    ctx.routeOverride = "/dashboard";
  }
  if (which === "history") await trialHistory(ctx, route, flow);
  else await trialDouble(ctx, route, flow);
}

const FAMILY = {
  fault: famFault,
  "3g": fam3g,
  extremes: famExtremes,
  zoom: famZoom,
  keyboard: famKeyboard,
  dark: famDark,
  history: (ctx, route) => famFlow(ctx, route, "history"),
  double: (ctx, route) => famFlow(ctx, route, "double"),
};

// ---- roll-up and filing -----------------------------------------------------------------------------------------------
const SUMMARY = {
  "fault:blank": "The page goes blank when a call fails",
  "fault:crash": "The page crashes when a call fails",
  "fault:stuck-loading": "The page stays on its loading mark when a call fails",
  "fault:raw-error": "The page shows raw error words when a call fails",
  "fault:silent": "Part of the page vanishes with no message when a call fails",
  "fault:false-empty": "The page says there is nothing when the call failed or is slow",
  "fault:retry-fails": "Retry does not recover the page",
  "fault:unhandled-error": "A call failing throws an unhandled script error",
  "fault:blank-while-waiting": "The page is blank while a slow call is waiting",
  "fault:no-recovery": "The page never fills when a slow call finally answers",
  "net3g:blank-while-loading": "On 3G the page is blank while it loads",
  "net3g:false-empty": "On 3G the page says there is nothing while the call is still on its way",
  "net3g:layout-shift": "On 3G the layout jumps while it loads",
  "data:blank": "Extreme data makes the page go blank",
  "data:crash": "Extreme data crashes the page",
  "data:unhandled-error": "Extreme data throws an unhandled script error",
  "data:overflow-x": "Extreme data makes the page scroll sideways",
  "data:text-clipped": "Extreme data gets text cut off",
  "data:overlap": "Extreme data makes controls overlap",
  "data:covered": "Extreme data leaves controls covered",
  "kbd:no-focus-indicator": "Controls show nothing when they take keyboard focus",
  "kbd:trap": "Keyboard focus is trapped",
  "kbd:unreachable": "Controls cannot be reached with the Tab key",
  "kbd:clickable-not-focusable": "Click-only elements cannot be used with a keyboard",
  "kbd:focus-covered": "Keyboard focus lands under something else",
  "kbd:focus-lost": "Keyboard focus goes to something that cannot be seen",
  "dark:light-island": "Light panels stay white in dark mode",
  "dark:light-field": "Fields stay white in dark mode",
  "dark:contrast": "Text fails contrast in dark mode only",
  "flow:lost-on-back": "Back loses typed text with no warning",
  "flow:lost-on-refresh": "Refreshing loses typed text with no warning",
  "flow:forward-empty": "Forward reopens a sheet empty",
  "submit:double": "Pressing Save twice sends the request twice",
};
function summaryOf(rule, route, size) {
  const m = /^zoom(\d+):(.*)$/.exec(rule);
  if (m) return `${route} at ${size}, text at ${m[1]} %: ${m[2] === "overflow-x" ? "the page scrolls sideways" : m[2] === "text-cut" ? "text is cut off at the top or bottom" : m[2] === "text-clipped" ? "text is cut off at the side" : m[2] === "overlap" ? "controls overlap" : "controls are covered"}`;
  return `${route} at ${size}: ${SUMMARY[rule] || rule}`;
}

const RANK = { BLOCKER: 4, MAJOR: 3, MINOR: 2, POLISH: 1 };
function areaFor(route, ctx) {
  if (ctx.area) return ctx.area;
  if (/part=stages/.test(route)) return "Stage editor";
  return sim.areaOfRoute(route);
}

async function fileAll(ctx, cell, route, dry) {
  const groups = new Map();
  for (const it of ctx.items) {
    if (!groups.has(it.rule)) groups.set(it.rule, []);
    groups.get(it.rule).push(it);
  }
  const out = [];
  const sizeKey = cfg.DEVICES[cell.size].key;
  for (const [rule, items] of groups) {
    const worst = items.reduce((a, b) => (RANK[b.severity] > RANK[a] ? b.severity : a), items[0].severity);
    const finding = {
      rule,
      selector: `@${sizeKey}`,
      severity: worst,
      summary: summaryOf(rule, route, sizeKey),
      // injected text can hold zero-width marks and half emoji; the reporter answers 500 to some of them, and nobody reads them
      detail: items
        .slice(0, 12)
        .map((i) => (i.detail ? `${i.what}: ${i.detail}` : i.what))
        .join(" | ")
        .replace(/[​-‏‪-‮⁠-⁤﻿­]/g, "")
        .replace(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g, "")
        .slice(0, 2600),
      route,
      shot: null,
      shotAll: [],
      count: items.length,
      rolled: true,
    };
    if (dry) {
      log(`    [dry] ${rule} ${worst} x${items.length}: ${finding.detail.slice(0, 300)}`);
      out.push({ rule, action: "dry" });
      continue;
    }
    const res = await report.file(finding, {
      tab: ctx.tab,
      alias: ctx.alias,
      filer: ctx.alias,
      persona: "attack",
      device: cell.size,
      theme: cell.family === "dark" ? "dark" : "light",
      area: areaFor(route, ctx),
      workflow: null,
      seed: null,
      steps: ctx.notes.slice(-8),
      png: ctx.pngs.get(rule) || null,
    });
    log(`  ${res.action} ${res.bugId || ""} ${rule} ${route} @${sizeKey} (${items.length})${res.reason ? ` (${res.reason})` : ""}`);
    out.push({ rule, action: res.action, bugId: res.bugId });
  }
  return out;
}

// ---- one cell -------------------------------------------------------------------------------------------------------
async function runCell(cell, opts = {}) {
  const t0 = Date.now();
  const owner = cell.role === "owner";
  const alias = owner ? "owner" : SELLERS[aliasTurn++ % SELLERS.length];
  let route = cell.route;
  const tab = await session.openTab({ alias, device: cell.size, theme: cell.family === "dark" ? "dark" : "light", state: "normal", keep: true });
  const ctx = makeCtx(tab, cell, alias);
  ctx.verbose = !!opts.verbose;
  let result = { items: 0, filed: [] };
  try {
    await prepare(tab);
    if (route.includes("{lead}")) {
      const opened = await session.go(tab, "/leads", { wait: 25000 });
      const id = opened.ok ? await clickmap.leadFor(tab, owner) : null;
      if (!id) {
        ctx.note("no lead to open for this person");
        if (!opts.dry) {
          state.cells[keyOf(cell)] = { at: Date.now(), items: 0, skipped: "no lead" };
          save();
        }
        return { skipped: "no lead" };
      }
      route = route.replace("{lead}", id);
    }
    const run = async () => {
      ctx.items = [];
      ctx.pngs = new Map();
      await FAMILY[cell.family](ctx, route);
    };
    await run();
    // a failure while dev rebuilds says nothing about the app: wait it out and look once more
    if (ctx.items.length && (await rebuilding(tab))) {
      ctx.note("dev was rebuilding: findings held, looked again after the rebuild");
      await waitOutRebuild(tab, 150000);
      await run();
    }
    const shown = ctx.routeOverride || route.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id");
    result.items = ctx.items.length;
    if (ctx.items.length) result.filed = await fileAll(ctx, cell, shown, !!opts.dry);
    if (!opts.dry) {
      state.cells[keyOf(cell)] = { at: Date.now(), items: ctx.items.length, ms: Date.now() - t0 };
      save();
    }
  } finally {
    await session.closeTab(tab).catch(() => null);
  }
  log(`attack ${cell.family} ${cell.role} ${route.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id")} ${cell.size} as ${alias}: ${result.items} findings in ${Math.round((Date.now() - t0) / 1000)} s${ctx.notes.length && opts.verbose ? "" : ""}`);
  return result;
}

async function runOne(opts = {}) {
  const cell = pickCell(opts.filter || {});
  if (!cell) return null;
  try {
    return await runCell(cell, opts);
  } catch (error) {
    if (String(error.message) === "stop") return { stopped: true };
    log(`attack ${cell.family} ${cell.role} ${cell.route} ${cell.size} broke: ${String(error).split("\n")[0].slice(0, 160)}`);
    return { error: true };
  }
}

module.exports = { runOne, runCell, pickCell, digestLine, FAMILIES, SIZES, PAGES };
