// Dipak's 99 click destinations (Home + Leads handoff, 31 Oct 2026, pp. 14-20), as checks. data/click-map.json
// holds each one: where to start, which control, what must follow (page, preselected context, words) and whether Back
// restores the page. A check never presses a control that calls, saves, completes or starts paid work.
const fs = require("fs");
const path = require("path");
const cfg = require("./config.cjs");
const { go, settle, sleep } = require("./session.cjs");

const manifest = JSON.parse(fs.readFileSync(path.join(cfg.ROOT, "data", "click-map.json"), "utf8"));
const byId = new Map(manifest.destinations.map((e) => [e.id, e]));

function atSize(entry, phone) {
  const size = phone ? "phone" : "desktop";
  return { ...entry, ...((entry.at || {})[size] || {}) };
}

function locate(page, control) {
  if (control.css) return page.locator(control.css).filter({ visible: true });
  if (control.role === "combobox") {
    return page
      .locator("select")
      .filter({ has: page.locator("option", { hasText: control.option || "" }) })
      .filter({ visible: true });
  }
  const name = control.regex ? new RegExp(control.name) : control.name;
  const found = page.getByRole(control.role, { name, exact: !!control.exact });
  return (control.role === "searchbox" ? found.or(page.getByRole("textbox", { name, exact: !!control.exact })) : found).filter({ visible: true });
}

const where = (page) => {
  const url = new URL(page.url());
  return { path: url.pathname, query: Object.fromEntries(url.searchParams) };
};
const queryMiss = (actual, wanted) => Object.entries(wanted || {}).filter(([k, v]) => !(k in actual) || (v !== "*" && actual[k] !== v));
async function visibleAny(page, words) {
  for (const word of words || []) if (await page.getByText(word, { exact: false }).filter({ visible: true }).count()) return word;
  return null;
}

// One lead this person may open, from the list the Leads page itself reads.
async function leadFor(tab, owner) {
  return tab.page
    .evaluate(async (scope) => {
      const answer = await fetch(`/v1/lead-desk/leads?scope=${scope}`, { credentials: "same-origin" });
      if (!answer.ok) return null;
      const body = await answer.json();
      const list = body.leads || [];
      return ((list.find((l) => l.calls > 0) || list[0] || {}).lead_id) || null;
    }, owner ? "team" : "mine")
    .catch(() => null);
}

// Close and the browser's Back both close the open lead (orchestrator, 1 Nov 2026): the list stays, ?lead=<id> goes; Forward reopens it.
async function leadClose(tab, entry, factor) {
  const page = tab.page;
  const route = entry.start.split("?")[0];
  const label = 'button "Close" and the browser Back';
  const opened = await go(tab, entry.start, { wait: 25000 * factor });
  if (!opened.ok) return { outcome: "skipped", reason: `the start page did not open (${String(opened.error).slice(0, 80)}): not judged` };
  const rows = page.getByRole("button", { name: /^Open (?!lead$)(?!.* menu$)/ }).filter({ visible: true });
  for (let wait = 0; wait < 15 * factor && !(await rows.count()); wait++) await sleep(1000);
  if (!(await rows.count())) return { outcome: "blocked", reason: "no lead in this list to open", route, selector: label };
  const hasLead = () => new URL(page.url()).searchParams.has("lead");
  const wrong = [];
  const openFirst = async () => {
    await rows.first().click({ timeout: 8000 * factor }).catch(() => null);
    await settle(tab, 10000 * factor);
    await sleep(900);
  };
  await openFirst();
  if (!hasLead()) return { outcome: "fail", reason: "opening a lead did not put it in the address (?lead=<id>)", route, selector: label };
  const close = page.getByRole("button", { name: /^Close/ }).filter({ visible: true });
  for (let wait = 0; wait < 10 * factor && !(await close.count()); wait++) await sleep(1000);
  if (!(await close.count())) return { outcome: "missing", reason: "the open lead has no Close button", route, selector: label };
  await close.first().click({ timeout: 8000 * factor }).catch(() => null);
  await settle(tab, 8000 * factor);
  await sleep(900);
  if (hasLead()) wrong.push("Close left the lead id in the address");
  if (!(await rows.count())) wrong.push("the list is gone after Close");
  await openFirst();
  if (!hasLead()) wrong.push("the lead did not open a second time");
  await page.goBack({ timeout: 10000 }).catch(() => null);
  await settle(tab, 8000 * factor);
  await sleep(900);
  if (hasLead()) wrong.push("the browser's Back did not drop the lead id");
  if (new URL(page.url()).pathname !== route) wrong.push(`Back went to ${new URL(page.url()).pathname}, not ${route}`);
  await page.goForward({ timeout: 10000 }).catch(() => null);
  await settle(tab, 8000 * factor);
  await sleep(900);
  if (!hasLead()) wrong.push("Forward did not reopen the lead");
  return wrong.length ? { outcome: "fail", reason: wrong.join("; "), route, selector: label } : { outcome: "pass", reason: "Close and Back drop the id, Forward reopens the lead", route, selector: label };
}

/**
 * Check one destination as this person at this size. Returns
 *   { outcome: "pass" | "fail" | "missing" | "skipped", reason, route, selector, detail }
 * "missing" means the control is not on the page at all (not built yet); "fail" means it is there and leads wrong.
 */
async function check(tab, listed, { lead, owner, slow, onOpened }) {
  const entry = atSize(listed, tab.dev.phone);
  const page = tab.page;
  const factor = slow ? 2 : 1;
  if (entry.kind === "todo") return { outcome: "skipped", reason: "no script for this destination yet" };
  if (entry.kind === "lead-close") return leadClose(tab, entry, factor);
  if (entry.status === "expected-missing" && entry.at && (entry.at[tab.dev.phone ? "phone" : "desktop"] || {}).status === "expected-missing") {
    // the handoff lists it but this layout has none yet: look, and say so
  }
  if (entry.start.includes("{lead}") && !lead) return { outcome: "skipped", reason: "no lead for this person to open" };
  const start = entry.start.replace("{lead}", lead || "");
  const opened = await go(tab, start, { wait: 25000 * factor });
  if (!opened.ok && /ERR_ABORTED|ERR_CONNECTION|ERR_NETWORK|Timeout|timed out|has been closed|Target closed/i.test(opened.error)) return { outcome: "skipped", reason: `the start page did not open (${opened.error.slice(0, 80)}): not judged` };
  if (!opened.ok) return { outcome: "fail", reason: `the page did not open: ${opened.error}`, route: start.split("?")[0], selector: "page load" };
  if (entry.side) {
    const side = page.getByRole("radio", { name: entry.side }).filter({ visible: true });
    // the selector renders with the data: give it 15 s before deciding this seller has none
    for (let wait = 0; wait < 15 * factor && !(await side.count()); wait++) await sleep(1000);
    if (await side.count()) {
      await side.first().click().catch(() => null);
      await settle(tab, 8000 * factor);
    } else {
      // a seller with one lead type has no Inbound|Cold selector: the check cannot be judged for them
      return { outcome: "blocked", reason: `not applicable: this seller has no "${entry.side}" selector (one lead type)`, route: start.split("?")[0], selector: `radio "${entry.side}"` };
    }
  }
  if (entry.type) {
    // some controls only appear after typing (Clear search)
    const box = page.getByRole("searchbox", { name: entry.type.into }).or(page.getByRole("textbox", { name: entry.type.into })).filter({ visible: true });
    if (await box.count()) {
      await box.first().fill(entry.type.text).catch(() => null);
      await settle(tab, 6000 * factor);
    }
  }
  if (onOpened) await onOpened(start.split("?")[0].replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ":id") + (start.includes("?") ? "?" + start.split("?")[1].replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, "") : ""));
  const control = locate(page, { ...entry.control, option: entry.option });
  const label = `${entry.control.role} "${entry.control.name}"`;
  const route = start.split("?")[0].replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ":id");
  // a control that renders after the data arrives gets 15 s on a loaded box before it is called missing
  for (let wait = 0; wait < 15 * factor && !(await control.count()); wait++) await sleep(1000);
  if (!(await control.count()) && entry.id === "93" && lead) {
    // the link shows only when the lead has a reported call
    const calls = await page.evaluate(async (id) => {
      try {
        const r = await fetch(`/v1/lead-desk/leads/${id}`, { credentials: "same-origin" });
        const b = await r.json();
        const l = b.lead || b;
        return typeof l.calls === "number" ? l.calls : null;
      } catch {
        return null;
      }
    }, lead);
    if (calls === 0) return { outcome: "blocked", reason: "not applicable: this seller's lead has no call, so there is no report to open", route, selector: label };
  }
  if (!(await control.count())) return { outcome: "missing", reason: "control not on the page", route, selector: label };
  if (entry.kind === "present" || entry.no_press) return { outcome: "pass", reason: "present", route, selector: label };
  if (entry.kind === "option" && entry.control.role === "button") {
    // the stage Picker: a button that opens a listbox whose rows are named "<stage><count>"
    await control.first().click({ timeout: 8000 * factor }).catch(() => null);
    await sleep(700);
    const wanted = new RegExp("^" + entry.option.replace(/[.*+?^${}()|[\]\\\/]/g, "\\$&") + "\\s*\\d*$");
    const row = page.getByRole("option", { name: wanted }).filter({ visible: true });
    if (!(await row.count())) {
      await page.keyboard.press("Escape").catch(() => null);
      return { outcome: "missing", reason: `the stage list has no "${entry.option}" row`, route, selector: label };
    }
    await row.first().click({ timeout: 8000 * factor }).catch(() => null);
    await settle(tab, 8000 * factor);
    const shown = await control.first().evaluate((el) => (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim()).catch(() => "");
    return shown.includes(entry.option)
      ? { outcome: "pass", reason: `stage ${entry.option}`, route, selector: label }
      : { outcome: "fail", reason: `chose ${entry.option}, the control shows "${shown.slice(0, 60)}"`, route, selector: label };
  }
  if (entry.kind === "option") {
    await control.first().selectOption({ label: entry.option });
    await settle(tab, 8000 * factor);
    const chosen = await control.first().evaluate((el) => (el.options[el.selectedIndex] && el.options[el.selectedIndex].textContent.trim()) || "");
    return chosen.startsWith(entry.option)
      ? { outcome: "pass", reason: `stage ${chosen}`, route, selector: label }
      : { outcome: "fail", reason: `chose ${entry.option}, the list shows ${chosen}`, route, selector: label };
  }
  const before = page.url();
  let tapError = null;
  await control.first().click({ timeout: 8000 * factor }).catch((e) => {
    tapError = String(e).split("\n").find((l) => /intercept|not visible|not stable|detached|disabled|outside/i.test(l)) || String(e).split("\n")[0];
    tapError = tapError.replace(/^\s+/, "").slice(0, 140);
  });
  if (tapError && /<dialog|dialog open|phone-onboarding/i.test(tapError)) {
    return { outcome: "blocked", reason: `a dialog is open over the page (the first-sign-in onboarding), so the tap cannot land: ${tapError.slice(0, 90)}`, route, selector: label };
  }
  if (entry.kind === "nav" && !tapError) {
    // a route compiles on its first visit in dev, and the box is shared: wait for the address to change, up to 25 s
    await page.waitForURL((u) => u.toString() !== before, { timeout: 25000 * factor }).catch(() => null);
  }
  await settle(tab, 10000 * factor);
  await sleep(500);
  if (entry.kind === "select") {
    const state = await control.first().evaluate((el) => el.getAttribute("aria-checked") || el.getAttribute("aria-selected") || String(el.checked ?? "")).catch(() => "unreadable");
    return state === "true" ? { outcome: "pass", reason: "selected", route, selector: label } : { outcome: "fail", reason: `not selected after the tap (${state})`, route, selector: label };
  }
  if (entry.kind === "sheet") {
    let seen = await visibleAny(page, entry.expect.visible);
    for (let wait = 0; !seen && wait < 10; wait++) {
      await sleep(1000);
      seen = await visibleAny(page, entry.expect.visible);
    }
    await page.keyboard.press("Escape").catch(() => null);
    return seen
      ? { outcome: "pass", reason: `shows "${seen}"`, route, selector: label }
      : { outcome: "fail", reason: `none of ${entry.expect.visible.join(" / ")} shown`, route, selector: label };
  }
  if (entry.kind === "back") {
    const opened2 = (await visibleAny(page, (entry.expect || {}).visible)) || page.url() !== before;
    if (!opened2) return { outcome: "fail", reason: "the tap opened nothing", route, selector: label };
    await page.goBack().catch(() => null);
    await settle(tab, 8000 * factor);
    const at = where(page);
    const listed2 = (await page.getByRole("button", { name: /^Open / }).filter({ visible: true }).count()) > 0;
    const prospect = await visibleAny(page, (entry.expect || {}).visible);
    return at.path === new URL(before).pathname && listed2 && !prospect
      ? { outcome: "pass", reason: "Back restores the list", route, selector: label }
      : { outcome: "fail", reason: `Back went to ${page.url().replace(cfg.PROXY, "")}${prospect ? " (the lead stays open)" : ""}`, route, selector: label };
  }
  // nav
  const now = where(page);
  const wrong = [];
  if (entry.expect.path && !now.path.startsWith(entry.expect.path)) wrong.push(`went to ${now.path}, expected ${entry.expect.path}`);
  let miss = queryMiss(now.query, entry.expect.query);
  // The side (Inbound or Cold) may be carried by the toggle, not the address: judge what is selected.
  const sideMiss = miss.find(([k]) => k === "side");
  if (sideMiss) {
    const want = /^cold/i.test(sideMiss[1]) ? "Cold Leads" : "Inbound Leads";
    const radios = await page.getByRole("radio", { name: /^(Inbound|Cold) Leads$/ }).filter({ visible: true }).count();
    const chosen = await page
      .getByRole("radio", { name: want })
      .filter({ visible: true })
      .first()
      .evaluate((el) => el.getAttribute("aria-checked") === "true" || el.checked === true)
      .catch(() => false);
    if (radios === 0 || chosen) miss = miss.filter(([k]) => k !== "side");
  }
  // The stage a card opens: judge the stage the list shows, not the address's key for it.
  const stepMiss = miss.find(([k]) => k === "step");
  if (stepMiss) {
    const wantLabel = { new: /^(New Lead|Unworked)/i, open_leads: /^Open Leads/i }[stepMiss[1]];
    if (wantLabel && (await page.getByText(wantLabel).filter({ visible: true }).count())) miss = miss.filter(([k]) => k !== "step");
  }
  if (miss.length) wrong.push(`context ${miss.map(([k, v]) => `${k}=${v}`).join(", ")} missing (has ${JSON.stringify(now.query)})`);
  if (entry.expect.visible && !(await visibleAny(page, entry.expect.visible))) wrong.push(`none of ${entry.expect.visible.join(" / ")} shown`);
  if (!wrong.length && entry.back) {
    await page.goBack().catch(() => null);
    await settle(tab, 8000 * factor);
    if (page.url() !== before) wrong.push(`Back went to ${page.url().replace(cfg.PROXY, "")}, not the page it left`);
  }
  if (tapError && wrong.length) wrong.unshift(`the tap did not land (${tapError})`);
  return wrong.length
    ? { outcome: "fail", reason: wrong.join("; "), route, selector: label }
    : { outcome: "pass", reason: `at ${now.path}`, route, selector: label };
}

module.exports = { manifest, byId, check, leadFor, atSize };
