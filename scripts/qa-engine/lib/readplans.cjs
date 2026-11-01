// Read-and-assert journeys for Home and Settings (orchestrator order, 1 Nov 2026): J175 and J310 (the "no recording" card and the counters), J324 (theme), J323 and J330
// (profile name, notification preferences). They never save anything: every write stays held and refused by the engine's guard. A journey whose point is the save itself
// (J323, J330) checks that the controls are there and answers "blocked" for the save, because the robot only writes QA robot records.
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
    const home = await page.evaluate(readHome, { labels: TODAY_LABELS, cardSource: CARD.source });
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

const J330 = {
  route: "/settings/notifications",
  async run({ tab }) {
    const page = tab.page;
    await until(() => page.getByRole("switch").first().count(), 15000);
    // Vibration is a phone setting: a computer does not show it
    const want = [["New enquiry", /^New enquiry/i], ["Follow-up due", /^Follow-up due/i], ["Missed follow-up", /^Missed follow-up/i], ["Quiet outside working hours", /^Quiet outside working hours/i]];
    if (tab.dev.phone) want.push(["Vibration", /^Vibration/i]);
    const missing = [];
    for (const [label, name] of want) if (!(await page.getByRole("switch", { name }).filter({ visible: true }).count())) missing.push(label);
    if (!(await page.getByRole("button", { name: /^Send me a test notification/ }).filter({ visible: true }).count())) missing.push("Send me a test notification");
    if (missing.length) return fail(`the notification settings are missing: ${missing.join(", ")}`, "/settings/notifications", "notification switches");
    return blocked("the switches and the test button are there; saving and applying a change is not exercised, because it changes this seller's own settings and the robot only writes QA robot records (needs the owner's say-so to toggle and put back)", "/settings/notifications", "notification switches");
  },
};

const J323 = {
  route: "/settings/profile",
  async run({ tab }) {
    const page = tab.page;
    // the name lives behind "Edit details" (Full name, Phone number, Save details, Cancel); the top form is user id, job title and team
    const edit = page.getByRole("button", { name: /^Edit details/ }).filter({ visible: true }).first();
    await until(() => edit.count(), 15000);
    if (!(await edit.count())) return fail("the Profile page has no Edit details button", "/settings/profile", "Edit details");
    await edit.click({ timeout: 6000 }).catch(() => null);
    const field = page.getByLabel(/^Full name/).filter({ visible: true }).first();
    await until(() => field.count(), 8000);
    if (!(await field.count())) return fail('"Edit details" shows no Full name field', "/settings/profile", "Full name");
    const save = page.getByRole("button", { name: /^Save details/ }).filter({ visible: true }).first();
    const cancel = page.getByRole("button", { name: /^Cancel/ }).filter({ visible: true }).first();
    if (!(await save.count())) return fail("Edit details has no Save details button", "/settings/profile", "Save details");
    const before = await field.inputValue();
    await field.fill(`${before} QA`).catch(() => null);
    await sleep(600);
    const enabled = await save.isEnabled().catch(() => false);
    const wrong = [];
    if (!enabled) wrong.push("typing in Full name does not enable Save details");
    if (await cancel.count()) {
      await cancel.click({ timeout: 6000 }).catch(() => null);
      await sleep(900);
      const shown = await page.evaluate(() => (document.querySelector("main") || document.body).innerText.replace(/\s+/g, " "));
      if (/ QA\b/.test(shown) && !before.includes(" QA")) wrong.push("Cancel leaves the typed name on the page");
    } else wrong.push("Edit details has no Cancel button");
    if (wrong.length) return fail(wrong.join("; "), "/settings/profile", "Edit details");
    return blocked("Edit details opens Full name and Save details responds to typing, and Cancel puts the name back; saving a new name and seeing it everywhere is not exercised, because it changes this seller's own profile and the robot only writes QA robot records (needs the owner's say-so to rename and put back)", "/settings/profile", "Edit details");
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
      return visible(e) && /^see (all|details)/i.test(nameOf(e)) && Math.abs(r.top + r.height / 2 - mid) <= 30 && r.left >= ha.left;
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
    const opened = await until(async () => (new URL(page.url()).searchParams.get("lead") || "") && (await page.getByRole("heading", { name: nameLink.text, exact: true }).filter({ visible: true }).count()), 15000);
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

module.exports = { plans: { J142: guarded(J142), J177: guarded(J177), J181: guarded(J181), J139: guarded(J162), J141: guarded(J141), J158: guarded(J158), J159: guarded(J141), J162: guarded(J162), J175: guarded(J175), J310: guarded(J310), J323: guarded(J323), J324: guarded(J324), J330: guarded(J330) } };
