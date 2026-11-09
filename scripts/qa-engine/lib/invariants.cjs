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
  // the pointer this page sees: a phone tab is meant to be coarse (touch); a fine one is a mouse, held to WCAG 2.5.8's 24 px
  out.pointer = matchMedia("(pointer: coarse)").matches ? "coarse" : "fine";
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
    .filter((el) => !el.disabled && el.getAttribute("aria-hidden") !== "true")
    // a visually hidden control (a custom file picker's real input, 1x1 px) is not what people tap: the visible button or label is
    .filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 2 || r.height > 2;
    });
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
    // clipped by its own scroll container (scrolled out of it): not covered by anything
    if (outsideOwnScroller(el, x, y)) continue;
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
      window.scrollTo({ left: sx, top: sy, behavior: "instant" });
      if (sc0) sc0.scrollTo({ top: st0, behavior: "instant" });
      if (!t2 || t2 === el || el.contains(t2) || t2.contains(el)) continue;
    }
    out.covered.push(rec(el, { by: sem(top) }));
  }
  // tap targets under 44 px (phone sizes)
  out.small = [];
  if (phone) {
    const tapNeed = out.pointer === "fine" ? 24 : 44;
    for (const el of interactive) {
      if (out.small.length >= 40) break;
      let r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > vh * 2) continue;
      if (r.width >= tapNeed && r.height >= tapNeed) continue;
      // a sheet or dialog opened on purpose covers the page behind it: the hit test there says nothing about the controls under it
      if (out.dialog > 0 && !el.closest("[role=dialog],[aria-modal=true],dialog")) continue;
      if (modals.length && !modals.some((m) => m.contains(el))) continue; // under an open :modal dialog
      const hit = (px, py) => {
        if (px < 0 || py < 0 || px >= vw || py >= vh) return false;
        const t = document.elementFromPoint(px, py);
        return !!t && (t === el || el.contains(t));
      };
      // a control off the screen, or under a fixed card or bar, cannot be probed in place (elementFromPoint answers null or the card there): bring it to the middle for the test, then put the scroll back
      let back = null;
      const onScreen = r.top >= 0 && r.bottom <= vh && r.left >= 0 && r.right <= vw;
      if (!onScreen || !hit(r.left + r.width / 2, r.top + r.height / 2)) {
        const sx = window.scrollX;
        const sy = window.scrollY;
        const sc = scrollerOf(el);
        const st = sc ? sc.scrollTop : 0;
        el.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
        back = () => {
          window.scrollTo({ left: sx, top: sy, behavior: "instant" });
          if (sc) sc.scrollTo({ top: st, behavior: "instant" });
        };
        r = el.getBoundingClientRect();
      }
      // judge the tap area, not the box: a ::after can make a 28 px box a 44 px target; a control reaches 44 px with (44 - size) / 2 on each side, so probe that far out, less 1 px for the edge
      const mx = r.left + r.width / 2;
      const my = r.top + r.height / 2;
      const reachY = Math.max(1, Math.floor((tapNeed - r.height) / 2) - 1);
      const reachX = Math.max(1, Math.floor((tapNeed - r.width) / 2) - 1);
      const tallEnough = r.height >= tapNeed || hit(mx, r.top - reachY) || hit(mx, r.bottom + reachY);
      const wideEnough = r.width >= tapNeed || hit(r.left - reachX, my) || hit(r.right + reachX, my);
      let small = !(tallEnough && wideEnough);
      if (small && getComputedStyle(el).display === "inline" && el.tagName === "A") small = false;
      if (small) {
        const wrap = el.closest("label,a,button,[role=button],[role=tab],[role=radio]");
        if (wrap && wrap !== el) {
          const w = wrap.getBoundingClientRect();
          if (w.width >= tapNeed && w.height >= tapNeed) small = false;
        }
      }
      const size = { w: Math.round(r.width), h: Math.round(r.height) };
      if (back) back();
      if (small) out.small.push(rec(el, { ...size, pointer: out.pointer }));
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
    const box = el.getBoundingClientRect();
    if (box.width < 24 || box.height < 24) continue; // a sliver (an 8 px empty avatars list while it loads) is nothing a person can look at
    const around = ((el.parentElement && el.parentElement.innerText) || "").replace(/\s+/g, " ");
    if (/\b(no|nothing|empty|yet|none|haven|add your|start by)\b/i.test(around)) continue;
    out.emptyLists.push(rec(el, {}));
  }
  // the four design rules (edge-mask, boxed, dead-row, label-heading), the same code as lib/design.cjs; filed only while state/design-filing.on exists
  out.design = phone ? (() => {
  const vw = innerWidth;
  const vh = innerHeight;
  const out = { phone: vw <= 480, edgeMask: [], boxed: [], deadRow: [], labelHeading: [], labelSmall: [] };
  if (!out.phone) return out;
  const INTERACTIVE = "a[href],button,[role=button],[role=tab],[role=link],[role=switch],[role=radio],[role=checkbox],[role=menuitem],input:not([type=hidden]),select,textarea,summary";
  const text = (el) => (el.getAttribute("aria-label") || el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && Number(cs.opacity) > 0.05;
  };
  const sel = (el) => {
    const role = el.getAttribute("role");
    const raw = typeof el.className === "string" ? el.className : "";
    const c = raw.split(" ")[0].replace(/^.*__/, "").slice(0, 24);
    return `${el.tagName.toLowerCase()}${role ? "[" + role + "]" : ""}${c ? "." + c : ""} "${text(el).slice(0, 24)}"`;
  };
  const inOverlay = (el) => !!el.closest("[role=dialog],[aria-modal=true],dialog");
  const overlayOpen = !!document.querySelector("[role=dialog],[aria-modal=true]");
  const controlsIn = (x) => [...(x.matches(INTERACTIVE) ? [x] : []), ...x.querySelectorAll(INTERACTIVE)].filter(visible);
  const bgOf = (e) => {
    for (let n = e; n; n = n.parentElement) {
      const m = getComputedStyle(n).backgroundColor.match(/rgba?\(([^)]+)\)/);
      if (m) {
        const p = m[1].split(",").map((x) => parseFloat(x));
        if (p.length < 4 || p[3] > 0.05) return p.slice(0, 3);
      }
    }
    return [255, 255, 255];
  };
  const dist = (a, b) => Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]);

  // 1. edge-mask
  const maskOf = (e) => {
    const c = getComputedStyle(e);
    const m = c.maskImage && c.maskImage !== "none" ? c.maskImage : c.webkitMaskImage && c.webkitMaskImage !== "none" ? c.webkitMaskImage : "";
    return m;
  };
  for (const S of document.querySelectorAll("body *")) {
    if (out.edgeMask.length >= 6) break;
    const cs = getComputedStyle(S);
    if (cs.overflowX !== "auto" && cs.overflowX !== "scroll") continue;
    if (S.scrollWidth <= S.clientWidth + 4) continue;
    const r = S.getBoundingClientRect();
    if (r.width < 120 || r.height < 24 || !visible(S) || inOverlay(S)) continue;
    let why = "";
    for (const e of [S, S.parentElement, S.parentElement && S.parentElement.parentElement]) {
      if (e && maskOf(e)) { why = `mask-image on ${e === S ? "the row" : "its wrapper"}`; break; }
    }
    if (!why) {
      for (const e of [S, S.parentElement]) {
        if (!e) continue;
        for (const ps of ["::before", "::after"]) {
          const p = getComputedStyle(e, ps);
          if (p.content !== "none" && /gradient/.test(p.backgroundImage) && ["absolute", "fixed", "sticky"].includes(p.position) && parseFloat(p.width) <= 120 && parseFloat(p.height) >= r.height * 0.5) { why = `fade gradient (${ps})`; break; }
        }
        if (why) break;
      }
    }
    if (!why && S.parentElement) {
      for (const e of S.parentElement.querySelectorAll(":scope > *, :scope > * > *")) {
        if (e === S || S.contains(e)) continue;
        const c2 = getComputedStyle(e);
        if (!/gradient/.test(c2.backgroundImage) || !["absolute", "fixed"].includes(c2.position)) continue;
        const r2 = e.getBoundingClientRect();
        if (r2.width > 0 && r2.width <= 120 && r2.height >= r.height * 0.5 && (Math.abs(r2.left - r.left) < 8 || Math.abs(r2.right - r.right) < 8) && Math.abs(r2.top - r.top) < r.height) { why = "fade gradient (overlay element)"; break; }
      }
    }
    if (why) out.edgeMask.push({ s: sel(S), d: `${why}; the row scrolls sideways (${S.scrollWidth}px in ${S.clientWidth}px)` });
  }

  // 2. boxed
  if (!overlayOpen) {
    const main = document.querySelector("main") || document.body;
    const docH = Math.max(main.scrollHeight, main.getBoundingClientRect().height);
    const need = Math.min(docH, vh) * 0.6;
    const kids = [main, ...main.querySelectorAll(":scope > *, :scope > * > *, :scope > * > * > *")];
    for (const e of kids) {
      const r = e.getBoundingClientRect();
      if (!visible(e) || r.width >= vw - 34 || r.width <= vw * 0.5 || r.height < need || r.left < 6 || vw - r.right < 6) continue;
      const cs = getComputedStyle(e);
      const own = cs.backgroundColor.match(/rgba?\(([^)]+)\)/);
      const p = own ? own[1].split(",").map((x) => parseFloat(x)) : null;
      const hasBg = p && (p.length < 4 || p[3] > 0.05);
      const hasBox = hasBg || (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== "none") || (cs.boxShadow && cs.boxShadow !== "none");
      if (!hasBox) continue;
      const y = Math.min(vh - 4, Math.max(4, r.top + Math.min(r.height, vh) / 2));
      const left = document.elementFromPoint(2, y);
      const right = document.elementFromPoint(vw - 3, y);
      if (!left || !right) continue;
      const sideL = bgOf(left);
      const sideR = bgOf(right);
      const mine = hasBg ? p.slice(0, 3) : bgOf(e);
      if (dist(mine, sideL) > 8 && dist(mine, sideR) > 8) {
        out.boxed.push({ s: sel(e), d: `content is ${Math.round(r.width)}px wide in a ${vw}px screen (${Math.round(r.left)}px at the left, ${Math.round(vw - r.right)}px at the right) and the sides show another colour (rgb ${sideL.join(",")} against rgb ${mine.join(",")})` });
        break;
      }
    }
  }

  // 3. dead-row
  let looked = 0;
  for (const P of document.querySelectorAll("main *")) {
    if (out.deadRow.length >= 6 || looked > 1500) break;
    looked++;
    if (P.matches("nav,ul,ol,[role=tablist],[role=menu],[role=listbox],[role=radiogroup]") || inOverlay(P)) continue;
    // a wrapping group (chips) puts a control on the next line only because it did not fit: that is the browser, not a design choice
    const pcs = getComputedStyle(P);
    if (pcs.flexWrap === "wrap" || pcs.flexWrap === "wrap-reverse") continue;
    const rows = [...P.children].filter(visible);
    if (rows.length < 2) continue;
    const pr = P.getBoundingClientRect();
    if (pr.width < 200) continue;
    for (let i = 1; i < rows.length; i++) {
      const A = rows[i - 1];
      const B = rows[i];
      const ra = A.getBoundingClientRect();
      const rb = B.getBoundingClientRect();
      if (rb.top < ra.bottom - 2 || rb.top - ra.bottom > 32) continue;
      const cB = controlsIn(B);
      if (cB.length !== 1) continue;
      const c = cB[0];
      const rc = c.getBoundingClientRect();
      if (rc.width >= pr.width * 0.5 || rc.width < 24) continue;
      const tb = text(B);
      const tc = text(c);
      if (tb !== tc && tb.replace(tc, "").trim().length > 0) continue;
      const cA = controlsIn(A);
      if (!cA.length) continue;
      let l = 1e9;
      let r2 = -1e9;
      const walker = document.createTreeWalker(A, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.textContent.trim()) continue;
        const rg = document.createRange();
        rg.selectNodeContents(n);
        for (const q of rg.getClientRects()) if (q.width > 0 && q.height > 0) { l = Math.min(l, q.left); r2 = Math.max(r2, q.right); }
      }
      for (const x of cA) { const q = x.getBoundingClientRect(); l = Math.min(l, q.left); r2 = Math.max(r2, q.right); }
      if (l > r2) continue;
      const free = Math.max(pr.right - r2, l - pr.left);
      if (free < pr.width * 0.4 || free < rc.width + 24) continue;
      out.deadRow.push({ s: sel(c), d: `${sel(c)} sits on its own row (${Math.round(rc.width)}px of ${Math.round(pr.width)}px) under ${sel(cA[0])}, whose row leaves ${Math.round(free)}px free (${Math.round((free / pr.width) * 100)}%)` });
    }
  }

  // 4. label-heading
  for (const h of document.querySelectorAll("h2,h3,h4,h5,h6,[role=heading]")) {
    if (out.labelHeading.length >= 6) break;
    if (h.matches("h1") || h.getAttribute("aria-level") === "1" || !visible(h) || h.closest("header,nav,aside,[role=dialog],[aria-modal=true],dialog,[role=tablist]")) continue;
    const t = text(h);
    if (!/^[\p{L}\p{M}'-]{3,}$/u.test(t)) continue;
    if (h.closest("a,button,label,summary,[role=button],[role=tab],[role=link]") || h.querySelector(INTERACTIVE) || h.hasAttribute("onclick") || getComputedStyle(h).cursor === "pointer") continue;
    const r = h.getBoundingClientRect();
    const below = [...document.querySelectorAll(INTERACTIVE)].filter((c) => {
      if (!visible(c) || h.contains(c)) return false;
      const q = c.getBoundingClientRect();
      return q.top >= r.bottom - 2 && q.top <= r.bottom + 40 && q.left < r.right + 8 && q.right > r.left - 8;
    });
    if (!below.length) continue;
    // a label set in heading size (16 px and up: Home's "Today") is the fault; the 12 to 14 px section titles above a list are how a list is laid out
    const fsz = parseFloat(getComputedStyle(h).fontSize);
    const item = { s: sel(h), d: `the heading "${t}" (${Math.round(fsz)}px) does nothing and sits ${Math.round(below[0].getBoundingClientRect().top - r.bottom)}px above ${sel(below[0])}${below.length > 1 ? ` and ${below.length - 1} more control${below.length > 2 ? "s" : ""}` : ""}` };
    if (fsz >= 16) out.labelHeading.push(item);
    else out.labelSmall.push(item);
  }
  return out;
})() : null;
  return out;
}

const EVT_ROUTE_IGNORE = /^$/;

// the four design rules are read on every phone scan but filed only while state/design-filing.on exists: first read in a capture, filed after a replay (orchestrator, 3 Nov 2026)
// state/design-filing.on lists the rules to file, one name per line; a rule not listed is read but not filed (boxed and dead-row stay reading-only until the owner grid has run).
const designFiling = () => { try { return new Set(require("fs").readFileSync(require("path").join(require("./config.cjs").STATE, "design-filing.on"), "utf8").split(/\s+/).filter(Boolean)); } catch (e) { return new Set(); } };

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
  for (const t of s.small) f("layout:tap-target-44", t.s, "POLISH", "Tap target under 44 px", `${t.s} is ${t.w}x${t.h}px (pointer ${t.pointer || "unknown"})`, t.p);
  if (s.design) {
    const filed = designFiling();
    if (filed.has("edge-mask")) for (const x of s.design.edgeMask) f("layout:edge-mask", x.s, "MINOR", "A row that scrolls sideways fades out or is masked at its edges", x.d);
    if (filed.has("boxed")) for (const x of s.design.boxed) f("layout:boxed", x.s, "MINOR", "On a phone the page content is boxed in instead of running full width", x.d);
    if (filed.has("dead-row")) for (const x of s.design.deadRow) f("layout:dead-row", x.s, "MINOR", "A control sits alone on its row while the row above has room for it", x.d);
    if (filed.has("label-heading")) for (const x of s.design.labelHeading) f("layout:label-heading", x.s, "MINOR", "A one-word heading that does nothing sits above controls", x.d);
  }
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
  "layout:edge-mask": "rows that fade or are masked at their edges",
  "layout:boxed": "page contents boxed in on a phone",
  "layout:dead-row": "controls alone on a row that has room above",
  "layout:label-heading": "one-word headings that do nothing above controls",
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
