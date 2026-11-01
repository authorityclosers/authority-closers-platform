// Read-and-assert journeys for Home and Settings (orchestrator order, 1 Nov 2026): J175 and J310 (the "no recording" card and the counters), J324 (theme), J323 and J330
// (profile name, notification preferences), then the Home and Leads journeys. All of them refuse every write while they run, except J323 and J330: those two really save one setting as
// priya in the AC Sales Sandbox (orchestrator's yes, 1 Nov 2026), put it back in the same run and read the restore back after a reload.
const fs = require("fs");
const path = require("path");
const cfg = require("./config.cjs");
const { sleep } = require("./session.cjs");

const pass = (reason, route, selector = "") => ({ outcome: "pass", reason, route, selector });
const fail = (reason, route, selector = "", severity = "MAJOR") => ({ outcome: "fail", reason, route, selector, severity });
const blocked = (reason, route, selector = "") => ({ outcome: "blocked", reason, route, selector });

const until = async (fn, ms = 10000) => {
  const t0 = Date.now();
  for (;;) {
    const v = await fn().catch(() => null);
    if (v) return v;
    if (Date.now() - t0 > ms) return null;
    await sleep(400);
  }
};

// ---- Home: the counters and the "no recording" card ------------------------------------------------------------------------
const TODAY_LABELS = ["Called today", "Talk time", "Connection rate", "Follow-ups done"];
const CARD = /no recording|without (a )?recording|recording (is |was )?missing|have no recording/i;

function readHome({ labels, cardSource }) {
  const card = new RegExp(cardSource, "i");
  const main = document.querySelector("main") || document.body;
  const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
  const leaves = [...main.querySelectorAll("*")].filter((e) => e.children.length === 0 && visible(e));
  const cards = [...main.querySelectorAll("section,article,aside,a,button,div,li,p")]
    .filter((e) => visible(e) && card.test(e.innerText || "") && (e.innerText || "").length < 300 && ![...e.children].some((c) => card.test(c.innerText || "") && (c.innerText || "").length < 300))
    .map((e) => ({ text: (e.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160), el: e }));
  const found = [];
  const covered = [];
  const underCard = [];
  for (const label of labels) {
    for (const el of leaves.filter((e) => (e.textContent || "").replace(/\s+/g, " ").trim().toLowerCase() === label.toLowerCase())) {
      found.push(label);
      // the counters sit in a horizontal pager on a phone: bring each one to the middle, both ways
      el.scrollIntoView({ block: "center", inline: "center" });
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      if (!hit || !(hit === el || el.contains(hit) || hit.contains(el))) covered.push(label);
      for (const c of cards) {
        const cr = c.el.getBoundingClientRect();
        if (!c.el.contains(el) && r.left < cr.right && r.right > cr.left && r.top < cr.bottom && r.bottom > cr.top) underCard.push(label);
      }
    }
  }
  const numberAfter = (label) => {
    const text = (main.innerText || "").replace(/\s+/g, " ");
    const m = new RegExp("(\\d+)\\s+" + label, "i").exec(text);
    return m ? Number(m[1]) : null;
  };
  return { found, covered, underCard, cards: cards.map((c) => c.text), tried: numberAfter("Tried"), connected: numberAfter("Connected") };
}

const J175 = {
  route: "/dashboard",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByText("Today's performance").first().count(), 15000);
    // the counters can still be coming in when the page first answers (a dark row once read one of four): wait for them before judging
    let home = await page.evaluate(readHome, { labels: TODAY_LABELS, cardSource: CARD.source });
    for (let t = 0; t < 20 && new Set(home.found).size < 3; t++) {
      await sleep(1000);
      home = await page.evaluate(readHome, { labels: TODAY_LABELS, cardSource: CARD.source });
    }
    const labels = [...new Set(home.found)];
    if (labels.length < 3) return fail(`Home shows only ${labels.length} of the four counters (${labels.join(", ") || "none"}): ${TODAY_LABELS.join(", ")}`, "/dashboard", "Home counters");
    if (home.covered.length) return fail(`the counter${home.covered.length > 1 ? "s" : ""} ${[...new Set(home.covered)].join(", ")} sit${home.covered.length > 1 ? "" : "s"} under something else on Home`, "/dashboard", "Home counters");
    if (home.cards.length && home.underCard.length) return fail(`the "no recording" card ("${home.cards[0].slice(0, 70)}") sits over the counters ${[...new Set(home.underCard)].join(", ")}`, "/dashboard", "no recording card");
    return pass(`Home shows ${labels.join(", ")} uncovered${home.cards.length ? `, with the "no recording" card beside them` : " (no 'no recording' card today)"}`, "/dashboard", "Home counters");
  },
};

const J310 = {
  route: "/dashboard",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByText("Today's performance").first().count(), 15000);
    const home = await page.evaluate(readHome, { labels: TODAY_LABELS, cardSource: CARD.source });
    if (!home.cards.length) return blocked("the card does not show: this seller has no call today without a recording (the sandbox sellers have no calls today), so there is nothing to compare; needs a seller with such a call", "/dashboard", "no recording card");
    const said = Number((/(\d+)/.exec(home.cards[0]) || [])[1] || 0);
    if (home.tried != null && said > home.tried) return fail(`the card says ${said} call${said === 1 ? "" : "s"} have no recording but Tried today is ${home.tried}`, "/dashboard", "no recording card");
    return pass(`the card ("${home.cards[0].slice(0, 60)}") agrees with Tried ${home.tried ?? "?"}`, "/dashboard", "no recording card");
  },
};

// ---- Settings ----------------------------------------------------------------------------------------------------------------
// what the eye would see change: background of the page, the main area and the text colour
const bodyColour = (page) =>
  page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    return [getComputedStyle(document.documentElement).backgroundColor, getComputedStyle(document.body).backgroundColor, getComputedStyle(main).backgroundColor, getComputedStyle(document.body).color].join(" | ");
  });
const themeNow = (page) => page.evaluate(() => ({ data: document.documentElement.dataset.theme || "", stored: (() => { try { return localStorage.getItem("sales-xray:theme"); } catch { return "?"; } })() }));

const J324 = {
  route: "/settings/notifications",
  async run({ tab }) {
    const page = tab.page;
    const radios = page.getByRole("radio", { name: /^(light|dark|system)$/i });
    await until(() => radios.count(), 15000);
    const names = (await radios.evaluateAll((els) => els.map((e) => (e.getAttribute("aria-label") || (e.labels && e.labels[0] && e.labels[0].textContent) || e.value || "").trim().toLowerCase()))).filter(Boolean);
    if (!names.includes("light") || !names.includes("dark")) return fail(`Appearance offers ${names.join(", ") || "nothing"}, expected Light and Dark`, "/settings/notifications", "Appearance");
    const start = (await themeNow(page)).data === "dark" ? "dark" : "light";
    const other = start === "dark" ? "light" : "dark";
    const colourStart = await bodyColour(page);
    const wrong = [];
    const choose = async (name) => {
      const radio = radios.nth(names.indexOf(name));
      await radio.check({ timeout: 6000, force: true }).catch(() => radio.click({ force: true, timeout: 6000 }).catch(() => null));
      await sleep(900);
    };
    await choose(other);
    let now = await themeNow(page);
    if (now.data !== other) wrong.push(`choosing ${other} leaves the page on "${now.data}"`);
    // Light is the default: the app may store it as "light" or take the key away
    if (!(other === "dark" ? now.stored === "dark" : now.stored === "light" || now.stored === null)) wrong.push(`choosing ${other} is not kept on this device (stored "${now.stored}")`);
    const colourOther = await bodyColour(page);
    if (colourOther === colourStart) wrong.push(`nothing on the page changes colour when ${other} is chosen (${colourStart})`);
    // a dark row's browser sets the dark key before every page load (the robot's own init script), so a reload says nothing there: it is checked on light rows
    if (start === "light") {
      await page.reload({ waitUntil: "load" }).catch(() => null);
      await until(() => radios.count(), 15000);
      now = await themeNow(page);
      if (now.data !== other) wrong.push(`after a reload the page is "${now.data}" again instead of ${other}`);
    }
    await choose(start);
    now = await themeNow(page);
    if (now.data !== start) wrong.push(`choosing ${start} again leaves the page on "${now.data}"`);
    const note = names.includes("system") ? "" : " (the app offers Light and Dark only, no System choice)";
    return wrong.length ? fail(wrong.join("; "), "/settings/notifications", "Appearance") : pass(`${start} to ${other} and back: the page changes, the choice is kept on this device${start === "light" ? " and survives a reload" : ""}${note}`, "/settings/notifications", "Appearance");
  },
};

// J330 and J323 really save, as priya in the AC Sales Sandbox (orchestrator, 1 Nov 2026: "let the row change one setting and put it back in the same run, then assert the restore before the
// row passes; if the restore fails, stop the row and tell me"). One setting each: the Quiet outside working hours switch, and the Full name. The restore is read back after a reload; when it
// does not hold, the row fails with "RESTORE FAILED", state/restore-failed.txt is written and every later row of these two journeys is held until someone clears that file.
const RESTORE_FLAG = path.join(cfg.STATE, "restore-failed.txt");
const UUID = /[0-9a-f]{8}-[0-9a-f-]{27}/g;

const writeGuarded = (plan) => ({
  ...plan,
  as: "priya",
  async run(ctx) {
    if (fs.existsSync(RESTORE_FLAG)) return blocked(`held: an earlier row could not put its change back (state/restore-failed.txt); nothing is changed until that file is cleared`, plan.route, "restore");
    const st = { writes: [] };
    const handler = async (route) => {
      const req = route.request();
      if (["GET", "HEAD", "OPTIONS"].includes(req.method())) return route.fallback();
      const u = new URL(req.url());
      if (u.pathname.startsWith("/v1/")) {
        st.writes.push(`${req.method()} ${u.pathname.replace(UUID, ":id")}`);
        return route.fallback();
      }
      if (u.pathname.startsWith("/_next/") || u.pathname.startsWith("/__")) return route.fallback();
      return route.abort("blockedbyclient");
    };
    await ctx.tab.context.route("**/*", handler);
    try {
      return await plan.run({ ...ctx, st });
    } finally {
      await ctx.tab.context.unroute("**/*", handler).catch(() => null);
    }
  },
});

const sandboxLabel = (page) => page.evaluate(() => (document.querySelector('[aria-label*="orkspace:"]') || {}).ariaLabel || "");
const restoreFailed = (what, route, selector) => {
  try {
    fs.appendFileSync(RESTORE_FLAG, `${new Date().toISOString()} ${what}\n`);
  } catch {
    // the failure is still reported by the row
  }
  return fail(`RESTORE FAILED: ${what}. Every later J323 and J330 row is held until state/restore-failed.txt is cleared; tell the orchestrator`, route, selector, "MAJOR");
};

const J330 = {
  route: "/settings/notifications",
  async run({ tab, st }) {
    const page = tab.page;
    await until(() => page.getByRole("switch").first().count(), 15000);
    if (!/sandbox/i.test(await sandboxLabel(page))) return blocked("NOT A SANDBOX WORKSPACE: nothing was changed", "/settings/notifications", "workspace");
    // Vibration is a phone setting: a computer does not show it
    const want = [["New enquiry", /^New enquiry/i], ["Follow-up due", /^Follow-up due/i], ["Missed follow-up", /^Missed follow-up/i], ["Quiet outside working hours", /^Quiet outside working hours/i]];
    if (tab.dev.phone) want.push(["Vibration", /^Vibration/i]);
    const missing = [];
    for (const [label, name] of want) if (!(await page.getByRole("switch", { name }).filter({ visible: true }).count())) missing.push(label);
    if (!(await page.getByRole("button", { name: /^Send me a test notification/ }).filter({ visible: true }).count())) missing.push("Send me a test notification");
    if (missing.length) return fail(`the notification settings are missing: ${missing.join(", ")}`, "/settings/notifications", "notification switches");
    const sw = () => page.getByRole("switch", { name: /^Quiet outside working hours/i }).filter({ visible: true }).first();
    const state = async () => (await sw().getAttribute("aria-checked").catch(() => null)) || (await sw().evaluate((e) => String(e.checked)).catch(() => null));
    const reload = async () => {
      await page.reload({ waitUntil: "load" }).catch(() => null);
      await until(() => sw().count(), 15000);
      await sleep(1500);
    };
    const before = await state();
    if (before !== "true" && before !== "false") return fail("the Quiet outside working hours switch does not say whether it is on", "/settings/notifications", "Quiet outside working hours");
    const changed = before === "true" ? "false" : "true";
    const wrong = [];
    st.writes.length = 0;
    await sw().click({ timeout: 6000 }).catch(() => null);
    await sleep(2500);
    if ((await state()) !== changed) wrong.push("the switch does not change when it is pressed");
    if (!st.writes.some((w) => /^(PUT|POST|PATCH)/.test(w))) wrong.push("pressing the switch sent no save");
    await reload();
    const kept = await state();
    if (kept !== changed) wrong.push(`after a reload the switch is "${kept}" again: the change was not saved`);
    // put it back, and read it back after a reload
    if (kept !== before) {
      await sw().click({ timeout: 6000 }).catch(() => null);
      await sleep(2500);
      await reload();
    }
    const final = await state();
    if (final !== before) return restoreFailed(`Quiet outside working hours was ${before}, changed to ${changed}, and reads ${final} after the put-back and a reload`, "/settings/notifications", "Quiet outside working hours");
    return wrong.length ? fail(wrong.join("; "), "/settings/notifications", "Quiet outside working hours") : pass(`Quiet outside working hours changed from ${before} to ${changed}, was saved (survived a reload) and was put back (reads ${before} after a reload)`, "/settings/notifications", "Quiet outside working hours");
  },
};

const J323 = {
  route: "/settings/profile",
  async run({ tab, st }) {
    const page = tab.page;
    const edit = page.getByRole("button", { name: /^Edit details/ }).filter({ visible: true }).first();
    await until(() => edit.count(), 15000);
    if (!/sandbox/i.test(await sandboxLabel(page))) return blocked("NOT A SANDBOX WORKSPACE: nothing was changed", "/settings/profile", "workspace");
    const field = () => page.getByLabel(/^Full name/).filter({ visible: true }).first();
    const open = async () => {
      if (!(await field().count())) {
        await edit.click({ timeout: 6000 }).catch(() => null);
        await until(() => field().count(), 8000);
      }
      return (await field().count()) > 0;
    };
    const reload = async () => {
      await page.reload({ waitUntil: "load" }).catch(() => null);
      await until(() => edit.count(), 15000);
      await sleep(1200);
    };
    const save = async (name) => {
      if (!(await open())) return false;
      await field().fill(name).catch(() => null);
      await sleep(400);
      await page.getByRole("button", { name: /^Save details/ }).filter({ visible: true }).first().click({ timeout: 6000 }).catch(() => null);
      await sleep(3000);
      return true;
    };
    if (!(await open())) return fail('"Edit details" shows no Full name field', "/settings/profile", "Full name");
    const before = await field().inputValue();
    const next = before.endsWith(" QA") ? before.slice(0, -3) : `${before} QA`;
    const wrong = [];
    st.writes.length = 0;
    await save(next);
    if (!st.writes.some((w) => /^(PUT|POST|PATCH)/.test(w))) wrong.push("Save details sent no save");
    const shownAfter = await page.evaluate(() => (document.querySelector("main") || document.body).innerText.replace(/\s+/g, " "));
    if (!shownAfter.includes(next)) wrong.push(`after Save details the Profile page does not show the new name "${next}"`);
    await reload();
    await open();
    const kept = await field().inputValue().catch(() => "");
    if (kept !== next) wrong.push(`after a reload the name reads "${kept}", not the saved "${next}"`);
    // everywhere: the account menu on a computer names the person
    if (!tab.dev.phone) {
      const label = await page.getByRole("button", { name: /^Open .* menu$/ }).filter({ visible: true }).first().getAttribute("aria-label").catch(() => "");
      if (label && !label.includes(next)) wrong.push(`the account menu still reads "${label}" after the name changed to "${next}"`);
    }
    // put it back, and read it back after a reload
    if (kept !== before) {
      await save(before);
      await reload();
      await open();
    }
    const final = await field().inputValue().catch(() => "");
    if (final !== before) return restoreFailed(`the Full name was "${before}", changed to "${next}", and reads "${final}" after the put-back and a reload`, "/settings/profile", "Full name");
    return wrong.length ? fail(wrong.join("; "), "/settings/profile", "Full name") : pass(`the Full name changed from "${before}" to "${next}", showed on the Profile page and after a reload, and was put back (reads "${before}" after a reload)`, "/settings/profile", "Full name");
  },
};

// ---- Home: counters in the first screen, how many rows the sections show, the next lead ------------------------------------
const J158 = {
  route: "/dashboard",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByText("Today's performance").first().count(), 15000);
    await page.evaluate(() => window.scrollTo(0, 0));
    await sleep(400);
    const read = await page.evaluate(() => {
      const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
      const leaves = [...document.querySelectorAll("*")].filter((e) => e.children.length === 0 && visible(e));
      const want = [["New", /^new( leads?)?$/i], ["Open", /^(in discussion|open( leads?)?)$/i], ["Follow-ups", /^follow-ups?( today)?$/i], ["Tasks", /^tasks?( today)?$/i]];
      return want.map(([name, rx]) => {
        const el = leaves.find((e) => rx.test((e.textContent || "").replace(/\s+/g, " ").trim()));
        if (!el) return { name, found: false };
        const r = el.getBoundingClientRect();
        return { name, found: true, inFirstScreen: r.top >= 0 && r.bottom <= innerHeight, bottom: Math.round(r.bottom), vh: innerHeight };
      });
    });
    const missing = read.filter((c) => !c.found).map((c) => c.name);
    if (missing.length) return fail(`Home does not show the ${missing.join(", ")} counter${missing.length > 1 ? "s" : ""}`, "/dashboard", "Home counters");
    const below = read.filter((c) => !c.inFirstScreen);
    if (below.length) return fail(`the ${below.map((c) => c.name).join(", ")} counter${below.length > 1 ? "s" : ""} need${below.length > 1 ? "" : "s"} scrolling (the lowest ends at ${Math.max(...below.map((c) => c.bottom))}px of a ${below[0].vh}px screen)`, "/dashboard", "Home counters");
    return pass(`the four counters (${read.map((c) => c.name).join(", ")}) are all in the first screen, the lowest ending at ${Math.max(...read.map((c) => c.bottom))}px of ${read[0].vh}px`, "/dashboard", "Home counters");
  },
};

// A section's rows: the links and buttons under its heading, in the heading's own column (a computer shows two columns), down to the next heading in that column. A row
// can hold a name link and a phone button, so rows are counted by what they open: one per lead or task link, one per other control; "See all", "+ Add", the empty-state
// nudge and the phone buttons are not rows.
const SECTION_ROWS = ({ from }) => {
  const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
  const nameOf = (e) => (e.getAttribute("aria-label") || e.textContent || "").replace(/\s+/g, " ").trim();
  const heads = [...document.querySelectorAll("h1,h2,h3")].filter(visible);
  const a = heads.find((e) => (e.textContent || "").trim() === from);
  if (!a) return { found: false };
  const ha = a.getBoundingClientRect();
  const mid = ha.top + ha.height / 2;
  // this section's See all link: on the heading's own line, to the right of the heading
  const seeLinks = [...document.querySelectorAll("a[href]")]
    .filter((e) => {
      const r = e.getBoundingClientRect();
      // on the heading's line, or just under it when a narrow screen wraps "+ Add" and "See all" onto a second line (360 px)
      const centre = r.top + r.height / 2;
      return visible(e) && /^see (all|details)/i.test(nameOf(e)) && centre >= ha.top - 20 && centre <= ha.bottom + 50 && r.left >= ha.left;
    })
    .sort((x, y) => x.getBoundingClientRect().left - y.getBoundingClientRect().left);
  const seeAll = seeLinks.filter((e) => /^see all/i.test(nameOf(e))).map((e) => e.getAttribute("href"));
  const colLeft = ha.left;
  const colRight = seeLinks.length ? seeLinks[0].getBoundingClientRect().right : a.parentElement.getBoundingClientRect().right;
  const inColumn = (r) => r.left + r.width / 2 >= colLeft - 4 && r.left + r.width / 2 <= colRight + 4;
  const top = ha.bottom + scrollY;
  const next = heads
    .filter((h) => h !== a && h.getBoundingClientRect().bottom + scrollY > top + 4 && inColumn(h.getBoundingClientRect()))
    .sort((x, y) => x.getBoundingClientRect().top - y.getBoundingClientRect().top)[0];
  const end = next ? next.getBoundingClientRect().top + scrollY - 14 : Infinity;
  const keys = new Set();
  for (const e of document.querySelectorAll("a[href],button")) {
    if (!visible(e) || e.closest("[role=status],[role=alert]")) continue;
    const r = e.getBoundingClientRect();
    if (!inColumn(r) || r.top + scrollY < top - 2 || r.top + scrollY >= end) continue;
    const name = nameOf(e);
    if (!name || /^(see all|see details|\+ ?add|add( |$)|call your next lead|call |open lead|dismiss)/i.test(name)) continue;
    keys.add(e.tagName === "A" && /(lead|task)=/.test(e.getAttribute("href") || "") ? e.getAttribute("href") : `${e.tagName}:${name}`);
  }
  return { found: true, rows: keys.size, seeAll, sample: [...keys].slice(0, 4).map((k) => k.slice(0, 40)) };
};

const J162 = {
  route: "/dashboard",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByText("Today's performance").first().count(), 15000);
    const tasks = await page.evaluate(SECTION_ROWS, { from: "Today's tasks", to: "Upcoming follow-ups" });
    const follow = await page.evaluate(SECTION_ROWS, { from: "Upcoming follow-ups", to: "Today's performance" });
    if (!tasks.found || !follow.found) return fail(`Home has no ${!tasks.found ? "Today's tasks" : "Upcoming follow-ups"} section`, "/dashboard", "Home sections");
    const wrong = [];
    if (tasks.rows > 3) wrong.push(`Home shows ${tasks.rows} tasks, at most three (${(tasks.sample || []).join(" | ")})`);
    if (follow.rows > 2) wrong.push(`Home shows ${follow.rows} upcoming follow-ups, at most two (${(follow.sample || []).join(" | ")})`);
    if (!tasks.seeAll.length) wrong.push("Today's tasks has no See all link");
    if (!follow.seeAll.length) wrong.push("Upcoming follow-ups has no See all link");
    else if (!/view=follow_ups/.test(follow.seeAll[0]) || !/when=upcoming/.test(follow.seeAll[0])) wrong.push(`the follow-ups See all goes to "${follow.seeAll[0]}", expected Follow-ups, Upcoming`);
    return wrong.length ? fail(wrong.join("; "), "/dashboard", "Home sections") : pass(`Home shows ${tasks.rows} task${tasks.rows === 1 ? "" : "s"} and ${follow.rows} upcoming follow-up${follow.rows === 1 ? "" : "s"}, each section with a See all link`, "/dashboard", "Home sections");
  },
};

const J141 = {
  route: "/dashboard",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByText("Today's performance").first().count(), 15000);
    const card = await page.evaluate(() => {
      const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
      const head = [...document.querySelectorAll("*")].find((e) => e.children.length === 0 && /^next (inbound|cold) call$/i.test((e.textContent || "").trim()) && visible(e));
      if (!head) return null;
      let root = head;
      for (let i = 0; i < 6 && root.parentElement; i++) {
        root = root.parentElement;
        if (root.querySelector("a[href*='lead=']") && root.querySelectorAll("a[href]").length >= 2) break;
      }
      const links = [...root.querySelectorAll("a[href]")].filter(visible).map((e) => ({ text: (e.getAttribute("aria-label") || e.textContent || "").replace(/\s+/g, " ").trim(), href: e.getAttribute("href") || "" }));
      return { links };
    });
    if (!card) return blocked("Home shows no next-to-call card for this seller (nothing to call)", "/dashboard", "Next to Call");
    const nameLink = card.links.find((l) => /lead=/.test(l.href));
    const callLink = card.links.find((l) => l !== nameLink && /^call\b|^start/i.test(l.text));
    if (!nameLink || !callLink) return fail(`the next-to-call card has ${nameLink ? "no Call link" : "no link to the lead"} (${card.links.map((l) => l.text).join(" / ").slice(0, 80)})`, "/dashboard", "Next to Call");
    const leadId = (/lead=([0-9a-f-]+)/.exec(nameLink.href) || [])[1];
    const callA = page.getByRole("link", { name: callLink.text }).filter({ visible: true }).first();
    await callA.click({ timeout: 8000 }).catch(() => null);
    const opened = await until(async () => (new URL(page.url()).searchParams.get("lead") || "") && (await page.getByRole("heading", { name: nameLink.text, exact: true }).filter({ visible: true }).count()), 30000);
    const gotId = new URL(page.url()).searchParams.get("lead") || "";
    if (!opened || gotId !== leadId) return fail(`"${callLink.text}" on Home was meant to open ${nameLink.text}, but ${gotId ? "another lead opened" : "no lead opened"} (${page.url().replace(/lead=[0-9a-f-]+/, "lead=<id>").replace(/^https?:\/\/[^/]+/, "")})`, "/dashboard", "Next to Call");
    const tel = await page.evaluate(() => [...document.querySelectorAll("a[href^='tel:']")].filter((e) => e.getBoundingClientRect().width > 0).map((e) => ({ href: e.getAttribute("href"), text: (e.textContent || "").replace(/\D/g, "") })));
    if (!tel.length) return fail(`${nameLink.text} opened but there is no number to call (no tel: link on the lead)`, "/dashboard", "Next to Call");
    const bad = tel.filter((t) => t.text && t.href.replace(/\D/g, "") !== t.text.slice(-t.href.replace(/\D/g, "").length));
    if (bad.length) return fail(`the call link goes to ${bad[0].href} but the screen shows ${bad[0].text}`, "/dashboard", "Next to Call");
    return pass(`"${callLink.text}" opens ${nameLink.text}, the lead named on the card, with a call link to the number shown`, "/dashboard", "Next to Call");
  },
};

// ---- Leads: quick views, search and filters (nothing is saved) ---------------------------------------------------------------
const leadsSnap = (page) =>
  page.evaluate(() => {
    const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
    const stage = [...document.querySelectorAll("button")].find((b) => /^pipeline stage/i.test(b.getAttribute("aria-label") || b.textContent || ""));
    const search = document.querySelector('input[placeholder*="earch leads"],input[aria-label*="earch leads"]');
    return {
      search: location.search,
      box: search ? search.value : null,
      stage: stage ? (stage.getAttribute("aria-label") || stage.textContent || "").replace(/\s+/g, " ").trim() : "",
      tabs: [...document.querySelectorAll("[role=tab]")].filter(visible).map((t) => ({ name: (t.textContent || "").replace(/\s+/g, " ").trim(), on: t.getAttribute("aria-selected") === "true" })),
      rows: [...document.querySelectorAll("button")].filter((b) => visible(b) && /^Open (?!lead$)(?!.* menu$)/.test(b.getAttribute("aria-label") || b.textContent || "")).map((b) => (b.getAttribute("aria-label") || b.textContent || "").replace(/^Open /, "").trim()),
      empty: ((document.querySelector("main") || document.body).innerText || "").match(/no leads|nothing here|no results|no matching|all clear/i),
    };
  });
const tabCount = (snap, rx) => {
  const t = snap.tabs.find((x) => rx.test(x.name));
  return t ? Number((/(\d+)\s*$/.exec(t.name) || [])[1] || 0) : null;
};
const J142 = {
  route: "/leads",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("tab", { name: /^To Call/ }).first().count(), 25000);
    const start = await leadsSnap(page);
    if (start.tabs.length < 3) return fail(`Leads shows ${start.tabs.length} quick views (${start.tabs.map((t) => t.name).join(" / ")}), expected To Call, Follow-ups, All Leads`, "/leads", "quick views");
    const wrong = [];
    const seen = [];
    for (const [rx, label] of [[/^Follow-ups/, "Follow-ups"], [/^All Leads/, "All Leads"], [/^To Call/, "To Call"]]) {
      await page.getByRole("tab", { name: rx }).filter({ visible: true }).first().click({ timeout: 6000 }).catch(() => null);
      await sleep(1500);
      const now = await leadsSnap(page);
      seen.push(`${label}: ${now.search || "/leads"}`);
      if (now.stage !== start.stage) wrong.push(`opening ${label} changed the stage control from "${start.stage}" to "${now.stage}": a quick view is a filter, not a stage`);
      const on = now.tabs.find((t) => t.on);
      if (!on || !rx.test(on.name)) wrong.push(`${label} was pressed but ${on ? `"${on.name}"` : "no view"} is selected`);
    }
    const all = tabCount(start, /^All Leads/);
    const toCall = tabCount(start, /^To Call/);
    const fup = tabCount(start, /^Follow-ups/);
    if (all != null && toCall != null && toCall > all) wrong.push(`To Call counts ${toCall} leads but All Leads only ${all}`);
    if (all != null && fup != null && fup > all) wrong.push(`Follow-ups counts ${fup} leads but All Leads only ${all}`);
    return wrong.length ? fail(wrong.join("; "), "/leads", "quick views") : pass(`To Call, Follow-ups and All Leads switch without touching the stage control ("${start.stage}"); counts ${toCall ?? "?"} / ${fup ?? "?"} / ${all ?? "?"}`, "/leads", "quick views");
  },
};

const J177 = {
  route: "/leads",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("tab", { name: /^To Call/ }).first().count(), 25000);
    const box = page.getByPlaceholder(/earch leads/).or(page.getByLabel(/earch leads/)).filter({ visible: true }).first();
    if (!(await box.count())) return fail("Leads has no Search leads box", "/leads", "search");
    await box.fill("a").catch(() => null);
    await sleep(2000);
    const typed = await leadsSnap(page);
    if (!/q=a\b/.test(typed.search)) return fail(`typing in the search box does not reach the address (${typed.search || "no query"}): a shared or reloaded link loses it`, "/leads", "search");
    const wrong = [];
    for (const [rx, label] of [[/^Follow-ups/, "Follow-ups"], [/^All Leads/, "All Leads"], [/^To Call/, "To Call"]]) {
      await page.getByRole("tab", { name: rx }).filter({ visible: true }).first().click({ timeout: 6000 }).catch(() => null);
      await sleep(1500);
      const now = await leadsSnap(page);
      if (now.box !== "a") wrong.push(`the search box reads "${now.box ?? "nothing"}" after opening ${label}, it was "a"`);
      if (!/q=a\b/.test(now.search)) wrong.push(`${label} dropped the search from the address (${now.search || "none"})`);
    }
    await page.getByRole("button", { name: /^Clear search/ }).filter({ visible: true }).first().click({ timeout: 4000 }).catch(() => null);
    await sleep(1200);
    return wrong.length ? fail([...new Set(wrong)].join("; "), "/leads", "search across quick views") : pass("the search stays in the box and in the address across To Call, Follow-ups and All Leads", "/leads", "search across quick views");
  },
};

const J181 = {
  route: "/leads",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("tab", { name: /^To Call/ }).first().count(), 25000);
    const before = await leadsSnap(page);
    const filter = page.getByRole("button", { name: /^Filter leads/ }).filter({ visible: true }).first();
    const sheet = () => page.getByRole("dialog").filter({ visible: true }).count();
    // each filter is a picker inside the sheet: open it, then choose the row (the sheet slides up first: a tap during that slide misses)
    const sheetField = async (field) => ((await page.getByRole("dialog").getByRole("button", { name: new RegExp(`^${field}`) }).first().textContent().catch(() => "")) || "").replace(/\s+/g, " ").trim();
    const pick = async (field, option) => {
      const opener = page.getByRole("dialog").getByRole("button", { name: new RegExp(`^${field}`) }).first();
      if (!(await opener.count())) return `the filter sheet has no ${field} choice`;
      for (let attempt = 0; attempt < 2; attempt++) {
        await opener.click({ timeout: 5000 }).catch(() => null);
        await sleep(500);
        const row = page.getByRole("option", { name: option, exact: true }).filter({ visible: true }).first();
        if (!(await row.count())) return `${field} has no "${option}" choice`;
        await row.click({ timeout: 5000 }).catch(() => null);
        await sleep(500);
        if ((await sheetField(field)).includes(option)) return "";
      }
      return `choosing "${option}" in ${field} does not take (it reads "${(await sheetField(field)).slice(0, 40)}")`;
    };
    await filter.click({ timeout: 6000 }).catch(() => null);
    if (!(await until(sheet, 8000))) return fail("Filter leads does not open the filter sheet", "/leads", "Filter leads");
    await sleep(1300);
    for (const [field, option] of [["Lead source", "Added by hand"], ["Date", "Came in this month"], ["Follow-up", "Upcoming"]]) {
      const problem = await pick(field, option);
      if (problem) return fail(problem, "/leads", "Filter leads");
    }
    const chosen = [await sheetField("Lead source"), await sheetField("Date"), await sheetField("Follow-up")];
    await page.getByRole("button", { name: /^Show Results/ }).filter({ visible: true }).first().click({ timeout: 5000 }).catch(() => null);
    await sleep(2200);
    const wrong = [];
    if (!/Added by hand/.test(chosen[0]) || !/this month/.test(chosen[1]) || !/Upcoming/.test(chosen[2])) wrong.push(`the sheet shows "${chosen.join(" / ").slice(0, 80)}" after the three choices`);
    if (await sheet()) wrong.push("Show Results leaves the filter sheet open");
    const applied = await leadsSnap(page);
    const appliedCount = tabCount(applied, /^To Call/);
    const beforeCount = tabCount(before, /^To Call/);
    const emptyText = await page.evaluate(() => ((document.querySelector("main") || document.body).innerText || "").replace(/\s+/g, " "));
    if (!applied.rows.length && !applied.empty) wrong.push("the filters match no lead and the list says nothing about it");
    if (applied.rows.length === 0 && /whose leads/i.test(emptyText)) wrong.push('the empty list says "Nobody here for whose leads you picked.": a garbled sentence, and the filters chosen here are source, date and follow-up, not whose leads');
    if (appliedCount != null && appliedCount !== applied.rows.length) wrong.push(`the To Call tab and the Call Next Lead button count ${appliedCount} lead${appliedCount === 1 ? "" : "s"} but the list under the filters shows ${applied.rows.length}`);
    if (applied.rows.length && applied.rows.length === before.rows.length && appliedCount === beforeCount && applied.search === before.search) wrong.push("after Show Results nothing changed: same rows, same counts, same address");
    // reopen: the sheet remembers the choices; Clear Filters puts everything back
    await filter.click({ timeout: 6000 }).catch(() => null);
    await until(sheet, 8000);
    await sleep(1300); // a tap while the sheet is still sliding up is not taken, for a person either
    const remembered = await sheetField("Lead source");
    if (!/Added by hand/.test(remembered)) wrong.push(`reopening the filter sheet shows the source as "${remembered.slice(0, 40)}", not the one chosen`);
    await page.getByRole("button", { name: /^Clear Filters/ }).filter({ visible: true }).first().click({ timeout: 5000 }).catch(() => null);
    await sleep(1200);
    if (await sheet()) await page.getByRole("button", { name: /^Show Results/ }).filter({ visible: true }).first().click({ timeout: 5000 }).catch(() => null);
    await sleep(2200);
    const cleared = await leadsSnap(page);
    if (cleared.search !== before.search) wrong.push(`after Clear Filters the address is "${cleared.search || "none"}", it was "${before.search || "none"}"`);
    const afterCount = tabCount(cleared, /^To Call/);
    if (beforeCount != null && afterCount != null && beforeCount !== afterCount) wrong.push(`To Call counted ${beforeCount} before the filters and ${afterCount} after Clear Filters`);
    if (cleared.rows.length !== before.rows.length) wrong.push(`the list shows ${cleared.rows.length} leads after Clear Filters, ${before.rows.length} before`);
    return wrong.length ? fail(wrong.join("; "), "/leads", "Filter leads", wrong.every((w) => /garbled/.test(w)) ? "MINOR" : "MAJOR") : pass(`source, date and follow-up filters apply (${applied.rows.length} lead${applied.rows.length === 1 ? "" : "s"} shown), the sheet remembers them, and Clear Filters puts the list back (${cleared.rows.length})`, "/leads", "Filter leads");
  },
};

// ---- Leads: the filter sheet, one control at a time (J050, J052, J053, J055); nothing is saved ---------------------------------
// The sheet slides up and a tap in that slide is not taken (for a person either), so every open waits 1.3 s; each filter is a picker: open it, then choose the row.
const filterKit = (page) => {
  const sheet = () => page.getByRole("dialog").filter({ visible: true }).count();
  const button = () => page.getByRole("button", { name: /^Filter leads/ }).filter({ visible: true }).first();
  const field = async (name) => ((await page.getByRole("dialog").getByRole("button", { name: new RegExp(`^${name}`) }).first().textContent().catch(() => "")) || "").replace(/\s+/g, " ").trim();
  return {
    sheet,
    async open() {
      await button().click({ timeout: 6000 }).catch(() => null);
      if (!(await until(sheet, 8000))) return false;
      await sleep(1300);
      return true;
    },
    field,
    async pick(name, option) {
      const opener = page.getByRole("dialog").getByRole("button", { name: new RegExp(`^${name}`) }).first();
      if (!(await opener.count())) return `the filter sheet has no ${name} choice`;
      for (let attempt = 0; attempt < 2; attempt++) {
        await opener.click({ timeout: 5000 }).catch(() => null);
        await sleep(500);
        const row = page.getByRole("option", { name: option, exact: true }).filter({ visible: true }).first();
        if (!(await row.count())) return `${name} has no "${option}" choice`;
        await row.click({ timeout: 5000 }).catch(() => null);
        await sleep(500);
        if ((await field(name)).includes(option)) return "";
      }
      return `choosing "${option}" in ${name} does not take (it reads "${(await field(name)).slice(0, 40)}")`;
    },
    async show() {
      await page.getByRole("button", { name: /^Show Results/ }).filter({ visible: true }).first().click({ timeout: 5000 }).catch(() => null);
      await sleep(2200);
    },
    async clear() {
      await page.getByRole("button", { name: /^Clear Filters/ }).filter({ visible: true }).first().click({ timeout: 5000 }).catch(() => null);
      await sleep(1200);
      if (await sheet()) await this.show();
      await sleep(1000);
    },
    async badge() {
      return (await button().textContent().catch(() => "")).replace(/\s+/g, " ").trim();
    },
  };
};

const J053 = {
  route: "/leads",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("tab", { name: /^To Call/ }).first().count(), 25000);
    const kit = filterKit(page);
    const before = await leadsSnap(page);
    if (!(await kit.open())) return fail("Filter leads does not open the filter sheet", "/leads", "Filter leads");
    const problem = await kit.pick("Lead source", "Added by hand");
    if (problem) return fail(problem, "/leads", "Show Results");
    await kit.show();
    const wrong = [];
    if (await kit.sheet()) wrong.push("Show Results leaves the filter sheet open");
    const after = await leadsSnap(page);
    if (after.search === before.search) wrong.push(`Show Results leaves the address as it was (${after.search || "none"}): the choice is not in the link`);
    const badge = await kit.badge();
    // the button reads "Filter" with the number of filters after it ("Filter1")
    if (!/1\s*$/.test(badge)) wrong.push(`one filter is applied but the Filter button reads "${badge.slice(0, 30)}"`);
    const count = tabCount(after, /^All Leads/);
    if (count != null && after.tabs.length && !after.rows.length && !after.empty) wrong.push("the list is empty and says nothing about the filter");
    await kit.open();
    await kit.clear();
    return wrong.length ? fail(wrong.join("; "), "/leads", "Show Results") : pass(`Show Results closes the sheet, puts the choice in the address (${after.search}) and the Filter button reads "${badge.slice(0, 20)}"`, "/leads", "Show Results");
  },
};

const J055 = {
  route: "/leads",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("tab", { name: /^To Call/ }).first().count(), 25000);
    const kit = filterKit(page);
    const before = await leadsSnap(page);
    const badgeBefore = await kit.badge();
    if (!(await kit.open())) return fail("Filter leads does not open the filter sheet", "/leads", "Filter leads");
    const problem = await kit.pick("Lead source", "Added by hand");
    if (problem) return fail(problem, "/leads", "Close Filter sheet");
    await page.getByRole("dialog").getByRole("button", { name: /^Close/ }).first().click({ timeout: 5000 }).catch(() => null);
    await sleep(1500);
    const wrong = [];
    if (await kit.sheet()) wrong.push("Close leaves the filter sheet open");
    const after = await leadsSnap(page);
    if (after.search !== before.search) wrong.push(`closing the sheet applied the draft: the address is now ${after.search || "none"}`);
    if (JSON.stringify(after.tabs) !== JSON.stringify(before.tabs)) wrong.push(`closing the sheet changed the counts (${before.tabs.map((t) => t.name).join(" / ")} to ${after.tabs.map((t) => t.name).join(" / ")})`);
    if ((await kit.badge()) !== badgeBefore) wrong.push(`the Filter button changed from "${badgeBefore.slice(0, 20)}" to "${(await kit.badge()).slice(0, 20)}" without applying anything`);
    if (await kit.open()) {
      const reopened = await kit.field("Lead source");
      if (!/Every source/.test(reopened)) wrong.push(`reopening the sheet still shows the draft ("${reopened.slice(0, 40)}"), it should be back to Every source`);
      await page.getByRole("dialog").getByRole("button", { name: /^Close/ }).first().click({ timeout: 5000 }).catch(() => null);
      await sleep(900);
    }
    return wrong.length ? fail(wrong.join("; "), "/leads", "Close Filter sheet") : pass("Close drops the draft choices: nothing is applied, the counts and the Filter button stay, and the sheet reopens clean", "/leads", "Close Filter sheet");
  },
};

const J050 = {
  route: "/leads",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("tab", { name: /^To Call/ }).first().count(), 25000);
    const kit = filterKit(page);
    const before = await leadsSnap(page);
    if (!(await kit.open())) return fail("Filter leads does not open the filter sheet", "/leads", "Filter leads");
    await page.getByRole("dialog").getByRole("button", { name: /^Lead source/ }).first().click({ timeout: 5000 }).catch(() => null);
    await sleep(600);
    const options = await page.getByRole("option").filter({ visible: true }).evaluateAll((els) => els.map((e) => (e.textContent || "").replace(/\s+/g, " ").trim()));
    const wrong = [];
    const want = [/^Every source/, /meta/i, /google/i, /website/i, /upload|import|sheet/i];
    for (const rx of want) if (!options.some((o) => rx.test(o))) wrong.push(`the Lead source choices (${options.slice(0, 8).join(", ")}) have nothing like ${rx.source}`);
    await page.keyboard.press("Escape").catch(() => null);
    await sleep(500);
    const problem = await kit.pick("Lead source", "Added by hand");
    if (problem) return fail(problem, "/leads", "Lead Source filter");
    await kit.show();
    const after = await leadsSnap(page);
    const all0 = tabCount(before, /^All Leads/);
    const all1 = tabCount(after, /^All Leads/);
    if (!/source=/.test(after.search)) wrong.push(`choosing a source does not reach the address (${after.search || "none"})`);
    if (all0 != null && all1 != null && all1 > all0) wrong.push(`All Leads went from ${all0} to ${all1} after narrowing by source`);
    if (all0 != null && all1 != null && all1 === all0 && after.search) wrong.push(`All Leads still counts ${all1} after choosing Added by hand: the source did not narrow anything`);
    await kit.open();
    await kit.clear();
    return wrong.length ? fail(wrong.join("; "), "/leads", "Lead Source filter") : pass(`Lead source offers ${options.length - 1} sources and Added by hand narrows All Leads from ${all0} to ${all1}`, "/leads", "Lead Source filter");
  },
};

const J052 = {
  route: "/leads",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("tab", { name: /^To Call/ }).first().count(), 25000);
    const kit = filterKit(page);
    const wrong = [];
    const seen = [];
    for (const [option, key] of [["Today", "today"], ["Overdue", "overdue"], ["Upcoming", "upcoming"]]) {
      if (!(await kit.open())) return fail("Filter leads does not open the filter sheet", "/leads", "Follow-up filter");
      const problem = await kit.pick("Follow-up", option);
      if (problem) return fail(problem, "/leads", "Follow-up filter");
      await kit.show();
      const now = await leadsSnap(page);
      seen.push(`${option}: ${now.search || "none"}`);
      if (!new RegExp(`when=${key}`).test(now.search)) wrong.push(`${option} does not reach the address (${now.search || "none"})`);
      if (!now.rows.length && !now.empty) wrong.push(`${option} leaves an empty list that says nothing`);
      await kit.open();
      await kit.clear();
    }
    return wrong.length ? fail(wrong.join("; "), "/leads", "Follow-up filter") : pass(`Today, Overdue and Upcoming each reach the address and clear again (${seen.join("; ")})`, "/leads", "Follow-up filter");
  },
};

// ---- Reports: the hub with its All, Calls and Leads tabs (J244, J247, J251, J252, J254); nothing is saved --------------------------------------
const reportsTab = (page, name) => page.getByRole("tab", { name, exact: true }).or(page.getByRole("radio", { name, exact: true })).filter({ visible: true }).first();
const tabOn = async (locator) => (await locator.evaluate((e) => e.getAttribute("aria-selected") === "true" || e.getAttribute("aria-checked") === "true" || e.checked === true).catch(() => false));

const J244 = {
  route: "/reports",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("heading", { name: "What stands out" }).first().count(), 20000);
    const read = await page.evaluate(() => {
      const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
      const main = document.querySelector("main") || document.body;
      const heads = [...main.querySelectorAll("h1,h2,h3")].filter(visible).map((e) => e.textContent.trim());
      return { heads, links: [...main.querySelectorAll("a[href]")].filter(visible).map((e) => ({ text: (e.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60), href: e.getAttribute("href") })) };
    });
    const wrong = [];
    for (const h of ["Reports", "What stands out", "Calls", "Leads"]) if (!read.heads.includes(h)) wrong.push(`Reports has no "${h}" heading (${read.heads.join(" / ").slice(0, 60)})`);
    if (!read.links.length) wrong.push("Reports shows no summary line or tile to open");
    const empty = read.links.filter((l) => !l.text || !l.href);
    if (empty.length) wrong.push(`${empty.length} tile${empty.length > 1 ? "s" : ""} on Reports have no words or no destination`);
    return wrong.length ? fail(wrong.join("; "), "/reports", "summary") : pass(`Reports shows "What stands out" and the Calls and Leads groups with ${read.links.length} lines that open something`, "/reports", "summary");
  },
};

const J247 = {
  route: "/reports",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("heading", { name: "What stands out" }).first().count(), 20000);
    const period = await page.evaluate(() => {
      const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
      const rx = /^(today|this week|this month|last 7 days|last 30 days|period|date range|week|month)\b/i;
      return [...document.querySelectorAll("button,[role=tab],[role=radio],[role=combobox],select,input")].filter(visible).map((e) => (e.getAttribute("aria-label") || e.textContent || "").replace(/\s+/g, " ").trim()).filter((t) => rx.test(t));
    });
    if (!period.length) return blocked("Reports has no period control in this version (its controls are the All, Calls and Leads tabs): nothing to change; the journey needs the period selector", "/reports", "period");
    return blocked(`Reports shows a period control (${period.slice(0, 3).join(", ")}); changing it and comparing the numbers is not scripted yet`, "/reports", "period");
  },
};

const J251 = {
  route: "/reports",
  async run({ tab }) {
    const page = tab.page;
    await until(() => reportsTab(page, "Calls").count(), 20000);
    const gap = await page.evaluate(() => {
      const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
      const main = document.querySelector("main") || document.body;
      const h = [...main.querySelectorAll("h1,h2")].find((e) => (e.textContent || "").trim() === "Reports" && visible(e));
      const pill = [...main.querySelectorAll("[role=tab],[role=radio],button")].find((e) => /^all$/i.test((e.textContent || "").trim()) && visible(e));
      if (!h || !pill) return null;
      const a = h.getBoundingClientRect();
      const b = pill.getBoundingClientRect();
      return { gap: Math.round(b.top - a.bottom), overlap: b.top < a.bottom };
    });
    if (!gap) return fail("Reports has no heading or no tab row to measure", "/reports", "heading and tabs");
    if (gap.overlap) return fail(`the tab row sits ${-gap.gap}px over the Reports heading`, "/reports", "heading and tabs");
    if (gap.gap < 8) return fail(`only ${gap.gap}px between the Reports heading and the tab row, less than 8px`, "/reports", "heading and tabs");
    return pass(`${gap.gap}px between the Reports heading and the tab row`, "/reports", "heading and tabs");
  },
};

const J252 = {
  route: "/reports",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("heading", { name: "What stands out" }).first().count(), 20000);
    const covered = await page.evaluate(() => {
      const visible = (e) => e.checkVisibility && e.checkVisibility() && e.getBoundingClientRect().width > 0;
      const main = document.querySelector("main") || document.body;
      const bad = [];
      let n = 0;
      for (const a of [...main.querySelectorAll("a[href]")].filter(visible)) {
        n += 1;
        a.scrollIntoView({ block: "center", inline: "center" });
        const r = a.getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        if (!hit || !(hit === a || a.contains(hit) || hit.contains(a))) bad.push(`${(a.textContent || "").replace(/\s+/g, " ").trim().slice(0, 30)} (under ${hit ? hit.tagName + " " + (hit.textContent || "").replace(/\s+/g, " ").trim().slice(0, 30) : "nothing"})`);
      }
      return { n, bad };
    });
    if (!covered.n) return fail("Reports shows no tile to check", "/reports", "tiles");
    if (covered.bad.length) return fail(`${covered.bad.length} of ${covered.n} Reports tiles are under something else: ${covered.bad.slice(0, 3).join("; ")}`, "/reports", "tiles");
    return pass(`none of the ${covered.n} Reports tiles has a card or notice over it`, "/reports", "tiles");
  },
};

const J254 = {
  route: "/reports",
  async run({ tab }) {
    const page = tab.page;
    const calls = reportsTab(page, "Calls");
    await until(() => calls.count(), 20000);
    if (!(await calls.count())) return fail("Reports has no Calls tab", "/reports", "tab bar");
    await calls.click({ timeout: 6000 }).catch(() => null);
    await sleep(1200);
    if (!(await tabOn(calls))) return fail("pressing Calls does not select it", "/reports", "tab bar");
    const before = new URL(page.url()).search;
    const tile = page.locator("main a[href]").filter({ visible: true }).first();
    const href = (await tile.getAttribute("href").catch(() => "")) || "";
    if (!href) return fail("the Calls tab shows no tile to open", "/reports", "tab bar");
    await tile.click({ timeout: 6000 }).catch(() => null);
    await until(async () => new URL(page.url()).pathname !== "/reports", 12000);
    await sleep(800);
    await page.goBack({ timeout: 10000 }).catch(() => null);
    await until(() => reportsTab(page, "Calls").count(), 15000);
    await sleep(1000);
    const back = reportsTab(page, "Calls");
    const wrong = [];
    if (new URL(page.url()).pathname !== "/reports") wrong.push(`Back from ${href.slice(0, 30)} lands on ${new URL(page.url()).pathname}, not Reports`);
    else if (!(await tabOn(back))) wrong.push(`Back to Reports does not keep the Calls tab (the address was "${before || "no query"}", now "${new URL(page.url()).search || "no query"}")`);
    return wrong.length ? fail(wrong.join("; "), "/reports", "tab bar") : pass(`the Calls tab is still selected after opening ${href.slice(0, 30)} and pressing Back`, "/reports", "tab bar");
  },
};

// Plan rows do not run under the walks' write guard, so every plan here refuses any write itself for as long as it runs (the route is taken off again afterwards:
// the after-call plans share the tab and need their own writes to pass).
const guarded = (plan) => ({
  ...plan,
  async run(ctx) {
    const refuse = (route) => (["GET", "HEAD", "OPTIONS"].includes(route.request().method()) ? route.fallback() : route.abort("blockedbyclient"));
    await ctx.tab.context.route("**/*", refuse);
    try {
      return await plan.run(ctx);
    } finally {
      await ctx.tab.context.unroute("**/*", refuse).catch(() => null);
    }
  },
});

module.exports = { plans: { J244: guarded(J244), J247: guarded(J247), J251: guarded(J251), J252: guarded(J252), J254: guarded(J254), J050: guarded(J050), J052: guarded(J052), J053: guarded(J053), J055: guarded(J055), J142: guarded(J142), J177: guarded(J177), J181: guarded(J181), J139: guarded(J162), J141: guarded(J141), J158: guarded(J158), J159: guarded(J141), J162: guarded(J162), J175: guarded(J175), J310: guarded(J310), J323: writeGuarded(J323), J324: guarded(J324), J330: writeGuarded(J330) } };
