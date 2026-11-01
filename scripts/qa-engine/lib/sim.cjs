// Persona simulator: a seeded random walk through the app as one fictional person. Each walk takes a row of the
// matrix (persona, device, theme, state, journey area) and behaves like that person: how fast they type, how often
// they tap wrong, double-tap or press Back, and what they type (Marathi, Hindi, Hinglish, other scripts, long
// names, emoji, pasted numbers). After every step the invariants run (lib/invariants.cjs); every violation is
// filed through the app's reporter with a picture, the element outlined, the persona, the seed and the steps.
// Read-only by construction: a write to the API is held 1.2 s and then refused, so double submits are counted
// (a second identical write inside the hold means the button was not guarded) and nothing is ever saved.
// Seeds are logged: `engine.cjs sim --seed N --persona P05 --device "390 px" --theme dark --area Leads` replays one.
const fs = require("fs");
const path = require("path");
const cfg = require("./config.cjs");
const session = require("./session.cjs");
const matrix = require("./matrix.cjs");
const personas = require("./personas.cjs");
const report = require("./report.cjs");
const inv = require("./invariants.cjs");
const { headroom, snapshot, sleep } = require("./guard.cjs");
const { probe, axeFindings, routeOf } = require("./probe.cjs");
const { controls, pickAgain } = require("./crawler.cjs");
const { rebuilding, waitOutRebuild } = require("./rebuild.cjs");

const START = {
  Home: ["/dashboard"],
  Leads: ["/leads", "/leads?tab=all"],
  "Prospect's Information": ["/leads?view=all"],
  "After-Call": ["/leads?view=all"],
  Tasks: ["/leads?tab=tasks"],
  "Follow-ups": ["/leads?view=follow_ups"],
  Reports: ["/reports", "/analysis/calls"],
  Growth: ["/coaching"],
  Performance: ["/performance"],
  "Owner controls": ["/organisation", "/organisation?tab=members"],
  "Stage editor": ["/organisation?tab=leads&part=stages"],
  "Lead import": ["/leads"],
  "Bug reporter": ["/dashboard"],
  "Capture setup": ["/dashboard"],
  "Sign-in": ["/dashboard"],
  Settings: ["/account"],
  Notifications: ["/dashboard"],
  "Ask Dipak": ["/dashboard"],
};
const OWNER_AREAS = new Set(["Reports", "Owner controls", "Stage editor", "Lead import"]);
const POOL = {
  seller: ["/dashboard", "/leads", "/leads?tab=tasks", "/leads?view=follow_ups", "/performance", "/reports", "/coaching", "/account"],
  owner: ["/dashboard", "/leads", "/performance", "/reports", "/organisation", "/organisation?tab=members", "/account"],
};
// Never pressed: they end the session, call, message, pay, delete or leave the app.
const NEVER = /log ?out|sign ?out|delete|remove|erase|reset|close account|call|dial|whatsapp|pay\b|buy|upgrade|checkout|upload|revoke|disconnect|unlink|archive|transfer|start (?:cold|calling)|record\b/i;
const EXPECTED_ERRORS = [/Failed to fetch|NetworkError|Load failed|AbortError|ERR_BLOCKED|ERR_INTERNET_DISCONNECTED/i];
const KNOWN_HTTP = [/^404 GET \/v1\/bug-reports\/advanced/];

// ---- randomness and the person -----------------------------------------------------------------------------------
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const pick = (r, list) => list[Math.floor(r() * list.length)];

const TEXT = {
  english: ["Rahul Sharma", "Call back tomorrow", "Interested in the course", "Needs fee details"],
  marathi: ["सुनिता पाटील", "उद्या फोन करा", "फी किती आहे?", "अमोल जाधव"],
  hindi: ["राहुल शर्मा", "कल फोन करना है", "फीस कितनी है?", "प्रिया वर्मा"],
  hinglish: ["Rahul ko kal call karna hai", "fees kitni hai bhai", "demo dena hai", "Priya ne WhatsApp pe bola"],
  tamil: ["லக்ஷ்மி நாராயணன்", "நாளை அழைக்கவும்"],
  telugu: ["వెంకట్ రెడ్డి", "రేపు ఫోన్ చేయండి"],
  bengali: ["অনিন্দিতা দাস", "আগামীকাল ফোন করুন"],
  malayalam: ["ലക്ഷ്മി നായർ", "നാളെ വിളിക്കുക"],
  numbers: ["+91 98765 43210", "98765-43210", "९८७६५४३२१०", "0091 98765 43210", " 98765 43210 "],
  emoji: ["🔥📞 Rahul 😀👍🏽", "Call 📞 now 🙏", "❤️‍🔥 hot lead ✅"],
  long: ["Venkatasubramanian Raghunathan Iyengar Chandrasekaran Thiruvengadam", "Mohammad Abdul Rahman Siddiqui Al-Hashmi Bin Sulaiman Khan Pathan", "A".repeat(60)],
  huge: ["x".repeat(500), "Lorem ipsum dolor sit amet ".repeat(20)],
};

function profileFor(p, row) {
  const tags = p.tags || "";
  const lang = (p.language || "").toLowerCase();
  const tech = (p.tech_level || "").toLowerCase();
  const patience = (p.patience || "").toLowerCase();
  const slowTyper = /[nlw]/.test(tags) || tech === "low";
  const primary = /marathi/.test(lang) ? "marathi" : /tamil/.test(lang) ? "tamil" : /telugu/.test(lang) ? "telugu" : /bengali/.test(lang) ? "bengali" : /malayalam/.test(lang) ? "malayalam" : /hinglish/.test(lang) ? "hinglish" : /hindi/.test(lang) ? "hindi" : "english";
  return {
    id: p.id,
    delay: /t/.test(tags) ? 8 : slowTyper ? 130 : 55,
    err: /t/.test(tags) ? 0.22 : /n/.test(tags) ? 0.12 : tech === "low" ? 0.1 : 0.05,
    primary,
    longNames: /[dq]/.test(tags) || row.state === "long names",
    huge: /q/.test(tags),
    steps: patience === "low" ? 28 : patience === "high" ? 55 : 40,
    speed: /t/.test(tags) ? "fast" : slowTyper ? "slow" : "normal",
  };
}

function inputFor(r, prof) {
  const x = r();
  if (x < 0.5) return { kind: prof.primary, text: pick(r, TEXT[prof.primary]) };
  if (x < 0.65) return { kind: "numbers", text: pick(r, TEXT.numbers), paste: true };
  if (x < 0.75) return { kind: "emoji", text: pick(r, TEXT.emoji) };
  if (x < 0.9 || prof.longNames) return { kind: "long", text: pick(r, TEXT.long) };
  return { kind: prof.huge ? "huge" : "english", text: pick(r, prof.huge ? TEXT.huge : TEXT.english) };
}

// ---- writes are held and refused ---------------------------------------------------------------------------------
async function holdWrites(tab) {
  tab.holds = new Map();
  tab.writes = 0;
  await tab.context.route("**/v1/**", async (route) => {
    const req = route.request();
    const method = req.method();
    if (method === "GET" || method === "HEAD" || method === "OPTIONS") return route.continue();
    const p = new URL(req.url()).pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ":id");
    const key = `${method} ${p} ${(req.postData() || "").slice(0, 160)}`;
    const e = tab.holds.get(key) || { n: 0, method, path: p };
    e.n += 1;
    tab.holds.set(key, e);
    tab.writes += 1;
    await sleep(1200);
    await route.abort("blockedbyclient").catch(() => null);
  });
}

// ---- one walk ----------------------------------------------------------------------------------------------------
async function loadGap(tab) {
  const page = tab.page;
  const quick = () => page.evaluate(() => ({ t: ((document.querySelector("main") || document.body).innerText || "").replace(/\s+/g, " ").trim().length, load: document.querySelectorAll('[role=progressbar],[role=status],[aria-busy="true"],[class*="skeleton" i],[class*="spinner" i],[class*="shimmer" i]').length })).catch(() => null);
  const a = await quick();
  if (!a || a.t >= 25 || a.load > 0 || tab.inflight === 0) return false;
  await sleep(1300);
  const b = await quick();
  return !!b && b.t < 25 && b.load === 0;
}

async function walk(job) {
  const { row, alias, persona, prof, seed, area, filer } = job;
  const r = rng(seed);
  const owner = alias === "owner";
  const tokens = new Set((row.journey || "").toLowerCase().match(/[a-z]{4,}/g) || []);
  const tab = await session.openTab({ alias, device: row.device, theme: row.theme, state: row.state, keep: true });
  const page = tab.page;
  const phone = tab.dev.phone;
  const steps = [];
  const out = { seed, steps: 0, found: 0, filed: 0, counted: 0, held: 0, bugs: [], rowBugs: [], byCheck: {}, writes: 0, journeyArea: area };
  const mine = new Set();
  const axeSeen = new Set();
  const note = (text) => steps.push(`${steps.length + 1}. ${text}`);
  let lastMark = tab.mark();
  const t0 = Date.now();
  const file = async (finding, extra = {}) => {
    const key = `${finding.rule}|${finding.route}|${finding.selector}`;
    if (mine.has(key)) return;
    mine.add(key);
    out.found++;
    const res = await report.file(finding, {
      tab,
      alias,
      filer,
      persona: persona.id,
      device: row.device,
      theme: row.theme,
      area: areaOfRoute(finding.route),
      workflow: row.workflow_id,
      seed,
      steps: steps.slice(-10),
      ...extra,
    });
    out[res.action === "failed" ? "held" : res.action] = (out[res.action === "failed" ? "held" : res.action] || 0) + 1;
    out.byCheck[finding.rule] = (out.byCheck[finding.rule] || 0) + 1;
    if (res.bugId) {
      out.bugs.push(res.bugId);
      if (["BLOCKER", "MAJOR"].includes(finding.severity) && areaOfRoute(finding.route) === row.area) out.rowBugs.push(res.bugId);
    }
    log(`  ${res.action} ${res.bugId || ""} ${finding.rule} ${finding.route} ${finding.selector}${res.reason ? ` (${res.reason})` : ""}`);
  };

  // what the page and the log say after a step
  const inspect = async (again = false) => {
    const route = routeOf(page.url());
    if (/^about:blank/.test(page.url())) {
      note("the tab was on about:blank (a navigation was aborted): nothing to judge");
      return null;
    }
    let s = await page.evaluate(inv.scan, phone).catch(() => null);
    // a page that looks blank on a busy box may just be slow: look again for up to 9 s before calling it blank
    const patience = tab.opts.state === "slow network" ? 30 : 12;
    for (let wait = 0; s && s.textLength < 25 && wait < patience; wait++) {
      await sleep(1000);
      s = await page.evaluate(inv.scan, phone).catch(() => s);
    }
    // still loading (calls in flight) is not blank: that is a missing loading mark at worst, judged elsewhere
    if (s && s.textLength < 25 && tab.inflight > 0) s.textLength = 25;
    const q = await page
      .evaluate(() => {
        const x = window.__qa || { cls: 0, events: [] };
        const o = { cls: x.cls, events: x.events.splice(0) };
        x.cls = 0;
        return o;
      })
      .catch(() => ({ cls: 0, events: [] }));
    let found = s ? inv.rollup(inv.findingsFrom(s, { route, phone, shift: q.cls, events: q.events }), tab.dev.key) : [];
    const seen = tab.since(lastMark);
    lastMark = tab.mark();
    for (const e of seen.pageerrors) if (!EXPECTED_ERRORS.some((re) => re.test(e))) found.push({ rule: "script:page-error", selector: e.replace(/\d+/g, "#").slice(0, 60), severity: "MAJOR", summary: "A script error or unhandled rejection was thrown", detail: e, route });
    for (const e of [...new Set(seen.console)]) if (!EXPECTED_ERRORS.some((re) => re.test(e))) found.push({ rule: "script:console-error", selector: e.replace(/\d+/g, "#").slice(0, 60), severity: "MINOR", summary: "The page logged an error", detail: e, route });
    for (const h of seen.http) {
      if (KNOWN_HTTP.some((re) => re.test(`${h.status} ${h.method} ${h.path}`))) continue;
      if (h.status === 502 || h.status === 503 || h.status === 504) continue; // the dev API restarting, not the app
      found.push({ rule: `api:${h.status >= 500 ? "5xx" : "4xx"}`, selector: `${h.method} ${h.path}`, severity: h.status >= 500 ? "MAJOR" : "MINOR", summary: `The app got HTTP ${h.status} from ${h.method} ${h.path}`, detail: `${h.method} ${h.path} -> ${h.status}`, route });
    }
    // an offline walk: the browser's own offline page has no title or language, and every call fails by design
    if (row.state === "offline") found = found.filter((f) => !/^(page:|axe:|script:|api:)/.test(f.rule));
    if (!again && found.length && (await rebuilding(tab))) {
      note("dev was rebuilding: findings held, looked again after the rebuild");
      await waitOutRebuild(tab, 150000);
      return inspect(true);
    }
    for (const f of found) await file(f);
    // axe once per screen state (the screen, whether a sheet is open, the theme) across all walkers for 30 minutes
    const sig = `${route}|${s ? s.dialog : 0}|${row.device}|${row.theme}`;
    if (row.state !== "offline" && !axeSeen.has(sig) && Date.now() - (axeCache.get(sig) || 0) > 30 * 60 * 1000) {
      axeSeen.add(sig);
      axeCache.set(sig, Date.now());
      for (const f of await axeFindings(tab, route)) if (!f.internal) await file(f);
    }
    return s;
  };

  try {
    const startRoute = pick(r, START[area] || ["/dashboard"]);
    note(`open ${startRoute} as ${persona.name} (${row.device}, ${row.theme}${row.state !== "normal" ? `, ${row.state}` : ""})`);
    const first = await session.go(tab, startRoute, { wait: 30000, onLoad: async () => ((await loadGap(tab)) ? await file({ rule: "state:no-loading", selector: "page", severity: "MINOR", summary: "The page is empty while it loads: no skeleton or loading mark", detail: "Nothing but blank space for over a second while data was still loading.", route: routeOf(startRoute) }) : null) });
    // a timeout on a loaded box says nothing about the app: log it, never file it
    if (!first.ok && !/Timeout|timed out|has been closed|Target closed|ERR_ABORTED|ERR_CONNECTION/i.test(first.error)) await file({ rule: "page:load", selector: "", severity: "MAJOR", summary: "The page did not open", detail: first.error, route: routeOf(startRoute) });
    else if (!first.ok) note(`the page timed out (${first.error.slice(0, 60)})`);
    if (row.state === "offline") {
      await tab.context.setOffline(true);
      note("lost the connection");
    }
    await holdWrites(tab);
    await inspect();
    for (let n = 0; n < prof.steps; n++) {
      if ((await headroom(() => {})) === "stop" || Date.now() - t0 > 6 * 60 * 1000) break;
      const route = routeOf(page.url());
      if (!new URL(page.url()).origin.startsWith(new URL(cfg.PROXY).origin)) {
        await session.go(tab, pick(r, POOL[owner ? "owner" : "seller"]));
        note("came back to the app");
        continue;
      }
      let list = await controls(page);
      list = list.filter((c) => !NEVER.test(c.name) && !(c.href && (/^(tel:|mailto:|sms:|whatsapp:)/i.test(c.href) || (/^https?:/i.test(c.href) && !c.href.startsWith(cfg.PROXY)))));
      const x = r();
      const typed = page.locator("input[type=text],input[type=search],input:not([type]),textarea").filter({ visible: true });
      const hasText = await typed.count().catch(() => 0);
      if (x < prof.err * 0.45 && list.length) {
        // a wrong tap: near a control, not on it
        const c = pick(r, list);
        const box = await pickAgain(page, c).boundingBox().catch(() => null);
        if (box) {
          const dx = (r() - 0.5) * box.width * 2.4;
          const dy = (r() - 0.5) * box.height * 2.4;
          await page.mouse.click(Math.max(1, box.x + box.width / 2 + dx), Math.max(1, box.y + box.height / 2 + dy)).catch(() => null);
          note(`tapped beside "${c.name.slice(0, 30)}" by mistake`);
        }
      } else if (x < prof.err * 0.7) {
        await page.goBack({ timeout: 8000 }).catch(() => null);
        note("pressed Back");
      } else if (x < prof.err && list.length) {
        // a double tap on a control: the app should send one request, not two
        const c = pick(r, list.filter((e) => e.role === "button" || e.role === "link").concat(list));
        const target = pickAgain(page, c);
        if (await target.count()) {
          tab.holds.clear();
          await target.dblclick({ timeout: 6000, delay: 60 }).catch(() => null);
          note(`double-tapped ${c.role} "${c.name.slice(0, 30)}"`);
          await sleep(1400);
          for (const e of tab.holds.values()) {
            if (e.n >= 2) await file({ rule: "sim:double-submit", selector: `${c.role} "${c.name.slice(0, 30)}"`, severity: "MAJOR", summary: "Pressing it twice sends the request twice", detail: `${e.method} ${e.path} was sent ${e.n} times by a double tap`, route: routeOf(page.url()), shot: null });
          }
        }
      } else if (x < prof.err + 0.12 && hasText) {
        const field = typed.nth(Math.floor(r() * hasText));
        const input = inputFor(r, prof);
        const label = await field.evaluate((el) => (el.getAttribute("aria-label") || el.placeholder || el.name || el.type || "field").slice(0, 30)).catch(() => "field");
        await field.click({ timeout: 5000 }).catch(() => null);
        // with a sheet or card over the field the keys land elsewhere: judge only when the field really has focus
        const focused = await field.evaluate((el) => document.activeElement === el).catch(() => false);
        if (!focused) note(`"${label}" did not take focus (something is over it): not judged`);
        const handle = await field.elementHandle({ timeout: 3000 }).catch(() => null);
        const urlBefore = page.url();
        const text = prof.speed === "slow" ? input.text.slice(0, 40) : input.text;
        if (input.paste) await field.fill(text).catch(() => null);
        else await page.keyboard.type(text, { delay: prof.delay }).catch(() => null);
        note(`${input.paste ? "pasted" : "typed"} ${input.kind} text into "${label}"`);
        let enter = false;
        if (r() < 0.4) {
          enter = true;
          await page.keyboard.press("Enter").catch(() => null);
          note("pressed Enter");
        }
        await sleep(900);
        // lost only if it is the same field, still on the page, on the same address, and nobody pressed Enter
        const kept = handle ? await handle.inputValue().catch(() => null) : null;
        const same = handle ? await handle.evaluate((el) => el.isConnected).catch(() => false) : false;
        if (focused && kept === "" && same && !enter && page.url() === urlBefore && text.length > 2) {
          await file({ rule: "sim:input-lost", selector: `field "${label}"`, severity: "MINOR", summary: "Typed text disappeared from the field", detail: `Typed ${input.kind} text (${text.length} characters); a moment later the field was empty.`, route });
        }
      } else if (x < prof.err + 0.22) {
        await page.mouse.wheel(0, Math.round((r() - 0.3) * 1400)).catch(() => null);
        note("scrolled");
      } else if (x < prof.err + 0.26) {
        const to = pick(r, POOL[owner ? "owner" : "seller"]);
        await session.go(tab, to, { wait: 25000, onLoad: async () => ((await loadGap(tab)) ? await file({ rule: "state:no-loading", selector: "page", severity: "MINOR", summary: "The page is empty while it loads: no skeleton or loading mark", detail: "Nothing but blank space for over a second while data was still loading.", route: routeOf(to) }) : null) });
        note(`opened ${to} directly`);
      } else if (list.length) {
        const dlg = await page.getByRole("dialog").filter({ visible: true }).count();
        const weights = list.map((c) => {
          let w = c.role === "link" || c.role === "tab" || c.role === "radio" ? 3 : 2;
          for (const t of (c.name.toLowerCase().match(/[a-z]{4,}/g) || [])) if (tokens.has(t)) w += 4;
          if ((tab.recent || []).includes(`${route}|${c.name}`)) w = 0.3;
          return w;
        });
        let roll = r() * weights.reduce((a, b) => a + b, 0);
        let index = 0;
        for (; index < list.length - 1 && roll > weights[index]; index++) roll -= weights[index];
        const c = list[index];
        (tab.recent ||= []).push(`${route}|${c.name}`);
        if (tab.recent.length > 12) tab.recent.shift();
        const target = pickAgain(page, c);
        const mark = Date.now();
        await target.click({ timeout: 6000 }).catch(() => null);
        note(`tapped ${c.role} "${c.name.slice(0, 40)}"${dlg ? " (a sheet was open)" : ""}`);
        if (await loadGap(tab)) await file({ rule: "state:no-loading", selector: `after ${c.role} "${c.name.slice(0, 30)}"`, severity: "MINOR", summary: "The screen is empty while it loads: no skeleton or loading mark", detail: `After tapping "${c.name.slice(0, 40)}" the page was blank for over a second while data loaded.`, route: routeOf(page.url()) });
        void mark;
      } else {
        await page.keyboard.press("Escape").catch(() => null);
        note("pressed Escape");
      }
      await session.settle(tab, 6000);
      if (r() < 0.15) {
        await page.keyboard.press("Escape").catch(() => null);
      }
      await inspect();
    }
  } finally {
    out.steps = steps.length;
    out.writes = tab.writes || 0;
    await session.closeTab(tab).catch(() => null);
  }
  out.log = steps;
  return out;
}

const axeCache = new Map();
const log = (text) => console.log(`${new Date().toISOString().slice(11, 19)} ${text}`);

function areaOfRoute(route) {
  const u = new URL(route, "http://x");
  const p = u.pathname;
  const q = u.searchParams;
  if (p.startsWith("/dashboard")) return "Home";
  if (p.startsWith("/leads")) return q.get("tab") === "tasks" ? "Tasks" : q.get("view") === "follow_ups" || q.get("tab") === "follow_ups" ? "Follow-ups" : q.get("lead") ? "Prospect's Information" : "Leads";
  if (p.startsWith("/performance")) return "Performance";
  if (p.startsWith("/reports") || p.startsWith("/analysis")) return "Reports";
  if (p.startsWith("/coaching")) return "Growth";
  if (p.startsWith("/organisation")) return "Owner controls";
  if (p.startsWith("/account") || p.startsWith("/settings") || p.startsWith("/plans")) return "Settings";
  return "Home";
}

// ---- rows, workers --------------------------------------------------------------------------------------------
const SEEN_FILE = path.join(cfg.STATE, "sim-seen.json");
const seenRows = new Set((() => { try { return JSON.parse(fs.readFileSync(SEEN_FILE, "utf8")); } catch { return []; } })());
let rowList = [];
let rowListAt = 0;
let counter = Number(process.env.QA_SEED_BASE || Date.now() % 1000000);

async function nextRow(sizes) {
  if (Date.now() - rowListAt > 10 * 60 * 1000 || !rowList.length) {
    rowList = (await matrix.list({ status: "not run", devices: sizes.join(",") })).filter((x) => !seenRows.has(x.workflow_id));
    rowListAt = Date.now();
    if (!rowList.length) {
      seenRows.clear();
      rowList = await matrix.list({ status: "not run", devices: sizes.join(",") });
    }
  }
  let ownerOk = false;
  try {
    ownerOk = fs.existsSync("/tmp/pw/owner-cookie.txt");
  } catch {
    ownerOk = false;
  }
  if (!ownerOk && rowList.length) {
    const table = await personas.load();
    rowList = rowList.filter((x) => !OWNER_AREAS.has(x.area) && !(table.get(x.persona) || {}).owner);
  }
  if (!rowList.length) return null;
  const base = { P0: 3, P1: 2, P2: 1 };
  let boost = false;
  try {
    boost = Date.now() - fs.statSync("/tmp/pw/owner-cookie.txt").mtimeMs < 2 * 3600 * 1000;
  } catch {
    boost = false;
  }
  const weight = (x) => (base[x.priority] || 1) * (boost && OWNER_AREAS.has(x.area) ? 6 : 1);
  const total = rowList.reduce((a, x) => a + weight(x), 0);
  let roll = Math.random() * total;
  let i = 0;
  for (; i < rowList.length - 1 && roll > weight(rowList[i]); i++) roll -= weight(rowList[i]);
  const row = rowList.splice(i, 1)[0];
  seenRows.add(row.workflow_id);
  if (seenRows.size % 10 === 0) fs.writeFileSync(SEEN_FILE, JSON.stringify([...seenRows]));
  return row;
}

async function oneWalk(row, seedOverride) {
  const table = await personas.load();
  const persona = table.get(row.persona) || { id: row.persona, name: row.persona, tags: "", alias: "priya", owner: false };
  const full = (await matrix.personaDetail())[persona.id] || {};
  const prof = profileFor({ ...persona, ...full }, row);
  const ownerArea = OWNER_AREAS.has(row.area);
  const alias = persona.owner || ownerArea ? "owner" : persona.alias;
  const seed = seedOverride || ++counter * 7919 + (Number(row.workflow_id.slice(1)) % 9973);
  const t0 = Date.now();
  let out;
  try {
    out = await walk({ row, alias, persona, prof, seed, area: row.area, filer: alias === "owner" ? null : alias });
  } catch (error) {
    log(`${row.workflow_id} seed ${seed}: the walk broke (${String(error).split("\n")[0].slice(0, 140)})`);
    return { error: true };
  }
  report.simTally(out, row);
  const notes = `SIM seed ${seed} ${row.workflow_id} ${row.area} as ${persona.name} (${prof.speed} typist, ${Math.round(prof.err * 100)}% slips, ${prof.primary}), ${row.state === "normal" ? "" : `state "${row.state}" ${["slow network", "offline"].includes(row.state) ? "" : "not emulated, "}`}${out.steps} steps, ${out.writes} writes held: ${out.found} findings (${out.filed || 0} filed, ${out.counted || 0} counted again, ${out.held || 0} held). Invariants only; the journey's own goal is not asserted.`;
  await matrix.sweep({ persona: persona.id, device: row.device, result: out.found ? "fail" : "pass", bugs: [...new Set(out.bugs)].slice(0, 12).join(","), notes: notes.slice(0, 500) }).catch((e) => log(`Runs row failed: ${e.message}`));
  // a confirmed serious finding on this journey's own area marks the row failed; everything else leaves it for a real journey script
  if (out.rowBugs.length) {
    await matrix
      .result({ workflow: row.workflow_id, result: "fail", persona: persona.id, device: row.device, bugs: [...new Set(out.rowBugs)].join(","), notes: `SIM walk seed ${seed}: ${out.rowBugs.length} serious finding(s) in this area at this size/theme/state` })
      .catch(() => null);
  }
  log(`${row.workflow_id} ${row.area} ${persona.id} ${row.device} ${row.theme} ${row.state} seed ${seed}: ${out.steps} steps, ${out.found} findings (${out.filed || 0} new, ${out.counted || 0} again) in ${Math.round((Date.now() - t0) / 1000)} s`);
  return { out };
}

// ---- the pool: workers rise while the box is healthy, fall when it is not ------------------------------------------
function throttleShare() {
  try {
    const text = fs.readFileSync("/sys/fs/cgroup/ac.slice/ac-strikes.slice/cpu.stat", "utf8");
    const get = (k) => Number((new RegExp(`^${k} (\\d+)`, "m").exec(text) || [0, 0])[1]);
    return { periods: get("nr_periods"), throttled: get("nr_throttled") };
  } catch {
    return { periods: 0, throttled: 0 };
  }
}

async function pool({ max = 4, sizes, minutes = Infinity }) {
  const until = Date.now() + minutes * 60 * 1000;
  let target = Math.min(2, max);
  const running = new Set();
  let last = throttleShare();
  let lastAdjust = Date.now();
  const workerLoop = async (id) => {
    while (Date.now() < until && running.size <= target) {
      if ((await headroom(() => {})) === "stop") return;
      const row = await nextRow(sizes);
      if (!row) {
        await sleep(30000);
        continue;
      }
      await oneWalk(row);
    }
  };
  let ids = 0;
  for (;;) {
    if ((await headroom(log)) === "stop" || Date.now() > until) break;
    const now = Date.now();
    if (now - lastAdjust > 45000) {
      const s = snapshot();
      const t = throttleShare();
      const dP = t.periods - last.periods;
      const share = dP > 0 ? (t.throttled - last.throttled) / dP : 0;
      last = t;
      lastAdjust = now;
      // CPU pressure is mostly other people's work (the robot runs at nice 15 and weight 20, so production and the
      // builders win every contest); what makes the robot back off is a long run queue and memory.
      const stressed = s.memPsi > 8 || s.memAvailableMb < 2000 || s.load1 > 11;
      const healthy = s.memPsi < 4 && s.memAvailableMb > 2600 && s.load1 < 8;
      const before = target;
      if (stressed && target > 1) target--;
      else if (healthy && target < max) target++;
      if (target !== before) log(`workers ${before} -> ${target} (cpu psi ${s.cpuPsi}, mem psi ${s.memPsi}, throttled ${Math.round(share * 100)}%, load ${s.load1}, free ${s.memAvailableMb} MB)`);
    }
    while (running.size < target) {
      const id = ++ids;
      const p = workerLoop(id).catch((e) => log(`worker ${id} stopped: ${String(e).split("\n")[0].slice(0, 120)}`)).finally(() => running.delete(p));
      running.add(p);
    }
    await sleep(3000);
  }
  await Promise.allSettled([...running]);
}

// One walk, for the mixed mode that alternates with the scripted rows at a single worker.
async function runOne(sizes) {
  const row = await nextRow(sizes);
  if (!row) return null;
  return oneWalk(row);
}

module.exports = { pool, oneWalk, runOne, walk, profileFor, START, holdWrites, areaOfRoute };
