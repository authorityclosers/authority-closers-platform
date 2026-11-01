// Route crawler: from a start page, every link and button that is shown. Links are followed (the right page, no
// 404 or blank or error, Back returns to where it started); buttons are pressed once on a read-only page (the
// crawl blocks every write to the API) and must change something: the address, a sheet or dialog, or the page.
// Dangerous words are listed, never pressed. The output map (role, name, where it went) also feeds the 99
// click-destination checks, which is how new controls get their selectors.
const cfg = require("./config.cjs");
const { go, settle, sleep } = require("./session.cjs");
const { probe, routeOf } = require("./probe.cjs");
const { installReadOnly } = require("./monkey.cjs");

const NEVER = /log ?out|sign ?out|delete|remove|erase|reset|close account|import|send|submit|call|dial|whatsapp|upload|pay|buy|upgrade|checkout|revoke|disconnect|unlink|archive|invite|transfer|complete|mark|save|confirm|accept|start (?:cold|calling)|record/i;

async function controls(page) {
  return page.evaluate(() => {
    const visible = (el) => {
      if (!el.checkVisibility || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const label = (el) =>
      (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.getAttribute("title") || "").replace(/\s+/g, " ").trim().slice(0, 80);
    const out = [];
    const seen = new Set();
    for (const el of document.querySelectorAll("a[href],button,[role=button],[role=tab],[role=radio],[role=menuitem],[role=switch],[role=checkbox]")) {
      if (!visible(el) || el.disabled || el.getAttribute("aria-hidden") === "true") continue;
      const role = el.getAttribute("role") || (el.tagName === "A" ? "link" : "button");
      const name = label(el);
      const href = el.tagName === "A" ? el.getAttribute("href") : null;
      const key = `${role}|${name}|${href || ""}`;
      if (seen.has(key) || (!name && !href)) continue;
      seen.add(key);
      out.push({ role, name, href });
    }
    return out;
  });
}

function pickAgain(page, c) {
  const exact = c.name && c.name.length < 70;
  if (c.role === "link" && c.href) return page.locator(`a[href="${c.href.replace(/"/g, '\\"')}"]`).filter({ visible: true }).filter({ hasText: c.name.slice(0, 30) }).first();
  return page.getByRole(c.role, { name: c.name, exact }).filter({ visible: true }).first();
}

/**
 * crawl(tab, start, { limit }) -> { start, found, map: [...], findings: [...] }
 * Findings are the broken ones: dead link, dead control, Back not restoring.
 */
async function crawl(tab, start, { limit = 70 } = {}) {
  const page = tab.page;
  await installReadOnly(tab);
  const origin = new URL(cfg.PROXY).origin;
  const startRoute = routeOf(start);
  const first = await go(tab, start, { wait: 25000 });
  if (!first.ok) return { start, found: 0, map: [], findings: [{ rule: "crawl:start-failed", selector: "", severity: "MAJOR", summary: "The start page did not open", detail: first.error, route: startRoute }] };
  const startUrl = page.url();
  const all = await controls(page);
  const todo = all.slice(0, limit);
  const map = [];
  const findings = [];
  const add = (rule, selector, severity, summary, detail, route) => findings.push({ rule, selector, severity, summary, detail, route: route || startRoute });
  for (const c of todo) {
    const rec = { role: c.role, name: c.name, href: c.href || null, from: startRoute };
    map.push(rec);
    if (NEVER.test(c.name) || (c.href && /^(tel:|mailto:|sms:|whatsapp:)/i.test(c.href))) {
      rec.skipped = c.href && /^(tel:|mailto:|sms:|whatsapp:)/i.test(c.href) ? "contact link" : "side-effect word";
      continue;
    }
    const mark = tab.mark();
    try {
      if (c.href) {
        const absolute = new URL(c.href, page.url());
        if (absolute.origin !== origin) {
          rec.skipped = "outside link";
          continue;
        }
        const opened = await go(tab, absolute.pathname + absolute.search, { wait: 20000 });
        rec.path = new URL(page.url()).pathname;
        rec.query = Object.fromEntries(new URL(page.url()).searchParams);
        if (!opened.ok) {
          rec.broken = opened.error;
          add("crawl:dead-link", `link "${c.name}"`, "MAJOR", `The link "${c.name}" does not open`, `${c.href}: ${opened.error}`);
        } else {
          const bad = (await probe(tab, routeOf(page.url()), { mark, skipAxe: true })).filter((f) => ["page:blank", "page:error-text", "page:stuck-skeleton", "api:5xx"].includes(f.rule));
          if (bad.length) {
            rec.broken = bad.map((b) => b.rule).join(",");
            add("crawl:dead-link", `link "${c.name}"`, "MAJOR", `The link "${c.name}" opens a broken page`, `${c.href} -> ${bad.map((b) => b.summary).join("; ")}`, routeOf(page.url()));
          }
        }
        await page.goBack().catch(() => null);
        await settle(tab, 8000);
        if (page.url() !== startUrl && new URL(page.url()).pathname + new URL(page.url()).search !== new URL(startUrl).pathname + new URL(startUrl).search) {
          rec.backBroken = page.url().replace(origin, "");
          add("crawl:back", `link "${c.name}"`, "MINOR", `Back after "${c.name}" does not return to the page it left`, `Left ${startRoute}, Back went to ${rec.backBroken}`);
        }
      } else {
        await page.evaluate(() => {
          window.__qaMut = 0;
          if (window.__qaObs) window.__qaObs.disconnect();
          window.__qaObs = new MutationObserver((list) => {
            window.__qaMut += list.length;
          });
          window.__qaObs.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });
        });
        const dialogsBefore = await page.getByRole("dialog").filter({ visible: true }).count();
        const target = pickAgain(page, c);
        if (!(await target.count())) {
          rec.skipped = "moved before it was pressed";
          continue;
        }
        await target.click({ timeout: 8000 }).catch((e) => {
          rec.clickError = String(e).split("\n")[0].slice(0, 100);
        });
        await settle(tab, 6000);
        await sleep(600);
        const changed = await page.evaluate(() => window.__qaMut || 0).catch(() => 0);
        const dialogs = await page.getByRole("dialog").filter({ visible: true }).count();
        const moved = page.url() !== startUrl;
        rec.path = new URL(page.url()).pathname;
        rec.query = Object.fromEntries(new URL(page.url()).searchParams);
        rec.opened = dialogs > dialogsBefore ? "dialog" : null;
        rec.changed = changed;
        rec.moved = moved;
        if (rec.clickError) {
          add("crawl:cannot-press", `${c.role} "${c.name}"`, "MAJOR", `"${c.name}" cannot be pressed`, rec.clickError);
        } else if (!moved && dialogs <= dialogsBefore && changed < 2) {
          add("crawl:dead-control", `${c.role} "${c.name}"`, "MINOR", `Pressing "${c.name}" does nothing`, `No new page, sheet or change on ${startRoute} after the tap.`);
        }
        await page.keyboard.press("Escape").catch(() => null);
        if (moved || dialogs > dialogsBefore) {
          await go(tab, start, { wait: 15000 });
        }
      }
    } catch (error) {
      rec.error = String(error).split("\n")[0].slice(0, 120);
    }
  }
  return { start, found: all.length, pressed: map.filter((m) => !m.skipped).length, map, findings };
}

module.exports = { crawl, controls, pickAgain };
