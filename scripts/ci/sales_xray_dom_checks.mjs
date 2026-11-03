// DOM checks the framework's CI gates name (docs/product/design-framework/FRAMEWORK.md v3.1, section 5), run by
// sales_xray_visual.mjs on the phone renders: edge masks, boxed layout, a dead row beside a control, a heading that
// does nothing (the QA robot's four design rules, one source in scripts/qa-engine/lib/design-rules.cjs), targets of 48 dp,
// 7:1 contrast on hero figures, off-scale text sizes and weights (new raw values), and a DOM-only pass at text scale 2.0.
// Report-only. A finding keeps its element's tag, role and first class, never its text.
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { DESIGN_SCAN } = require("../qa-engine/lib/design-rules.cjs");

export const TARGET_DP = 48;
export const HERO_CONTRAST = 7;
export const EMPTY_FIELDS = {
  design_edge_mask_count: null,
  design_boxed_count: null,
  design_dead_row_count: null,
  design_label_heading_count: null,
  target_under_48_count: null,
  hero_contrast_fail_count: null,
  raw_value_count: null,
  text_scale2_overflow_px: null,
  text_scale2_clipped_count: null,
  dom_findings: null,
};

/** Runs in the page: targets under 48 dp by their hit area, hero figures under 7:1, off-scale sizes and weights. */
export const PHONE_CHECKS = (limit) => {
  const [TARGET, HERO] = limit;
  const INTERACTIVE =
    "a[href],button,[role=button],[role=tab],[role=link],[role=switch],[role=radio],[role=checkbox],[role=menuitem],input:not([type=hidden]),select,textarea,summary";
  const out = { targets: [], hero: [], raw: [], rawChecked: false };
  const vw = innerWidth;
  const vh = innerHeight;
  const sel = (el) => {
    const role = el.getAttribute("role");
    const raw = typeof el.className === "string" ? el.className : "";
    const first = raw.split(" ")[0].replace(/^.*__/, "").slice(0, 24);
    return `${el.tagName.toLowerCase()}${role ? "[" + role + "]" : ""}${first ? "." + first : ""}`;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    return (
      cs.visibility !== "hidden" &&
      cs.display !== "none" &&
      Number(cs.opacity) > 0.05
    );
  };

  // targets: the tap area, not the box (a ::after can reach 48 dp from a smaller control)
  for (const el of document.querySelectorAll(INTERACTIVE)) {
    if (out.targets.length >= 40) break;
    let r = el.getBoundingClientRect();
    if (!visible(el) || (r.width >= TARGET && r.height >= TARGET)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === "inline" && el.tagName === "A") continue;
    if (
      el.matches("input[type=checkbox],input[type=radio]") &&
      el.closest("label")
    )
      continue;
    const sx = scrollX;
    const sy = scrollY;
    el.scrollIntoView({
      block: "center",
      inline: "nearest",
      behavior: "instant",
    });
    r = el.getBoundingClientRect();
    const hit = (x, y) => {
      if (x < 0 || y < 0 || x >= vw || y >= vh) return false;
      const t = document.elementFromPoint(x, y);
      return !!t && (t === el || el.contains(t));
    };
    const ry = Math.max(1, Math.floor((TARGET - r.height) / 2) - 1);
    const rx = Math.max(1, Math.floor((TARGET - r.width) / 2) - 1);
    const mx = r.left + r.width / 2;
    const my = r.top + r.height / 2;
    const tall =
      r.height >= TARGET || hit(mx, r.top - ry) || hit(mx, r.bottom + ry);
    const wide =
      r.width >= TARGET || hit(r.left - rx, my) || hit(r.right + rx, my);
    window.scrollTo(sx, sy);
    if (!(tall && wide))
      out.targets.push({
        s: sel(el),
        w: Math.round(r.width),
        h: Math.round(r.height),
      });
  }

  // hero figures: a figure set large, against the colour really behind it
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(",").map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const behind = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage !== "none") return null;
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) {
        layers.push(c);
        if (c.a >= 1) break;
      }
    }
    let base = { r: 255, g: 255, b: 255 };
    for (const c of layers.reverse())
      base = {
        r: c.r * c.a + base.r * (1 - c.a),
        g: c.g * c.a + base.g * (1 - c.a),
        b: c.b * c.a + base.b * (1 - c.a),
      };
    return base;
  };
  const FIGURE = /^[+\-−]?[₹$]?\d[\d.,]*\s?(%|k|K|m|M|min|s|h)?$/;
  for (const el of document.querySelectorAll("body *")) {
    if (out.hero.length >= 20) break;
    if (el.children.length || !visible(el)) continue;
    if (!FIGURE.test((el.textContent || "").trim())) continue;
    const cs = getComputedStyle(el);
    if (parseFloat(cs.fontSize) < 24) continue;
    const fg = parse(cs.color);
    const bg = behind(el);
    if (!fg || !bg) continue;
    const text = {
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a),
    };
    const l1 = lum(text);
    const l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    if (ratio < HERO)
      out.hero.push({ s: sel(el), ratio: Math.round(ratio * 10) / 10 });
  }

  // raw values: a text size or weight that is no step of the type scale (--sx-text-*, --ds-text-*, --ds-weight-*)
  const names = new Set();
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = sheet.cssRules;
    } catch {
      continue;
    }
    for (const rule of rules) {
      if (!rule.style) continue;
      for (const name of rule.style)
        if (/^--(sx|ds)-(text|weight)-/.test(name)) names.add(name);
    }
  }
  if (names.size) {
    out.rawChecked = true;
    const probe = document.createElement("span");
    document.body.append(probe);
    const sizes = new Set(["0px"]);
    const weights = new Set(["400", "500"]);
    for (const name of names) {
      probe.style.cssText = "position:absolute;visibility:hidden";
      if (/-text-/.test(name)) {
        probe.style.fontSize = `var(${name})`;
        sizes.add(getComputedStyle(probe).fontSize);
      } else {
        probe.style.fontWeight = `var(${name})`;
        weights.add(getComputedStyle(probe).fontWeight);
      }
    }
    probe.remove();
    const seen = new Map();
    for (const el of document.querySelectorAll("body *")) {
      if (!visible(el)) continue;
      const own = [...el.childNodes].some(
        (n) => n.nodeType === 3 && n.textContent.trim(),
      );
      if (!own) continue;
      const cs = getComputedStyle(el);
      if (!sizes.has(cs.fontSize)) {
        const key = `font-size ${cs.fontSize}`;
        seen.set(key, (seen.get(key) ?? 0) + 1);
      }
      if (!weights.has(cs.fontWeight)) {
        const key = `font-weight ${cs.fontWeight}`;
        seen.set(key, (seen.get(key) ?? 0) + 1);
      }
    }
    for (const [value, n] of [...seen].slice(0, 20))
      out.raw.push({ s: value, n });
  }
  return out;
};

/** Runs in the page, last: every text element at twice its size (Android's largest font setting), DOM only. */
export const TEXT_SCALE_2 = () => {
  const els = [...document.querySelectorAll("body *")];
  const sizes = els.map((el) => parseFloat(getComputedStyle(el).fontSize));
  els.forEach((el, i) =>
    el.style.setProperty("font-size", `${sizes[i] * 2}px`, "important"),
  );
  const width = document.documentElement.clientWidth;
  const overflow = Math.max(
    0,
    document.documentElement.scrollWidth - width,
    document.body.scrollWidth - width,
  );
  const items = [];
  let clipped = 0;
  const cuts = (v) => v === "hidden" || v === "clip";
  for (const el of els) {
    const cs = getComputedStyle(el);
    if (!cuts(cs.overflowX) && !cuts(cs.overflowY)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || cs.visibility === "hidden") continue;
    const own = [...el.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim(),
    );
    if (!own) continue;
    // a line cut with an ellipsis or a line clamp is the design, not a fault
    const ellipsis =
      cs.textOverflow === "ellipsis" ||
      cs.webkitLineClamp !== "none" ||
      cs.lineClamp > 0;
    const tall = cuts(cs.overflowY) && el.scrollHeight > el.clientHeight + 1;
    const wide =
      cuts(cs.overflowX) && !ellipsis && el.scrollWidth > el.clientWidth + 1;
    if ((tall && !ellipsis) || wide) {
      clipped++;
      if (items.length < 10) {
        const raw = typeof el.className === "string" ? el.className : "";
        const first = raw.split(" ")[0].replace(/^.*__/, "").slice(0, 24);
        items.push(`${el.tagName.toLowerCase()}${first ? "." + first : ""}`);
      }
    }
  }
  return { overflow, clipped, items };
};

const bare = (selector) => selector.replace(/ "[^"]*"$/, "");

/** Runs the phone checks and writes their counts and findings onto the row; a failure leaves the fields null. */
export async function runPhoneChecks(page, row) {
  try {
    const design = await page.evaluate(DESIGN_SCAN);
    const checks = await page.evaluate(PHONE_CHECKS, [
      TARGET_DP,
      HERO_CONTRAST,
    ]);
    row.design_edge_mask_count = design.edgeMask.length;
    row.design_boxed_count = design.boxed.length;
    row.design_dead_row_count = design.deadRow.length;
    row.design_label_heading_count = design.labelHeading.length;
    row.target_under_48_count = checks.targets.length;
    row.hero_contrast_fail_count = checks.hero.length;
    row.raw_value_count = checks.rawChecked ? checks.raw.length : null;
    row.dom_findings = [
      ...design.edgeMask.map((f) => ({
        rule: "edge-mask",
        selector: bare(f.s),
      })),
      ...design.boxed.map((f) => ({ rule: "boxed", selector: bare(f.s) })),
      ...design.deadRow.map((f) => ({ rule: "dead-row", selector: bare(f.s) })),
      ...design.labelHeading.map((f) => ({
        rule: "label-heading",
        selector: bare(f.s),
      })),
      ...checks.targets.map((f) => ({
        rule: "target-48",
        selector: f.s,
        size: `${f.w}x${f.h}`,
      })),
      ...checks.hero.map((f) => ({
        rule: "hero-contrast",
        selector: f.s,
        ratio: f.ratio,
      })),
      ...checks.raw.map((f) => ({
        rule: "raw-value",
        selector: f.s,
        elements: f.n,
      })),
    ].slice(0, 40);
  } catch {
    /* Failed measurements stay null: never a guess. */
  }
}

/** The DOM-only pass at text scale 2.0. It changes the page, so it runs after the screenshot. */
export async function runTextScale(page, row) {
  try {
    const result = await page.evaluate(TEXT_SCALE_2);
    row.text_scale2_overflow_px = result.overflow;
    row.text_scale2_clipped_count = result.clipped;
    for (const item of result.items)
      row.dom_findings = [
        ...(row.dom_findings ?? []),
        { rule: "text-scale-2-clipped", selector: item },
      ].slice(0, 50);
  } catch {
    /* stays null */
  }
}
