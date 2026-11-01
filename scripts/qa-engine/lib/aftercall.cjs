// After-call journeys on the pool of "QA robot" leads (orchestrator's rules, 1 Nov 2026): at most 5 fictional leads in the AC Sales Sandbox (state/qa-pool.json),
// reused by every run, never deleted. These plans are the only ones that write: only as priya, only while the workspace says Sandbox, only on a pool lead,
// only through /v1 (any other write is refused), and tel: is intercepted by a click handler and counted, never followed.
const fs = require("fs");
const path = require("path");
const cfg = require("./config.cjs");
const { go, settle, sleep } = require("./session.cjs");

const POOL_FILE = path.join(cfg.STATE, "qa-pool.json");
const UUID = /[0-9a-f]{8}-[0-9a-f-]{27}/g;
const ROUTE = "/leads?lead=:id";
const TEL_GUARD = `document.addEventListener("click", (e) => { const a = e.target && e.target.closest && e.target.closest('a[href^="tel:"]'); if (a) { e.preventDefault(); e.stopPropagation(); (window.__qaTel = window.__qaTel || []).push(a.getAttribute("href")); } }, true);`;
const pass = (reason, selector = "") => ({ outcome: "pass", reason, route: ROUTE, selector });
const fail = (reason, selector = "", severity = "MAJOR") => ({ outcome: "fail", reason, route: ROUTE, selector, severity });
const blocked = (reason, selector = "") => ({ outcome: "blocked", reason, route: ROUTE, selector });

function pool() {
  try {
    return JSON.parse(fs.readFileSync(POOL_FILE, "utf8"));
  } catch {
    return [];
  }
}
const pickLead = (row) => {
  const list = pool();
  return list.length ? list[Number(String(row.workflow_id).replace(/\D/g, "")) % list.length] : null;
};

// refuse every write that is not a /v1 write, intercept tel:, and note the /v1 writes
async function prepare(tab) {
  if (tab.afterCall) return tab.afterCall;
  const st = { writes: [] };
  await tab.context.addInitScript(TEL_GUARD);
  await tab.context.route("**/*", async (rt) => {
    const req = rt.request();
    if (["GET", "HEAD", "OPTIONS"].includes(req.method())) return rt.fallback();
    const u = new URL(req.url());
    if (u.pathname.startsWith("/v1/") || u.pathname.startsWith("/_next/") || u.pathname.startsWith("/__")) return rt.fallback();
    return rt.abort("blockedbyclient");
  });
  tab.page.on("request", (r) => {
    if (!["GET", "HEAD", "OPTIONS"].includes(r.method()) && r.url().includes("/v1/")) st.writes.push(`${r.method()} ${new URL(r.url()).pathname.replace(UUID, ":id")}`);
  });
  tab.afterCall = st;
  return st;
}

// opens the lead panel; returns an error text, or null when "Log a call" is on screen in a sandbox workspace
async function openLead(tab, lead) {
  const page = tab.page;
  const r = await go(tab, `/leads?lead=${lead.id}`, { wait: 30000 });
  if (!r.ok) return `the page did not open: ${String(r.error).slice(0, 80)}`;
  const btn = page.getByRole("button", { name: /^Log a call/ }).filter({ visible: true });
  for (let t = 0; t < 25 && !(await btn.count()); t++) await sleep(1000);
  const label = await page.evaluate(() => (document.querySelector('[aria-label*="orkspace:"]') || {}).ariaLabel || "");
  if (!/sandbox/i.test(label)) return `NOT A SANDBOX WORKSPACE ("${String(label).slice(0, 50)}"): nothing was written`;
  if (!(await btn.count())) return "the lead panel did not open (no Log a call button)";
  return null;
}

const callsCount = (page) =>
  page.evaluate(() => {
    const t = [...document.querySelectorAll("[role=tab]")].find((e) => /^Calls/i.test((e.textContent || "").trim()));
    const m = t && /(\d+)\s*$/.exec((t.textContent || "").trim());
    return m ? Number(m[1]) : 0;
  });
const statusText = (page) =>
  page.evaluate(() => [...document.querySelectorAll("[role=status],[role=alert]")].filter((e) => e.getBoundingClientRect().width > 0 && !/is your lead now/i.test(e.innerText || "")).map((e) => (e.innerText || "").replace(/\s+/g, " ").trim()).join(" | "));
const press = async (page, name, wait = 1200) => {
  const b = page.getByRole("button", { name }).filter({ visible: true }).first();
  if (!(await b.count())) return false;
  await b.click({ timeout: 8000 }).catch(() => null);
  await sleep(wait);
  return true;
};
const failOpen = (err) => (/NOT A SANDBOX/.test(err) ? blocked(err, "workspace") : fail(err, "lead panel"));

// "Log a call" then "No answer", ready to save
async function toNoAnswer(page) {
  if (!(await press(page, /^Log a call/))) return "no Log a call button";
  if (!(await press(page, "No answer", 1500))) return 'no "No answer" button after Log a call';
  return null;
}

const J212 = {
  as: "priya",
  phoneOnly: true,
  route: "/dashboard",
  async run({ tab, row }) {
    const st = await prepare(tab);
    const lead = pickLead(row);
    if (!lead) return blocked("no QA robot pool lead (state/qa-pool.json)", "pool");
    const err = await openLead(tab, lead);
    if (err) return failOpen(err);
    const page = tab.page;
    const before = await callsCount(page);
    const problem = await toNoAnswer(page);
    if (problem) return fail(problem, "after-call panel");
    const reminder = await page.getByRole("button", { name: /Pick a time/ }).filter({ visible: true }).count();
    st.writes.length = 0;
    if (!(await press(page, /^Save & Close/, 300))) return fail("no Save & Close after No answer", "after-call panel");
    let said = "";
    let undo = 0;
    for (let t = 0; t < 8; t++) {
      said = await statusText(page);
      undo = await page.getByRole("button", { name: /^Undo/ }).filter({ visible: true }).count();
      if (/Moved to|saved/i.test(said) && undo) break;
      await sleep(1000);
    }
    const wrong = [];
    if (!reminder) wrong.push('no "Pick a time instead" (a reminder) after No answer');
    if (!/Moved to|saved/i.test(said)) wrong.push(`no confirmation that the attempt was saved: the screen reads "${said.slice(0, 80) || "nothing"}"`);
    if (!undo) wrong.push("the confirmation offers no Undo");
    const calls = st.writes.filter((w) => /dispose|call|attempt/i.test(w));
    if (calls.length !== 1) wrong.push(`${calls.length} call writes were sent (${st.writes.join(", ").slice(0, 100)}), expected 1`);
    if (undo) await press(page, /^Undo/, 2500);
    const err2 = await openLead(tab, lead);
    if (!err2) {
      const after = await callsCount(page);
      const expected = undo ? before : before + 1;
      if (after !== expected) wrong.push(`the call count went ${before} -> ${after}${undo ? " after Undo" : ""}, expected ${expected}`);
    }
    return wrong.length ? fail(wrong.join("; "), "No answer, Save & Close") : pass(`No answer saves one attempt and says "${said.replace(/\s*\|.*/, "").slice(0, 70)}" with Undo, which took it back` + (/Call attempt saved/i.test(said) ? "" : " (the handoff words it \"Call attempt saved - No Answer\")"), "No answer, Save & Close");
  },
};

const J215 = {
  as: "priya",
  phoneOnly: true,
  route: "/dashboard",
  async run({ tab, row }) {
    const st = await prepare(tab);
    const lead = pickLead(row);
    if (!lead) return blocked("no QA robot pool lead (state/qa-pool.json)", "pool");
    const err = await openLead(tab, lead);
    if (err) return failOpen(err);
    const page = tab.page;
    const before = await callsCount(page);
    const problem = await toNoAnswer(page);
    if (problem) return fail(problem, "after-call panel");
    const save = page.getByRole("button", { name: /^Save & Close/ }).filter({ visible: true }).first();
    const box = await save.boundingBox().catch(() => null);
    if (!box) return fail("no Save & Close after No answer", "after-call panel");
    st.writes.length = 0;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await sleep(120);
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2).catch(() => null);
    await sleep(3500);
    const calls = st.writes.filter((w) => /dispose|call|attempt/i.test(w));
    const wrong = [];
    if (calls.length > 1) wrong.push(`pressing Save twice in 120 ms sent ${calls.length} call writes (${calls.join(", ").slice(0, 120)})`);
    const undo = page.getByRole("button", { name: /^Undo/ }).filter({ visible: true });
    if (await undo.count()) await undo.first().click({ timeout: 5000 }).catch(() => null);
    await sleep(1500);
    const err2 = await openLead(tab, lead);
    if (!err2) {
      const after = await callsCount(page);
      if (after > before + 1) wrong.push(`the call count went ${before} -> ${after}: more than one call record`);
    }
    return wrong.length ? fail(wrong.join("; "), "Save & Close pressed twice") : pass(`a double press makes ${calls.length} call write`, "Save & Close pressed twice");
  },
};

const J219 = {
  as: "priya",
  phoneOnly: true,
  route: "/dashboard",
  async run({ tab, row }) {
    const st = await prepare(tab);
    const lead = pickLead(row);
    if (!lead) return blocked("no QA robot pool lead (state/qa-pool.json)", "pool");
    // arrive from the list so that Back has the list to return to
    await go(tab, "/leads?view=all", { wait: 25000 });
    const err = await openLead(tab, lead);
    if (err) return failOpen(err);
    const page = tab.page;
    const before = await callsCount(page);
    const problem = await toNoAnswer(page);
    if (problem) return fail(problem, "after-call panel");
    st.writes.length = 0;
    await page.goBack({ timeout: 10000 }).catch(() => null);
    await settle(tab, 8000);
    await sleep(1500);
    const wrong = [];
    if (st.writes.length) wrong.push(`leaving with Back sent ${st.writes.length} write(s): ${st.writes.join(", ").slice(0, 100)}`);
    const err2 = await openLead(tab, lead);
    if (!err2) {
      const after = await callsCount(page);
      if (after !== before) wrong.push(`the call count went ${before} -> ${after}: a phantom attempt`);
    }
    return wrong.length ? fail(wrong.join("; "), "Back from the after-call panel") : pass("leaving the after-call panel with Back saves nothing and adds no attempt", "Back from the after-call panel");
  },
};

const J211 = {
  as: "priya",
  phoneOnly: true,
  route: "/dashboard",
  async run({ tab, row }) {
    const st = await prepare(tab);
    const lead = pickLead(row);
    if (!lead) return blocked("no QA robot pool lead (state/qa-pool.json)", "pool");
    const err = await openLead(tab, lead);
    if (err) return failOpen(err);
    const page = tab.page;
    if (!(await press(page, /^Log a call/))) return fail("no Log a call button", "after-call panel");
    if (!(await press(page, "We talked", 1800))) return fail('no "We talked" button after Log a call', "after-call panel");
    const options = await page.getByRole("button", { name: /^(Open Leads|Interested|Meeting Scheduled|Meeting Done|Won|Closed \/ Lost)/ }).filter({ visible: true }).count();
    st.writes.length = 0;
    await press(page, /^Save & Close/, 1800);
    const said = await statusText(page);
    const wrong = [];
    if (!options) wrong.push("We talked offers no outcome to choose (Open Leads, Interested, Meeting Scheduled, Meeting Done, Won, Closed / Lost)");
    if (st.writes.length) wrong.push(`Save & Close with nothing chosen sent ${st.writes.length} write(s): ${st.writes.join(", ").slice(0, 100)}`);
    if (!/pick|choose|select/i.test(said)) wrong.push(`Save & Close with nothing chosen says "${said.slice(0, 70) || "nothing"}" instead of asking what happens next`);
    return wrong.length ? fail(wrong.join("; "), "We talked, Save & Close") : pass("We talked asks what happens next and saves nothing until it is chosen", "We talked, Save & Close");
  },
};

module.exports = { plans: { J211, J212, J215, J219 }, pool, pickLead };
