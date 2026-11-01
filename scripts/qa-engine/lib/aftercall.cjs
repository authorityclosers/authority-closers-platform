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
    if (!/Moved to .+next call/i.test(said)) wrong.push(`the confirmation should say where the lead went and when the next call is ("Moved to <stage> · next call <when>"): the screen reads "${said.slice(0, 80) || "nothing"}"`);
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
    return wrong.length ? fail(wrong.join("; "), "No answer, Save & Close") : pass(`No answer saves one attempt and says "${said.replace(/\s*\|.*/, "").slice(0, 70)}" with Undo, which took it back`, "No answer, Save & Close");
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


// One-off call from the customer: Save & Close returns to the same customer (the panel stays on this lead).
const J213 = {
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
    st.writes.length = 0;
    if (!(await press(page, /^Save & Close/, 300))) return fail("no Save & Close after No answer", "after-call panel");
    let undo = 0;
    for (let t = 0; t < 8 && !undo; t++) {
      undo = await page.getByRole("button", { name: /^Undo/ }).filter({ visible: true }).count();
      if (!undo) await sleep(1000);
    }
    await sleep(800);
    const stillHere = new URL(page.url()).searchParams.get("lead") === lead.id;
    const heading = await page.getByRole("heading", { name: lead.name }).filter({ visible: true }).count();
    const wrong = [];
    if (!stillHere) wrong.push(`Save & Close left the customer: the address is ${new URL(page.url()).pathname + new URL(page.url()).search.slice(0, 40)}`);
    if (!heading) wrong.push(`the customer "${lead.name}" is not on screen after Save & Close`);
    if (undo) await press(page, /^Undo/, 2500);
    return wrong.length ? fail(wrong.join("; "), "Save & Close from a one-off call") : pass("Save & Close returns to the same customer", "Save & Close from a one-off call");
  },
};

// Moving to a stage from the after-call panel asks for what is needed first (a reason to close as lost, a time for a meeting). Nothing is saved.
const J222 = {
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
    const wrong = [];
    const noted = [];
    for (const [stage, wants] of [["Closed / Lost", /reason|why/i], ["Meeting Scheduled", /date|when|time|pick/i]]) {
      const e2 = await openLead(tab, lead);
      if (e2) return failOpen(e2);
      if (!(await press(page, /^Log a call/))) return fail("no Log a call button", "after-call panel");
      if (!(await press(page, "We talked", 1500))) return fail('no "We talked" button', "after-call panel");
      if (!(await press(page, new RegExp("^" + stage.replace(/[/]/g, "\/")), 1800))) {
        noted.push(`no "${stage}" choice`);
        continue;
      }
      st.writes.length = 0;
      await press(page, /^Save & Close/, 1800);
      const said = await statusText(page);
      const extra = await page.evaluate(() => [...document.querySelectorAll("dialog[open] textarea, dialog[open] input, dialog[open] select, [role=dialog] input, [role=dialog] select")].filter((e) => e.getBoundingClientRect().width > 0).map((e) => (e.getAttribute("aria-label") || e.placeholder || e.name || e.type || "").slice(0, 30)));
      const asks = wants.test(said) || extra.some((x) => wants.test(x)) || (await page.getByRole("button", { name: wants }).filter({ visible: true }).count()) > 0;
      if (st.writes.length) wrong.push(`${stage}: Save & Close with nothing more chosen sent ${st.writes.length} write(s)`);
      else if (!asks) wrong.push(`${stage}: it does not ask for what is needed first (screen says "${said.slice(0, 60) || "nothing"}", fields: ${extra.join(", ").slice(0, 60) || "none"})`);
    }
    if (noted.length && !wrong.length) return blocked(noted.join("; "), "stage choices");
    return wrong.length ? fail(wrong.join("; "), "move to stage from the after-call panel") : pass("closing as lost asks for a reason and a meeting asks for a time, before anything is saved", "move to stage from the after-call panel");
  },
};

// J214, the calling round on the pool (competitor teardown 2 behaviour: the start button carries the count, Skip sends a lead to the end of the round, closing the round pauses it,
// Continue or Start from top on the next start, "Round done" at the end). The search "QA robot" scopes the round to the pool; every lead is checked to be a pool lead before anything is written.
// Writes: one No answer save on the first lead, taken back with Undo; the rest of the round is answered with "I didn't call", which writes nothing. The Call link is checked, never pressed
// (pressing it makes the page log a phone call when it comes back, and a logged call cannot be undone).
const ROUND_LIST = "/leads?view=all&q=QA%20robot";
const until = async (fn, ms = 12000) => {
  const t0 = Date.now();
  for (;;) {
    const v = await fn().catch(() => null);
    if (v) return v;
    if (Date.now() - t0 > ms) return null;
    await sleep(500);
  }
};
const dialogHeading = (page) =>
  page.evaluate(() => {
    const h = document.querySelector("dialog[open] h1,dialog[open] h2,dialog[open] h3,[role=dialog] h1,[role=dialog] h2,[role=dialog] h3");
    // the lead panel reads "Lead" until the lead has loaded: not a name yet
    const text = h ? (h.textContent || "").replace(/\s+/g, " ").trim() : "";
    return h && h.getBoundingClientRect().width > 0 && text !== "Lead" ? text : "";
  });

const J214 = {
  as: "priya",
  phoneOnly: true,
  route: "/leads",
  async run({ tab, row }) {
    const st = await prepare(tab);
    const members = pool();
    if (!members.length) return blocked("no QA robot pool lead (state/qa-pool.json)", "pool");
    const names = new Set(members.map((m) => m.name));
    const page = tab.page;
    const here = () => dialogHeading(page);
    const wrong = [];
    const r = await go(tab, ROUND_LIST, { wait: 30000 });
    if (!r.ok) return fail(`the page did not open: ${String(r.error).slice(0, 80)}`, "calling round");
    const start = page.getByRole("button", { name: /^Call Next Lead/ }).filter({ visible: true }).first();
    await until(() => start.count(), 25000);
    const label = await page.evaluate(() => (document.querySelector('[aria-label*="orkspace:"]') || {}).ariaLabel || "");
    if (!/sandbox/i.test(label)) return blocked(`NOT A SANDBOX WORKSPACE ("${String(label).slice(0, 50)}"): nothing was written`, "workspace");
    if (!(await start.count())) return fail("no Call Next Lead button on the Leads list", "Call Next Lead");
    const startText = ((await start.textContent()) || "").replace(/\s+/g, " ").trim();
    const count = Number((/·\s*(\d+)/.exec(startText) || [])[1] || 0);
    if (count !== members.length) wrong.push(`the start button says "${startText}" but the list holds ${members.length} QA robot leads (the search is "QA robot")`);

    // 1. start: the first lead opens with Pause, Call and Skip; the Call link is a tel: link for the number on screen
    await start.click({ timeout: 8000 }).catch(() => null);
    const first = await until(here, 15000);
    if (!first) return fail("Call Next Lead did not open a lead", "Call Next Lead");
    if (!names.has(first)) return blocked(`the round opened "${first.slice(0, 40)}", which is not a QA robot pool lead: nothing was written`, "pool");
    for (const [name, what] of [[/^Pause$/, "Pause"], [/^Skip$/, "Skip"]]) {
      if (!(await page.getByRole("button", { name }).filter({ visible: true }).count())) wrong.push(`the round card has no ${what} button`);
    }
    const callLink = page.getByRole("link", { name: /^Call/ }).filter({ visible: true }).first();
    if (await callLink.count()) {
      const href = (await callLink.getAttribute("href")) || "";
      const shown = ((await callLink.textContent()) || "").replace(/\D/g, "");
      if (!/^tel:\+?\d/.test(href) || href.replace(/\D/g, "") !== shown) wrong.push(`the Call link goes to "${href.slice(0, 30)}" but the screen shows ${shown}`);
    } else wrong.push("the round card has no Call link");

    // 2. Save & Next Lead on the first lead: it opens the next lead, says where the lead went, and Undo takes it back
    const problem = await toNoAnswer(page);
    if (problem) return fail(problem, "after-call panel in a round");
    const saveName = await page.getByRole("button", { name: /^Save/ }).filter({ visible: true }).first().textContent().catch(() => "");
    if (!/^Save & Next Lead/.test((saveName || "").trim())) wrong.push(`in a round the save button should read "Save & Next Lead", it reads "${(saveName || "").trim().slice(0, 30) || "nothing"}"`);
    st.writes.length = 0;
    await press(page, /^Save/, 300);
    const second = await until(async () => {
      const h = await here();
      return h && h !== first ? h : "";
    }, 15000);
    let said = "";
    let undo = 0;
    for (let t = 0; t < 8; t++) {
      said = await statusText(page);
      undo = await page.getByRole("button", { name: /^Undo/ }).filter({ visible: true }).count();
      if (/Moved to/i.test(said) && undo) break;
      await sleep(1000);
    }
    const saves = st.writes.filter((w) => /dispose/i.test(w));
    if (!second) wrong.push("Save & Next Lead did not open the next lead");
    else if (!names.has(second)) wrong.push(`Save & Next Lead opened "${second.slice(0, 40)}", which is not in the round`);
    if (!/Moved to .+next call/i.test(said)) wrong.push(`after Save & Next Lead the screen says "${said.slice(0, 80) || "nothing"}", expected where the lead went and the next call`);
    if (saves.length !== 1) wrong.push(`Save & Next Lead sent ${saves.length} save writes (${st.writes.join(", ").slice(0, 90)}), expected 1`);
    if (undo) {
      await press(page, /^Undo/, 2500);
      const undone = await statusText(page);
      if (!/Undone|back to/i.test(undone)) wrong.push(`Undo in a round says "${undone.slice(0, 60) || "nothing"}"`);
    } else wrong.push("after Save & Next Lead there is no Undo: the pool lead stays moved");

    // 3. Skip sends the lead to the end, Pause leaves the round
    const beforeSkip = await here();
    await press(page, /^Skip$/, 1500);
    const afterSkip = await until(async () => {
      const h = await here();
      return h && h !== beforeSkip ? h : "";
    }, 10000);
    if (!afterSkip) wrong.push("Skip did not move to another lead");
    else if (!names.has(afterSkip)) wrong.push(`Skip opened "${afterSkip.slice(0, 40)}", which is not in the round`);
    await press(page, /^Pause$/, 1500);
    if (!(await until(() => start.count(), 10000))) wrong.push("Pause did not return to the list with the start button");

    // 4. start again: Continue (n of N) and Start from top
    await start.click({ timeout: 8000 }).catch(() => null);
    const cont = page.getByRole("button", { name: /^Continue/ }).filter({ visible: true }).first();
    const top = page.getByRole("button", { name: /^Start from top/ }).filter({ visible: true }).first();
    if (!(await until(() => cont.count(), 8000)) || !(await top.count())) wrong.push("after Pause, starting again does not offer Continue and Start from top");
    else {
      const m = /\((\d+) of (\d+)\)/.exec(((await cont.textContent()) || "").trim());
      if (!m || Number(m[2]) !== members.length) wrong.push(`Continue should say how far the round is ("n of ${members.length}"), it reads "${((await cont.textContent()) || "").trim().slice(0, 30)}"`);
      await cont.click({ timeout: 8000 }).catch(() => null);
      const resumed = await until(here, 10000);
      if (!resumed || !names.has(resumed)) wrong.push(`Continue opened "${(resumed || "nothing").slice(0, 40)}", expected a lead in the round`);
      await press(page, /^Pause$/, 1500);
      await until(() => start.count(), 10000);
      await start.click({ timeout: 8000 }).catch(() => null);
      await until(() => top.count(), 8000);
    }
    let topLead = "";
    if (await top.count()) {
      await top.click({ timeout: 8000 }).catch(() => null);
      topLead = await until(here, 10000);
      if (!topLead || !names.has(topLead)) wrong.push(`Start from top opened "${(topLead || "nothing").slice(0, 40)}", expected a lead in the round`);
    }

    // 5. answer every lead with "I didn't call" (writes nothing): the round must end with "Round done"
    st.writes.length = 0;
    let laps = 0;
    let ended = false;
    for (; laps < members.length + 3; laps++) {
      if ((await dialogHeading(page)) === "Round done") {
        ended = true;
        break;
      }
      if (!(await press(page, /^Log a call/, 1500))) break;
      if (!(await press(page, /^I didn.t call/, 2000))) break;
    }
    if (!ended) ended = (await dialogHeading(page)) === "Round done";
    if (st.writes.length) wrong.push(`answering "I didn't call" sent ${st.writes.length} write(s): ${st.writes.join(", ").slice(0, 100)}`);
    if (!ended) wrong.push(`the round did not end with "Round done" after ${laps} answered leads`);
    else {
      const shown = await page.evaluate(() => [...document.querySelectorAll("dl div")].map((d) => (d.textContent || "").replace(/\s+/g, " ").trim()).join(" | "));
      const leads = Number((/Leads\s*(\d+)/.exec(shown) || [])[1] || 0);
      if (!leads || leads > members.length) wrong.push(`"Round done" says it went through ${leads || "no"} leads (the round has ${members.length}): "${shown.slice(0, 80)}"`);
      for (const [name, what] of [[/Follow-ups due today/, "Follow-ups due today"], [/^Back to the list/, "Back to the list"]]) {
        if (!(await page.getByRole("button", { name }).filter({ visible: true }).count())) wrong.push(`"Round done" has no ${what} button`);
      }
      await press(page, /^Back to the list/, 1500);
      if ((await dialogHeading(page)) === "Round done" || !(await start.count())) wrong.push('"Back to the list" did not return to the list');
    }
    return wrong.length
      ? fail(wrong.join("; "), "calling round")
      : pass(`the round of ${members.length} runs: Save & Next Lead opens the next lead and Undo takes it back, Skip, Pause, Continue and Start from top work, "Round done" ends it${topLead && topLead === first ? " (Start from top opened the first lead again)" : ""}`, "calling round");
  },
};

// A pool lead that a plan left moved (no Undo on screen): back to New Lead by the lead's own Stage control (the sheet's "Move to New Lead" button confirms the choice).
async function putBack(tab, lead) {
  const err = await openLead(tab, lead);
  if (err) return err;
  const page = tab.page;
  const stage = await page.evaluate(() => {
    const b = [...document.querySelectorAll("button")].find((x) => /^Stage:/.test(x.getAttribute("aria-label") || x.textContent || ""));
    return b ? (b.getAttribute("aria-label") || b.textContent || "").trim() : "";
  });
  if (!stage || /^Stage: New Lead[.]/.test(stage)) return null;
  await press(page, /^Stage:/, 1500);
  const pick = page.locator("dialog[open] button, [role=dialog] button").filter({ hasText: /^New Lead\s*Moves at once/ }).filter({ visible: true }).first();
  if (!(await pick.count())) return `no New Lead choice to put ${lead.name} back (it reads "${stage.slice(0, 40)}")`;
  await pick.click({ timeout: 6000 }).catch(() => null);
  await sleep(900);
  await press(page, /^Move to New Lead/, 2500);
  return null;
}

// J221, a save that fails: the dispose request is refused (a dropped connection), then let through for the retry. Expected (as seen working on dev, 1 Nov 2026): the note typed stays in
// its box, the screen says it is not sent yet and offers Send now, nothing says "Moved to" or "saved", and the retry goes out with the SAME command id, so it counts once. The retry is
// a real save on a pool lead (a note is added to it: the one thing Undo keeps); Undo puts the stage back. Offline rows are blocked by design (they need the staging build).
const J221 = {
  as: "priya",
  route: "/dashboard",
  async run({ tab, row }) {
    const st = await prepare(tab);
    const lead = pickLead(row);
    if (!lead) return blocked("no QA robot pool lead (state/qa-pool.json)", "pool");
    const err = await openLead(tab, lead);
    if (err) return failOpen(err);
    const page = tab.page;
    const problem = await toNoAnswer(page);
    if (problem) return fail(problem, "after-call panel");
    const note = page.getByLabel(/Anything to know/).or(page.getByPlaceholder(/Anything to know/)).filter({ visible: true }).first();
    const typed = "QA robot note: kept when a save fails";
    await note.fill(typed).catch(() => null);
    const attempts = [];
    let failing = true;
    const handler = async (rt) => {
      const req = rt.request();
      if (req.method() === "GET" || !/\/dispose$/.test(new URL(req.url()).pathname)) return rt.fallback();
      let command = "";
      try {
        command = JSON.parse(req.postData() || "{}").command_id || "";
      } catch {
        command = "";
      }
      attempts.push({ command, refused: failing });
      if (failing) return rt.abort("internetdisconnected");
      return rt.fallback();
    };
    await tab.context.route("**/v1/lead-desk/leads/*/dispose", handler);
    const wrong = [];
    try {
      st.writes.length = 0;
      await press(page, /^Save & Close/, 300);
      let said = "";
      for (let t = 0; t < 10; t++) {
        said = await statusText(page);
        if (/not sent|couldn.t|try again|kept on this phone|wasn.t saved/i.test(said)) break;
        await sleep(1000);
      }
      const kept = await note.inputValue().catch(() => "");
      const retry = page.getByRole("button", { name: /^(Send now|Try again|Retry)/ }).filter({ visible: true }).first();
      const offers = (await retry.count()) > 0;
      if (/Moved to|All changes saved/i.test(said) && !/not sent/i.test(said)) wrong.push(`the save was refused but the screen says "${said.slice(0, 80)}": a false success`);
      if (!/not sent|couldn.t|try again|kept on this phone|wasn.t saved/i.test(said)) wrong.push(`after a refused save the screen says "${said.slice(0, 80) || "nothing"}", expected that it is not sent yet`);
      if (kept !== typed) wrong.push(`the note typed ("${typed.slice(0, 24)}…") is ${kept ? `now "${kept.slice(0, 30)}"` : "gone"} after the save failed`);
      if (!offers) wrong.push("after a refused save there is no Send now or Try again");
      // the connection is back: the retry
      failing = false;
      const before = attempts.length;
      // normal rows press what the app offers (Send now); the other rows press Save & Close again, whose Undo takes the call back, so the pool does not fill with calls
      const viaSendNow = row.state === "normal" && offers;
      if (viaSendNow) await retry.click({ timeout: 6000 }).catch(() => null);
      else await press(page, /^Save & Close/, 300);
      let after = "";
      let undo = 0;
      for (let t = 0; t < 12; t++) {
        after = await statusText(page);
        undo = await page.getByRole("button", { name: /^Undo/ }).filter({ visible: true }).count();
        if (/Moved to/i.test(after) && undo) break;
        await sleep(1000);
      }
      const through = attempts.filter((a) => !a.refused);
      if (!/Moved to .+next call/i.test(after)) {
        const sheetOpen = (await page.getByRole("button", { name: /^Save & Close/ }).filter({ visible: true }).count()) > 0;
        wrong.push(
          through.length && /not sent/i.test(after)
            ? `after ${viaSendNow ? "Send now" : "the retry"} the save arrived (${through.length} request went through) but the screen still says "${after.slice(0, 60)}"${sheetOpen ? ", the after-call sheet is still open with the note in it" : ""} and shows no "Moved to" or Undo`
            : `after the retry the screen says "${after.slice(0, 80) || "nothing"}", expected where the lead went and the next call`,
        );
      }
      const commands = new Set(attempts.map((a) => a.command));
      if (through.length !== 1) wrong.push(`${through.length} saves went through after the retry (${attempts.length - before} sent since), expected 1`);
      if (commands.size > 1) wrong.push(`the retry used a new command id (${commands.size} different ids over ${attempts.length} attempts), so a save that had arrived would count twice`);
      if (undo) await press(page, /^Undo/, 2500);
      else if (!viaSendNow) wrong.push("after the retry there is no Undo: the pool lead stays moved");
    } finally {
      await tab.context.unroute("**/v1/lead-desk/leads/*/dispose", handler).catch(() => null);
    }
    const left = await putBack(tab, lead);
    if (left) wrong.push(`the pool lead could not be put back: ${left}`);
    return wrong.length ? fail(wrong.join("; "), "save fails, then retry") : pass("a refused save keeps the typed note, says it is not sent yet and offers Send now; the retry goes out once with the same command id and Undo takes it back", "save fails, then retry");
  },
};

module.exports = { plans: { J211, J212, J213, J214, J215, J219, J221, J222 }, pool, pickLead };
