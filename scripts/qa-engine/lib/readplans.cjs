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

module.exports = { plans: { J175: guarded(J175), J310: guarded(J310), J323: guarded(J323), J324: guarded(J324), J330: guarded(J330) } };
