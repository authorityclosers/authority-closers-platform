// The phone overlap check's logic (wb_overlap.mjs; owner, 17 Nov 2026, after Shivam's review of the lead page:
// "Bad UI that just overlaps … How did this get through? Testing didn't notice it"). The lead page's stage strip
// drew "Unworked" into "Follow-up" at 360 px with large text, and no check measured it. This one does, on the
// lead page and the Leads list, at 360, 363 and 412 px, normal and large (1.3x) text, light and dark:
// - overlap: two visible runs of text from different elements whose boxes cross (each run measured as the
//   browser lays it out, line by line, cut to what a hidden overflow lets show);
// - clipped: an element whose own text is wider than its box, cut off with no ellipsis.
// Text under a fixed or sticky bar is a different layer and is not compared with the page beneath it.
// A finding keeps its element's tag and first class, never its text (as sales_xray_dom_checks.mjs does).

export const WIDTHS = [360, 363, 412];
export const SCALES = [1, 1.3];
export const THEMES = ["light", "dark"];
export const HEIGHT = 780;

/** Every state the check runs a page in: 3 widths x 2 text sizes x 2 themes. */
export function overlapStates() {
  return WIDTHS.flatMap((width) =>
    SCALES.flatMap((scale) => THEMES.map((theme) => ({ width, scale, theme }))),
  );
}

export const tagOfState = ({ width, scale, theme }) =>
  `${width} ${scale === 1 ? "100%" : `${Math.round(scale * 100)}%`} ${theme}`;

/** How far two boxes cross: the width and height of what they share (0 when they don't). */
export function crossing(a, b) {
  return {
    width: Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)),
    height: Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)),
  };
}

/**
 * Whether two runs of text collide. Lines stacked one under the other in a tight line height share a pixel or
 * two of their glyph boxes and are fine; text drawn into other text shares most of its height.
 */
export function collides(a, b, { minWidth = 1.5, minShare = 0.5 } = {}) {
  // As crossing(), written out: it runs in the page on its own.
  const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
  const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
  const shorter = Math.min(a.bottom - a.top, b.bottom - b.top);
  return width > minWidth && shorter > 0 && height > shorter * minShare;
}

/** One line per page and state with findings, the worst first; nothing when every state is clean. */
export function summarise(rows) {
  return rows
    .filter((row) => row.error || row.overlaps.length || row.clipped.length)
    .sort(
      (a, b) =>
        Number(!!b.error) - Number(!!a.error) ||
        b.overlaps.length + b.clipped.length - (a.overlaps.length + a.clipped.length),
    )
    .map((row) =>
      row.error
        ? `${row.page} @ ${row.state}: could not measure (${row.error})`
        : `${row.page} @ ${row.state}: ${row.overlaps.length} overlapping, ${row.clipped.length} clipped` +
          (row.overlaps.length ? ` · ${row.overlaps.slice(0, 3).map((o) => `${o.a} x ${o.b}`).join(", ")}` : "") +
          (row.clipped.length ? ` · clipped ${row.clipped.slice(0, 3).map((c) => c.el).join(", ")}` : ""),
    );
}

/**
 * Runs in the page (see inPage): the text runs under `rootSelector`, then the pairs that collide (`hit`, which
 * is collides()) and the elements that cut their own text.
 */
export function scanOverlaps(rootSelector, hit) {
  const root = document.querySelector(rootSelector) ?? document.body;
  const name = (el) => {
    const raw = typeof el.className === "string" ? el.className : (el.getAttribute("class") ?? "");
    const first = raw.split(/\s+/)[0].replace(/^.*__/, "").slice(0, 24);
    return `${el.tagName.toLowerCase()}${first ? "." + first : ""}`;
  };
  const shown = (el) =>
    typeof el.checkVisibility === "function"
      ? el.checkVisibility({ opacityProperty: true, visibilityProperty: true })
      : getComputedStyle(el).visibility !== "hidden";
  // What a hidden overflow lets show of an element's content: its own and every ancestor's (an ellipsised
  // name's text runs on under the ellipsis; a scroller's content can be scrolled to, so it is kept).
  const clipCache = new Map();
  const clipOf = (el) => {
    if (clipCache.has(el)) return clipCache.get(el);
    const parent = el.parentElement;
    const box = parent
      ? { ...clipOf(parent) }
      : { left: -Infinity, top: -Infinity, right: Infinity, bottom: Infinity };
    {
      const style = getComputedStyle(el);
      const cut = (value) => value === "hidden" || value === "clip";
      if (cut(style.overflowX) || cut(style.overflowY)) {
        const rect = el.getBoundingClientRect();
        if (cut(style.overflowX)) {
          box.left = Math.max(box.left, rect.left);
          box.right = Math.min(box.right, rect.right);
        }
        if (cut(style.overflowY)) {
          box.top = Math.max(box.top, rect.top);
          box.bottom = Math.min(box.bottom, rect.bottom);
        }
      }
    }
    clipCache.set(el, box);
    return box;
  };
  const layerOf = (el) => {
    for (let at = el; at; at = at.parentElement) {
      const position = getComputedStyle(at).position;
      if (position === "fixed" || position === "sticky") return at;
    }
    return null;
  };
  const runs = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.textContent.trim()) continue;
    const el = node.parentElement;
    if (!el || !shown(el)) continue;
    const own = el.getBoundingClientRect();
    if (own.width <= 2 || own.height <= 2) continue; // read to screen readers only
    const clip = clipOf(el);
    range.selectNodeContents(node);
    for (const rect of range.getClientRects()) {
      const box = {
        left: Math.max(rect.left, clip.left),
        top: Math.max(rect.top, clip.top),
        right: Math.min(rect.right, clip.right),
        bottom: Math.min(rect.bottom, clip.bottom),
      };
      if (box.right - box.left < 2 || box.bottom - box.top < 2) continue;
      runs.push({ el, node, layer: layerOf(el), box });
    }
  }
  const overlaps = [];
  const seen = new Set();
  for (let i = 0; i < runs.length; i++)
    for (let j = i + 1; j < runs.length; j++) {
      const a = runs[i];
      const b = runs[j];
      if (a.node === b.node || a.layer !== b.layer) continue;
      if (!hit(a.box, b.box)) continue;
      const key = `${name(a.el)}|${name(b.el)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      overlaps.push({
        a: name(a.el),
        b: name(b.el),
        at: [Math.round(a.box.left), Math.round(a.box.top), Math.round(b.box.left), Math.round(b.box.top)],
      });
    }
  // Text cut off: an element whose own text runs past its box, hidden with no ellipsis or line clamp.
  const clipped = [];
  for (const el of new Set(runs.map((run) => run.el))) {
    const style = getComputedStyle(el);
    if (style.overflowX !== "hidden" && style.overflowX !== "clip") continue;
    if (style.textOverflow === "ellipsis") continue;
    if (style.webkitLineClamp && style.webkitLineClamp !== "none") continue;
    if (el.scrollWidth > el.clientWidth + 1) clipped.push({ el: name(el), by: el.scrollWidth - el.clientWidth });
  }
  return { runs: runs.length, overlaps: overlaps.slice(0, 20), clipped: clipped.slice(0, 20) };
}

/** The scan as one expression for page.evaluate, collides() passed in whole so the page uses the same rule. */
export const inPage = (rootSelector) =>
  `(${scanOverlaps.toString()})(${JSON.stringify(rootSelector)}, ${collides.toString()})`;
