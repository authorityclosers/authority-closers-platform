// Invariants checked after every step of a persona walk. The in-page part (scan) runs once per step and returns
// raw facts; findingsFrom() turns them into findings. Each finding keeps a semantic selector (tag, role, words:
// stable across rebuilds, used in the fingerprint) and a CSS path (used only to outline the element in the picture).
//   console errors, script errors and unhandled rejections, HTTP 4xx/5xx, sideways scroll, layout shift,
//   overlapping controls, clipped text, tap targets under 44 px, axe, slow interactions, missing loading or empty
//   states, native <select>.
const { normSelector } = require("./util.cjs");

// Added to every context before any page script runs: layout shift and slow interactions, summed per step.
const INIT = `(() => {
  const q = (window.__qa = { cls: 0, events: [] });
  window.__qaPath = (el) => {
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && parts.length < 6; n = n.parentElement) {
      let p = n.tagName.toLowerCase();
      if (n.id && !/\\d/.test(n.id)) { parts.unshift(p + "#" + CSS.escape(n.id)); break; }
      const sibs = n.parentElement ? [...n.parentElement.children].filter((c) => c.tagName === n.tagName) : [];
      if (sibs.length > 1) p += ":nth-of-type(" + (sibs.indexOf(n) + 1) + ")";
      parts.unshift(p);
    }
    return parts.join(">");
  };
  window.__qaSem = (el) => {
    const label = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.getAttribute("title") || el.value || "").replace(/\\s+/g, " ").trim().slice(0, 40);
    const role = el.getAttribute("role");
    return el.tagName.toLowerCase() + (role ? "[role=" + role + "]" : "") + (label ? ' "' + label + '"' : "");
  };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) q.cls += e.value; }).observe({ type: "layout-shift", buffered: true }); } catch (e) {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.interactionId) q.events.push({ n: e.name, d: Math.round(e.duration), t: e.target ? [window.__qaSem(e.target), window.__qaPath(e.target)] : null }); }).observe({ type: "event", durationThreshold: 200, buffered: false }); } catch (e) {}
})();`;

function scan(phone) {
  const vw = document.documentElement.clientWidth;
  const vh = window.innerHeight;
  const sem = window.__qaSem;
  const path = window.__qaPath;
  const visible = (el) => {
    if (!el.checkVisibility || !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const rec = (el, extra) => ({ s: sem(el), p: path(el), ...extra });
  const out = { url: location.pathname + location.search, vw, vh };
  const main = document.querySelector("main") || document.body;
  out.textLength = (main.innerText || "").replace(/\s+/g, " ").trim().length;
  out.bodyText = (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 6000);
  out.skeletons = [...document.querySelectorAll('[aria-busy="true"],[class*="skeleton" i],[class*="shimmer" i]')].filter(visible).filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width * r.height > 1500;
  }).length;
  out.loading = document.querySelectorAll('[role=progressbar],[role=status],[aria-busy="true"],[class*="spinner" i],[class*="loading" i]').length;
  out.dialog = [...document.querySelectorAll("[role=dialog]")].filter(visible).length;
  // sideways scroll
  out.overflow = { sw: document.documentElement.scrollWidth, cw: vw, items: [] };
  for (const el of document.querySelectorAll("body *")) {
    if (out.overflow.items.length >= 6) break;
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
    if (!scrolled) out.overflow.items.push(rec(el, { l: Math.round(r.left), r: Math.round(r.right) }));
  }
  const interactive = [...document.querySelectorAll("a[href],button,[role=button],[role=tab],[role=radio],[role=switch],[role=checkbox],[role=menuitem],input:not([type=hidden]),select,textarea")]
    .filter(visible)
    .filter((el) => !el.disabled && el.getAttribute("aria-hidden") !== "true");
  const inView = interactive.filter((el) => {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  });
  // covered by something else
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
  for (const el of inView) {
    if (out.covered.length >= 12) break;
    const r = el.getBoundingClientRect();
    const x = Math.min(vw - 1, Math.max(0, r.left + r.width / 2));
    const y = Math.min(vh - 1, Math.max(0, r.top + Math.min(r.height / 2, vh - r.top - 1)));
    const top = document.elementFromPoint(x, y);
    if (!top || top === el || el.contains(top) || top.contains(el)) continue;
    const lab = top.closest && top.closest("label");
    if (lab && (lab.contains(el) || lab.htmlFor === el.id)) continue;
    if (getComputedStyle(top).pointerEvents === "none") continue;
    // a sheet, dialog or menu opened on purpose covers the page behind it: not a fault
    const layer = top.closest("[role=dialog],[aria-modal=true],dialog,[role=menu],[role=listbox],[popover]");
    if (layer && !layer.contains(el)) continue;
    if (out.dialog > 0 && !el.closest("[role=dialog],[aria-modal=true],dialog")) continue;
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
    out.covered.push(rec(el, { by: sem(top) }));
  }
  // tap targets under 44 px (phone sizes)
  out.small = [];
  if (phone) {
    for (const el of interactive) {
      if (out.small.length >= 40) break;
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > vh * 2) continue;
      if (r.width >= 44 && r.height >= 44) continue;
      // judge the tap area: a ::after can make a 28 px box a 44 px target, so probe 8 px beyond the short sides
      const hit = (px, py) => {
        if (px < 0 || py < 0 || px >= vw || py >= vh) return false;
        const t = document.elementFromPoint(px, py);
        return !!t && (t === el || el.contains(t));
      };
      const mx = r.left + r.width / 2;
      const my = r.top + r.height / 2;
      const tallEnough = r.height >= 44 || hit(mx, r.top - 8) || hit(mx, r.bottom + 8);
      const wideEnough = r.width >= 44 || hit(r.left - 8, my) || hit(r.right + 8, my);
      if (tallEnough && wideEnough) continue;
      if (getComputedStyle(el).display === "inline" && el.tagName === "A") continue;
      const wrap = el.closest("label,a,button,[role=button],[role=tab],[role=radio]");
      if (wrap && wrap !== el) {
        const w = wrap.getBoundingClientRect();
        if (w.width >= 44 && w.height >= 44) continue;
      }
      out.small.push(rec(el, { w: Math.round(r.width), h: Math.round(r.height) }));
    }
  }
  // overlapping controls: two shown controls whose boxes cross, neither inside the other
  out.overlaps = [];
  const boxes = inView.slice(0, 90).map((el) => ({ el, r: el.getBoundingClientRect() }));
  for (let i = 0; i < boxes.length && out.overlaps.length < 12; i++) {
    for (let j = i + 1; j < boxes.length && out.overlaps.length < 12; j++) {
      const a = boxes[i];
      const b = boxes[j];
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      const h = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (w <= 2 || h <= 2) continue;
      const small = Math.min(a.r.width * a.r.height, b.r.width * b.r.height);
      const big = Math.max(a.r.width * a.r.height, b.r.width * b.r.height);
      if (small < 120 || (w * h) / small < 0.5) continue;
      // a card-sized link around other controls, or a bar fixed to the screen over scrolling content, is by design
      if (big / small > 8) continue;
      const pinned = (el) => {
        for (let n = el; n && n !== document.body; n = n.parentElement) {
          const pos = getComputedStyle(n).position;
          if (pos === "fixed" || pos === "sticky") return true;
        }
        return false;
      };
      if (pinned(a.el) || pinned(b.el)) continue;
      const dismissal = /^(close|dismiss|clear|x|×)\b/i;
      if (dismissal.test((a.el.getAttribute("aria-label") || a.el.textContent || "").trim()) || dismissal.test((b.el.getAttribute("aria-label") || b.el.textContent || "").trim())) continue;
      out.overlaps.push({ s: sem(a.el), p: path(a.el), o: sem(b.el) });
    }
  }
  // clipped text: the text is wider than its box, the box hides the rest, and it is not an ellipsis
  out.clipped = [];
  for (const el of main.querySelectorAll("*")) {
    if (out.clipped.length >= 20) break;
    if (el.children.length > 2 || !(el.textContent || "").trim()) continue;
    const s = getComputedStyle(el);
    if (!/(hidden|clip)/.test(s.overflowX) || s.textOverflow === "ellipsis") continue;
    if (el.scrollWidth <= el.clientWidth + 1 || el.clientWidth < 8) continue;
    if (!visible(el)) continue;
    out.clipped.push(rec(el, { sw: el.scrollWidth, cw: el.clientWidth }));
  }
  // native select (the owner's rule: the shared picker everywhere)
  out.selects = [...document.querySelectorAll("select")].filter(visible).slice(0, 12).map((el) => rec(el, {}));
  // a list or table with no rows and no words about it
  out.emptyLists = [];
  for (const el of main.querySelectorAll("[role=list],ul,ol,table,[role=grid]")) {
    if (out.emptyLists.length >= 6) break;
    if (!visible(el)) continue;
    if (el.querySelectorAll("li,tr,[role=listitem],[role=row],a,button").length) continue;
    const around = ((el.parentElement && el.parentElement.innerText) || "").replace(/\s+/g, " ");
    if (/\b(no|nothing|empty|yet|none|haven|add your|start by)\b/i.test(around)) continue;
    out.emptyLists.push(rec(el, {}));
  }
  return out;
}

const EVT_ROUTE_IGNORE = /^$/;

// opts: { route, phone, shift, events, firstSight: bool }
function findingsFrom(s, { route, phone, shift = 0, events = [] }) {
  const out = [];
  const f = (rule, sel, severity, summary, detail, shot) => out.push({ rule, selector: normSelector(sel), severity, summary, detail, route, shot: shot || null });
  if (s.textLength < 25) f("page:blank", "main", "MAJOR", "The page is blank", `Only ${s.textLength} characters of text on screen.`);
  if (s.overflow.sw > s.overflow.cw + 1 && s.overflow.items.length) {
    const it = s.overflow.items[0];
    f("layout:overflow-x", it.s, "MAJOR", "The page scrolls sideways", `Page ${s.overflow.sw}px wide in a ${s.overflow.cw}px screen; ${s.overflow.items.slice(0, 3).map((x) => `${x.s} (${x.l}..${x.r})`).join(" | ")}`, it.p);
  }
  for (const c of s.covered) f("layout:covered", c.s, "MAJOR", "A control is covered by something else", `${c.s} is under ${c.by}`, c.p);
  for (const o of s.overlaps) f("layout:overlap", `${o.s} + ${o.o}`, "MINOR", "Two controls overlap", `${o.s} overlaps ${o.o}`, o.p);
  for (const c of s.clipped) f("layout:text-clipped", c.s, "MINOR", "Text is cut off", `${c.s}: the text is ${c.sw}px wide in a ${c.cw}px box that hides the rest`, c.p);
  for (const t of s.small) f("layout:tap-target-44", t.s, "POLISH", "Tap target under 44 px", `${t.s} is ${t.w}x${t.h}px`, t.p);
  for (const n of s.selects) f("ui:native-select", n.s, "MINOR", "A native select is still used", `${n.s}: the owner's rule is the shared picker everywhere`, n.p);
  for (const e of s.emptyLists) f("state:no-empty", e.s, "MINOR", "An empty list says nothing", `${e.s} has no rows and no words about it`, e.p);
  if (shift > 0.1) f("layout:shift", "page", "MINOR", "The layout jumps while it loads", `Layout shift of ${shift.toFixed(2)} during the step`);
  // Interaction timing means nothing while the shared dev box is saturated (the same tap took 1 to 3 s on svg
  // icons here): off unless QA_PERF=1, to be measured on staging instead.
  for (const e of process.env.QA_PERF === "1" ? events.filter((x) => x.d >= 300 && x.t) : []) {
    f("perf:slow-interaction", e.t[0], "POLISH", `An interaction took ${e.d} ms to respond`, `${e.n} on ${e.t[0]} took ${e.d} ms (the dev box is shared, so re-check on staging)`, e.t[1]);
  }
  return out;
}

// One report per page, rule and viewport: every element of that rule on the page, with its selector and size, and one
// picture with all of them outlined (orchestrator, 31 Oct 2026).
const ROLLED = {
  "layout:tap-target-44": "controls under 44 px",
  "layout:covered": "controls covered by something else",
  "layout:overlap": "pairs of controls that overlap",
  "layout:text-clipped": "texts that are cut off",
  "ui:native-select": "native selects (the shared picker is the rule)",
  "state:no-empty": "empty lists with no words about them",
};
const RANK = { BLOCKER: 4, MAJOR: 3, MINOR: 2, POLISH: 1 };

function rollup(findings, viewportKey) {
  const out = [];
  const groups = new Map();
  for (const f of findings) {
    if (!ROLLED[f.rule]) {
      out.push(f);
      continue;
    }
    const k = `${f.rule}|${f.route}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(f);
  }
  for (const items of groups.values()) {
    const first = items[0];
    const worst = items.reduce((a, b) => (RANK[b.severity] > RANK[a] ? b.severity : a), first.severity);
    out.push({
      rule: first.rule,
      selector: `@${viewportKey}`,
      severity: worst,
      summary: `${first.route} at ${viewportKey} px: ${items.length} ${ROLLED[first.rule]}`,
      detail: items.map((i) => i.detail).join(" | ").slice(0, 2600),
      route: first.route,
      shot: null,
      shotAll: items.map((i) => i.shot).filter(Boolean).slice(0, 40),
      count: items.length,
      rolled: true,
    });
  }
  return out;
}

module.exports = { INIT, scan, findingsFrom, rollup, ROLLED };
