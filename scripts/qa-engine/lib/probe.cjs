// Page checks, run on every page and state the robot opens: broken pages, API and script errors, layout
// (overflow, covered controls, small targets) and WCAG (axe-core, grouped by rule). Each returns findings:
//   { rule, selector, severity, summary, detail, route, shot?: selector to outline in the picture }
// Severity words are the matrix's: BLOCKER, MAJOR, MINOR, POLISH.
const cfg = require("./config.cjs");
const { isNoise, sleep } = require("./session.cjs");
const { normSelector } = require("./util.cjs");

const SCREEN_KEYS = ["tab", "view", "step", "stage", "side", "part", "when", "range"];

// The screen as people name it: the path plus the keys that pick a different screen, never an id.
function routeOf(urlOrPath) {
  const u = new URL(urlOrPath, "http://x");
  const keep = SCREEN_KEYS.filter((k) => u.searchParams.has(k)).map((k) => `${k}=${u.searchParams.get(k)}`);
  const path = u.pathname.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ":id").replace(/\/\d+(?=\/|$)/g, "/:id");
  return keep.length ? `${path}?${keep.join("&")}` : path;
}

const IMPACT = { critical: "MAJOR", serious: "MAJOR", moderate: "MINOR", minor: "POLISH" };

async function axeFindings(tab, route) {
  const tags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
  // Text caught mid-fade scores as low contrast: let the page's animations finish first, but never wait over 3 s
  // (a spinner never finishes).
  await tab.page
    .evaluate(async () => {
      const finishing = document.getAnimations().filter((a) => {
        const end = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming().endTime : 0;
        return Number.isFinite(end);
      });
      await Promise.race([Promise.allSettled(finishing.map((a) => a.finished)), new Promise((resolve) => setTimeout(resolve, 3000))]);
    })
    .catch(() => null);
  await tab.page.waitForTimeout(150).catch(() => null);
  let result;
  try {
    const { AxeBuilder } = require("@axe-core/playwright");
    result = await new AxeBuilder({ page: tab.page }).withTags(tags).analyze();
  } catch (error) {
    try {
      // Fallback: inject axe-core directly (what the wrapper does).
      const source = require("fs").readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
      await tab.page.evaluate(source);
      result = await tab.page.evaluate(async (t) => await window.axe.run(document, { runOnly: { type: "tag", values: t } }), tags);
    } catch (second) {
      return [{ rule: "robot:axe-failed", selector: "", severity: "POLISH", summary: "axe could not run", detail: String(second).split("\n")[0].slice(0, 160), route, internal: true }];
    }
  }
  return result.violations.map((v) => {
    const nodes = v.nodes || [];
    const first = nodes[0] ? [].concat(nodes[0].target || []).join(" ") : "";
    return {
      rule: `axe:${v.id}`,
      selector: normSelector(first),
      severity: IMPACT[v.impact] || "MINOR",
      summary: `${v.help} (WCAG ${((v.tags || []).filter((t) => /^wcag\d/.test(t))[0] || "").replace("wcag", "")})`,
      detail: `${nodes.length} element(s): ${nodes.slice(0, 4).map((n) => [].concat(n.target || []).join(" ").slice(0, 90)).join(" | ")}. ${v.helpUrl}`,
      route,
      shot: first && !first.includes("iframe") ? first : null,
      axeId: v.id,
      count: nodes.length,
    };
  });
}

// Everything that runs inside the page, in one trip: blank, error words, skeleton, overflow, covered, small.
function inPage(phone) {
  const visible = (el) => {
    if (!el.checkVisibility || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const name = (el) =>
    (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.getAttribute("title") || el.value || "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 40);
  const css = (el) => {
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute("role");
    const label = name(el);
    return `${tag}${role ? `[role=${role}]` : ""}${label ? ` "${label}"` : ""}`;
  };
  const out = {};
  const vw = document.documentElement.clientWidth;
  const vh = window.innerHeight;
  const main = document.querySelector("main") || document.body;
  out.textLength = (main.innerText || "").replace(/\s+/g, " ").trim().length;
  out.bodyText = (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 6000);
  out.title = document.title;
  out.heading = [...document.querySelectorAll("h1,h2")].filter(visible).map((h) => h.textContent.trim()).slice(0, 4);
  // skeletons that are still painted
  out.skeletons = [...document.querySelectorAll('[aria-busy="true"],[class*="skeleton" i],[class*="shimmer" i]')]
    .filter(visible)
    .filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width * r.height > 1500;
    }).length;
  // horizontal overflow with no scroller around it
  out.overflow = { scrollWidth: document.documentElement.scrollWidth, clientWidth: vw, offenders: [] };
  for (const el of document.querySelectorAll("body *")) {
    if (out.overflow.offenders.length >= 6) break;
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right <= vw + 1 && r.left >= -1) continue;
    let p = el.parentElement;
    let scrolled = false;
    while (p && p !== document.body) {
      const s = getComputedStyle(p);
      if (/(auto|scroll|hidden|clip)/.test(s.overflowX) && p.getBoundingClientRect().right <= vw + 1) {
        scrolled = true;
        break;
      }
      p = p.parentElement;
    }
    if (!scrolled) out.overflow.offenders.push(`${css(el)} left=${Math.round(r.left)} right=${Math.round(r.right)}`);
  }
  // controls with something on top of them (a banner, a bar, a sheet that should not be there)
  const controls = [...document.querySelectorAll("a[href],button,[role=button],[role=tab],input:not([type=hidden]),select,textarea,[role=switch]")]
    .filter(visible)
    .filter((el) => !el.disabled && el.getAttribute("aria-hidden") !== "true");
  let modals = [];
  try {
    modals = [...document.querySelectorAll(":modal")];
  } catch (e) {
    modals = [];
  }
  const pinnedOf = (n) => {
    for (; n && n !== document.body; n = n.parentElement) {
      const p = getComputedStyle(n).position;
      if (p === "fixed" || p === "sticky") return n;
    }
    return null;
  };
  const scrollerOf = (n) => {
    for (n = n.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (/(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight + 1) return n;
    }
    return null;
  };
  const outsideOwnScroller = (el, x, y) => {
    const sc = scrollerOf(el);
    if (!sc) return false;
    const b = sc.getBoundingClientRect();
    return x < b.left || x > b.right || y < b.top || y > b.bottom;
  };
  out.covered = [];
  for (const el of controls) {
    if (out.covered.length >= 6) break;
    const r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) continue;
    const x = Math.min(vw - 1, Math.max(0, r.left + r.width / 2));
    const y = Math.min(vh - 1, Math.max(0, r.top + Math.min(r.height / 2, vh - r.top - 1)));
    const top = document.elementFromPoint(x, y);
    if (!top || top === el || el.contains(top) || top.contains(el)) continue;
    // a label or a wrapper around the control is fine; a different, unrelated element on top is not
    const labelFor = top.closest && top.closest("label");
    if (labelFor && (labelFor.contains(el) || labelFor.htmlFor === el.id)) continue;
    const style = getComputedStyle(top);
    if (style.pointerEvents === "none") continue;
    const layer = top.closest("[role=dialog],[aria-modal=true],dialog,[role=menu],[role=listbox],[popover]");
    if (layer && !layer.contains(el)) continue;
    if (modals.length && !modals.some((m) => m.contains(el))) continue; // under an open :modal dialog
    if (el.closest("[inert]")) continue;
    if ((pinnedOf(top) && !pinnedOf(el)) || outsideOwnScroller(el, x, y) || (pinnedOf(el) && pinnedOf(el).contains(top))) {
      // under the fixed tab bar or the corner stack: covered only if scrolling it into view does not clear it
      const sx = window.scrollX;
      const sy = window.scrollY;
      const sc0 = scrollerOf(el);
      const st0 = sc0 ? sc0.scrollTop : 0;
      el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
      const r2 = el.getBoundingClientRect();
      const t2 = document.elementFromPoint(Math.min(vw - 1, Math.max(0, r2.left + r2.width / 2)), Math.min(vh - 1, Math.max(0, r2.top + Math.min(r2.height / 2, vh - r2.top - 1))));
      window.scrollTo(sx, sy);
      if (sc0) sc0.scrollTop = st0;
      if (!t2 || t2 === el || el.contains(t2) || t2.contains(el)) continue;
    }
    out.covered.push(`${css(el)} is under ${css(top)}`);
  }
  // small tap targets (phone sizes only): under 24 px either way is below WCAG 2.5.8
  out.small = [];
  if (phone) {
    for (const el of controls) {
      if (out.small.length >= 8) break;
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > vh * 2) continue;
      if (getComputedStyle(el).display === "inline" && el.tagName === "A") continue; // a link inside a sentence
      if (r.width < 24 || r.height < 24) {
        // judge the tap area, not the box: a ::after band can make a 23 px line a 47 px target (the lead's "Follow-up · Tomorrow" line, 2 Nov 2026), so probe 6 px beyond each short side
        const hit = (px, py) => {
          if (px < 0 || py < 0 || px >= vw || py >= vh) return false;
          const t = document.elementFromPoint(px, py);
          return !!t && (t === el || el.contains(t));
        };
        // below the fold: bring it into view for the test, then put the page back
        const sx0 = window.scrollX;
        const sy0 = window.scrollY;
        if (r.top < 0 || r.bottom > vh) el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
        const q = el.getBoundingClientRect();
        const mx = q.left + q.width / 2;
        const my = q.top + q.height / 2;
        const tallEnough = q.height >= 24 || (hit(mx, q.top - 6) && hit(mx, q.bottom + 6));
        const wideEnough = q.width >= 24 || (hit(q.left - 6, my) && hit(q.right + 6, my));
        window.scrollTo(sx0, sy0);
        if (tallEnough && wideEnough) continue;
        out.small.push(`${css(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
    }
  }
  return out;
}

const ERROR_WORDS = [
  [/something went wrong/i, "Something went wrong"],
  [/didn['’]t load|did not load|could(?:n['’]t| not) load/i, "says it did not load"],
  [/internal server error/i, "Internal Server Error"],
  [/application error|unhandled runtime error/i, "application error screen"],
  [/\b(?:NaN|undefined|\[object Object\]|null)\b/, "raw value shown (NaN / undefined / null)"],
  [/\b(?:403|404|500)\b[^.]{0,40}(?:forbidden|not found|error)|(?:forbidden|not found)\b[^.]{0,20}\b(?:403|404)\b/i, "error page text"],
];

// opts: { phone, mark (log mark), skipAxe, expectedErrors }
async function probe(tab, route, opts = {}) {
  const findings = [];
  const phone = !!tab.dev.phone;
  const f = (rule, selector, severity, summary, detail, shot) => findings.push({ rule, selector: normSelector(selector), severity, summary, detail, route, shot: shot || null });
  let page;
  if (/^about:blank/.test(tab.page.url())) return findings; // an aborted navigation: nothing to judge
  try {
    page = await tab.page.evaluate(inPage, phone);
    // a cold load on a shared box is slow, not blank: look again for up to 20 s before calling it blank
    for (let wait = 0; page.textLength < 25 && wait < 10; wait++) {
      await tab.page.waitForTimeout(2000);
      page = await tab.page.evaluate(inPage, phone).catch(() => page);
    }
  } catch (error) {
    f("page:unreadable", "", "MAJOR", "The page could not be read after it loaded", String(error).split("\n")[0].slice(0, 160));
    return findings;
  }
  if (page.textLength < 25) f("page:blank", "main", "MAJOR", "The page is blank after loading", `Only ${page.textLength} characters of text. Title: ${page.title}`);
  for (const [re, label] of ERROR_WORDS) {
    const hit = re.exec(page.bodyText);
    if (hit) f("page:error-text", label, "MAJOR", `The page shows an error or raw value: ${label}`, `Text near it: "${page.bodyText.slice(Math.max(0, hit.index - 40), hit.index + 80)}"`);
  }
  if (page.skeletons > 0) {
    await sleep(6000);
    const again = await tab.page.evaluate(inPage, phone).catch(() => null);
    if (again && again.skeletons > 0) f("page:stuck-skeleton", "skeleton", "MAJOR", "A loading skeleton never goes away", `${again.skeletons} placeholder block(s) still showing 6+ seconds after the page went quiet.`);
  }
  if (page.overflow.scrollWidth > page.overflow.clientWidth + 1 && page.overflow.offenders.length) {
    f("layout:overflow-x", page.overflow.offenders[0].split(" left=")[0], "MAJOR", "The page scrolls sideways", `Page is ${page.overflow.scrollWidth}px wide in a ${page.overflow.clientWidth}px screen: ${page.overflow.offenders.slice(0, 3).join(" | ")}`);
  }
  for (const c of page.covered) f("layout:covered", c.split(" is under ")[0], "MAJOR", "A control is covered by something else", c);
  if (page.small.length) f("layout:small-targets", page.small[0].replace(/ \d+x\d+$/, ""), "POLISH", "Tap targets under 24 px", page.small.slice(0, 5).join(" | "));
  if (opts.mark) {
    const seen = tab.since(opts.mark);
    const expected = opts.expectedErrors || [];
    for (const e of seen.pageerrors) if (!expected.some((re) => re.test(e))) f("script:page-error", e.replace(/\d+/g, "#").slice(0, 60), "MAJOR", "A script error was thrown", e);
    for (const e of [...new Set(seen.console)]) if (!expected.some((re) => re.test(e))) f("script:console-error", e.replace(/\d+/g, "#").slice(0, 60), "MINOR", "The page logged an error", e);
    for (const h of seen.http) {
      if (isNoise(h.path)) continue;
      const known = (opts.knownHttp || []).some((re) => re.test(`${h.status} ${h.method} ${h.path}`));
      if (known || h.status === 502 || h.status === 503 || h.status === 504) continue;
      f(`api:${h.status >= 500 ? "5xx" : "4xx"}`, `${h.method} ${h.path}`, h.status >= 500 ? "MAJOR" : "MINOR", `The app got HTTP ${h.status} from ${h.method} ${h.path}`, `${h.method} ${h.path} -> ${h.status}`);
    }
  }
  if (!opts.skipAxe) findings.push(...(await axeFindings(tab, route)));
  return findings;
}

module.exports = { probe, routeOf, normSelector, axeFindings };
