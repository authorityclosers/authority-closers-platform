// The four design rules (orchestrator, 3 Nov 2026), run in the page:
//   edge-mask     a mask-image or fade gradient on a row that scrolls sideways (phone)
//   boxed         page content narrower than the viewport minus 34 px, boxed, with another colour at the sides (phone)
//   dead-row      a row of one control under half the width, with the row above leaving 40% or more free and room for it (phone)
//   label-heading a one-word heading of 16 px or more that does nothing, directly above controls (phone, not an h1)
// One source for the capture stage (lib/design.cjs), the CI visual script (scripts/ci/sales_xray_visual.mjs) and, as a text
// copy inside the page scan, the robot's walks (lib/invariants.cjs; a unit test keeps that copy equal). Nothing is required here:
// the function is serialised into the page.
const DESIGN_SCAN = () => {
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
};

module.exports = { DESIGN_SCAN };
