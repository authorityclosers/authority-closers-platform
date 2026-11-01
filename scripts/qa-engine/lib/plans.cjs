// Read-only journey plans beyond the 99 clicks: each is a short script with an assertion from Dipak's handoff or
// from a ledger finding. A plan returns { outcome: "pass" | "fail" | "blocked", reason, route, selector, severity? }.
// "blocked" is for a thing the handoff asks for that this build is not expected to have yet; "fail" is for
// what is there and wrong (or what the handoff has required since it was written). Plans press nothing that
// calls, saves, completes or starts paid work. `as` runs the plan as a particular fictional seller.
const { go, settle, sleep } = require("./session.cjs");
const { probe, routeOf } = require("./probe.cjs");

const visible = async (page, text) => {
  for (const t of [].concat(text)) {
    const re = t instanceof RegExp ? t : null;
    const found = re ? page.getByText(re) : page.getByText(t, { exact: false });
    if (await found.filter({ visible: true }).count()) return typeof t === "string" ? t : t.source;
  }
  return null;
};
const pass = (reason, route, selector = "") => ({ outcome: "pass", reason, route, selector });
const fail = (reason, route, selector = "", severity = "MAJOR") => ({ outcome: "fail", reason, route, selector, severity });
const blocked = (reason, route, selector = "") => ({ outcome: "blocked", reason, route, selector });

async function open(tab, route) {
  const r = await go(tab, route, { wait: 25000 });
  return r.ok ? null : fail(`the page did not open: ${r.error}`, routeOf(route), "page load");
}

const BOTH = new Set(["priya", "rohan", "farah", "karan", "pooja", "vikas"]);
const NAV_WANT = ["Home", "Leads", "Ask Dipak", "Reports", "Growth"];

async function noFindings(tab, route, rules, mark) {
  const found = (await probe(tab, route, { mark, skipAxe: !rules.some((r) => r.startsWith("axe:")) })).filter((f) => rules.includes(f.rule));
  return found.length ? fail(found.map((f) => `${f.summary}: ${f.detail}`.slice(0, 160)).join(" | "), route, found[0].selector, found[0].severity) : null;
}

const plans = {
  // Mode: only people with both lead types see the Inbound / Cold selector.
  J136: { route: "/dashboard", run: selectorByType },
  J161: { as: "sneha", route: "/dashboard", run: selectorByType },
  // No Recent Calls block on Home; history lives in Reports.
  J140: { route: "/dashboard", run: noRecentCalls },
  J163: { route: "/dashboard", run: noRecentCalls },
  // Bottom navigation: Home, Leads, Ask Dipak, Reports, Growth; no Chats or Calls tab (phone only).
  J173: {
    route: "/dashboard",
    phoneOnly: true,
    async run({ tab }) {
      const page = tab.page;
      const bar = page.getByRole("navigation").filter({ visible: true });
      const names = await bar.locator("a[href],button").evaluateAll((els) => els.map((e) => (e.getAttribute("aria-label") || e.textContent || "").replace(/\s+/g, " ").trim()).filter(Boolean)).catch(() => []);
      const lower = names.map((n) => n.toLowerCase());
      const missing = NAV_WANT.filter((w) => !lower.some((n) => n.startsWith(w.toLowerCase())));
      const extra = ["Chats", "Calls"].filter((w) => lower.some((n) => n.startsWith(w.toLowerCase())));
      return missing.length || extra.length
        ? fail(`bottom bar shows ${names.slice(0, 8).join(" / ")}${missing.length ? `; missing ${missing.join(", ")}` : ""}${extra.length ? `; should not have ${extra.join(", ")}` : ""}`, "/dashboard", "bottom navigation")
        : pass("bottom bar is Home, Leads, Ask Dipak, Reports, Growth", "/dashboard", "bottom navigation");
    },
  },
  // Footer links to manager pages are hidden from a Member.
  J262: {
    route: "/dashboard",
    async run({ tab }) {
      const hit = ["Team coaching", "People", "Insights"].filter(Boolean);
      const shown = [];
      for (const name of hit) if (await tab.page.getByRole("link", { name, exact: true }).filter({ visible: true }).count()) shown.push(name);
      return shown.length ? fail(`a Member sees links to ${shown.join(", ")}`, "/dashboard", `link "${shown[0]}"`) : pass("no manager links for a Member", "/dashboard");
    },
  },
  // A seller never reaches Team coaching: the page must not break or show a raw 403.
  J258: {
    route: "/coaching?view=team",
    async run({ tab, mark }) {
      const bad = await noFindings(tab, "/coaching?view=team", ["page:error-text", "page:blank", "api:4xx", "api:5xx"], mark);
      return bad ? fail(`a seller opening Team coaching gets a broken page: ${bad.reason}`, "/coaching?view=team", "team coaching") : pass("Team coaching is closed cleanly", "/coaching?view=team");
    },
  },
  // A Member never sees plans and prices.
  J326: {
    route: "/settings/plan",
    async run({ tab }) {
      const text = (await tab.page.evaluate(() => document.body.innerText || "").catch(() => "")).replace(/\s+/g, " ");
      const price = /(?:₹|Rs\.?)\s?\d[\d,]*/.exec(text);
      const choose = /choose a plan/i.test(text);
      const route = "/settings/plan";
      if (price || choose) return fail(`a Member sees ${price ? `a price (${price[0]})` : "Choose a plan"}`, route, "plans and prices");
      const err = await visible(tab.page, [/couldn.?t load|something went wrong|not found|forbidden|403|404/i]);
      return err ? fail(`the page shows an error (${err})`, route, "plans page", "MINOR") : pass("no plans or prices for a Member", route);
    },
  },
  // Performance opens on a direct load and leaves its skeleton.
  J263: { route: "/performance", run: ({ tab, mark }) => cleanLoad(tab, "/performance", mark) },
  J270: { route: "/performance", run: ({ tab, mark }) => cleanLoad(tab, "/performance", mark) },
  J244: { route: "/reports", run: ({ tab, mark }) => cleanLoad(tab, "/reports", mark) },
  J255: { route: "/coaching", run: ({ tab, mark }) => cleanLoad(tab, "/coaching", mark) },
  // Nothing covers the controls: the alert card and banners never hide Search, Filter, the avatar, +, bell.
  J166: { route: "/dashboard", run: ({ tab, mark }) => cleanLoad(tab, "/dashboard", mark, ["layout:covered"]) },
  J190: { route: "/leads", run: ({ tab, mark }) => cleanLoad(tab, "/leads", mark, ["layout:covered"]) },
  J299: { route: "/dashboard", run: ({ tab, mark }) => cleanLoad(tab, "/dashboard", mark, ["layout:covered"]) },
  J155: { route: "/leads", phoneOnly: true, run: ({ tab, mark }) => cleanLoad(tab, "/leads", mark, ["layout:covered", "layout:overflow-x"]) },
  // Home in dark mode keeps its contrast.
  J167: { route: "/dashboard", themeOnly: "dark", run: ({ tab, mark }) => cleanLoad(tab, "/dashboard", mark, ["axe:color-contrast"]) },
  // Full width at 1440 and 1920, several columns, no dead area.
  J168: { route: "/dashboard", desktopOnly: true, run: ({ tab }) => fullWidth(tab, "/dashboard") },
  J188: { route: "/leads", desktopOnly: true, run: ({ tab }) => fullWidth(tab, "/leads") },
  J271: { route: "/performance", desktopOnly: true, run: ({ tab }) => fullWidth(tab, "/performance") },
  J331: { route: "/account", desktopOnly: true, run: ({ tab }) => fullWidth(tab, "/account") },
  // Search with no match, then Clear Search.
  J180: {
    route: "/leads?view=all",
    async run({ tab }) {
      const page = tab.page;
      const box = page.getByRole("searchbox", { name: "Search leads" }).or(page.getByRole("textbox", { name: "Search leads" })).filter({ visible: true });
      if (!(await box.count())) return blocked("no search box on this layout yet", "/leads", "search leads");
      await box.first().fill("zzqx no such lead");
      await settle(tab, 8000);
      await sleep(800);
      const said = await visible(page, "No leads match these filters");
      if (!said) return fail("a search with no match does not say 'No leads match these filters'", "/leads", "search leads");
      const clear = page.getByRole("button", { name: /clear (search|filters)/i }).filter({ visible: true });
      if (!(await clear.count())) return fail("no Clear Search / Clear Filters after a search with no match", "/leads", "clear search");
      await clear.first().click().catch(() => null);
      await settle(tab, 8000);
      const back = await page.getByRole("button", { name: /^Open / }).filter({ visible: true }).count();
      return back ? pass("no-match wording shown and Clear Search brings the list back", "/leads", "search leads") : fail("Clear Search does not bring the list back", "/leads", "clear search");
    },
  },
  // The nine stages in the stage selector.
  J182: {
    route: "/leads",
    async run({ tab }) {
      const select = tab.page.locator("select").filter({ has: tab.page.locator("option", { hasText: "Interested" }) }).filter({ visible: true });
      if (!(await select.count())) return blocked("no stage selector on this layout yet", "/leads", "stage selector");
      const options = (await select.first().evaluate((el) => [...el.options].map((o) => o.textContent.replace(/\s+/g, " ").trim()))).map((o) => o.replace(/\s*\d+$/, ""));
      const want = ["Not Connected", "Open Leads", "Interested", "Meeting Scheduled", "Meeting Done", "Won", "Closed / Lost", "Junk Lead"];
      const missing = want.filter((w) => !options.some((o) => o.startsWith(w)));
      const first = options.find((o) => /^(New Lead|Unworked)/.test(o));
      return missing.length || !first
        ? fail(`stage selector lacks ${missing.concat(first ? [] : ["New Lead or Unworked"]).join(", ")} (has ${options.join(" / ")})`, "/leads", "stage selector")
        : pass(`nine stages present (${first} first)`, "/leads", "stage selector");
    },
  },
  // Cold rows say Unworked, never "New lead" and "Unworked" together.
  J186: {
    as: "priya",
    route: "/leads",
    async run({ tab }) {
      const page = tab.page;
      const cold = page.getByRole("radio", { name: "Cold Leads" }).filter({ visible: true });
      if (!(await cold.count())) return blocked("no Inbound|Cold selector here", "/leads", "cold selector");
      await cold.first().click().catch(() => null);
      await settle(tab, 8000);
      const both = await page.evaluate(() => [...document.querySelectorAll("li,tr,[role=row],article,button")].filter((el) => el.checkVisibility && el.checkVisibility()).filter((el) => /new lead/i.test(el.innerText || "") && /unworked/i.test(el.innerText || "")).length);
      return both ? fail(`${both} cold row(s) say both "New lead" and "Unworked"`, "/leads?side=cold", "cold rows") : pass("no cold row says both words", "/leads?side=cold", "cold rows");
    },
  },
  // Switching Inbound to Cold changes what the Home counters count.
  J160: {
    as: "priya",
    route: "/dashboard",
    async run({ tab }) {
      const page = tab.page;
      const inbound = page.getByRole("radio", { name: "Inbound Leads" }).filter({ visible: true });
      const cold = page.getByRole("radio", { name: "Cold Leads" }).filter({ visible: true });
      if (!(await inbound.count()) || !(await cold.count())) return blocked("no Inbound|Cold selector on Home yet", "/dashboard", "lead type selector");
      const read = () => page.evaluate(() => (document.querySelector("main") || document.body).innerText.replace(/\s+/g, " ").slice(0, 700));
      await inbound.first().click().catch(() => null);
      await settle(tab, 8000);
      const a = await read();
      await cold.first().click().catch(() => null);
      await settle(tab, 8000);
      const b = await read();
      await inbound.first().click().catch(() => null);
      return a === b ? fail("switching Inbound to Cold changes nothing on Home", "/dashboard", "lead type selector") : pass("Home changes with the lead type", "/dashboard", "lead type selector");
    },
  },
};

async function selectorByType({ tab, alias }) {
  const page = tab.page;
  const radios = await page.getByRole("radio", { name: /^(Inbound|Cold) Leads$/ }).filter({ visible: true }).count();
  const both = BOTH.has(alias);
  if (both && radios >= 2) return pass("both lead types: selector shown", "/dashboard", "lead type selector");
  if (!both && radios === 0) return pass("one lead type: no selector, as the handoff says", "/dashboard", "lead type selector");
  return both
    ? blocked("selector not on Home yet for a seller with both types", "/dashboard", "lead type selector")
    : fail(`a seller with one lead type sees the selector (${radios} option(s))`, "/dashboard", "lead type selector");
}

async function noRecentCalls({ tab }) {
  const shown = await visible(tab.page, [/recent calls/i]);
  return shown ? fail("Home still shows a Recent Calls block; the handoff moves history to Reports", "/dashboard", "recent calls") : pass("no Recent Calls block on Home", "/dashboard", "recent calls");
}

async function cleanLoad(tab, route, mark, rules = ["page:blank", "page:stuck-skeleton", "page:error-text", "api:5xx", "script:page-error"]) {
  const bad = await noFindings(tab, routeOf(route), rules, mark);
  return bad || pass("opens cleanly", routeOf(route));
}

async function fullWidth(tab, route) {
  const share = await tab.page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const main = document.querySelector("main") || document.body;
    let right = 0;
    for (const el of main.querySelectorAll("*")) {
      if (!el.checkVisibility || !el.checkVisibility()) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 40 || r.height < 12) continue;
      right = Math.max(right, r.right);
    }
    const mainBox = main.getBoundingClientRect();
    return { vw, right: Math.round(right), mainWidth: Math.round(mainBox.width) };
  });
  const used = share.right / share.vw;
  return used < 0.8
    ? fail(`content ends at ${share.right}px of a ${share.vw}px screen (${Math.round(used * 100)}%): an empty strip on the right`, routeOf(route), "main content")
    : pass(`content reaches ${Math.round(used * 100)}% of the width`, routeOf(route), "main content");
}

function applies(plan, tab, row) {
  if (plan.phoneOnly && !tab.dev.phone) return false;
  if (plan.desktopOnly && tab.dev.phone) return false;
  if (plan.themeOnly && row.theme !== plan.themeOnly) return false;
  return true;
}

// the after-call journeys (they write, on the QA robot pool only)
Object.assign(plans, require("./aftercall.cjs").plans);
// read-and-assert journeys for Home and Settings (nothing is saved)
Object.assign(plans, require("./readplans.cjs").plans);

module.exports = { plans, applies, open };
