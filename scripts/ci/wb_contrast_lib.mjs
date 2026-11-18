// The dark contrast check's logic (wb_contrast.mjs; owner, 17 Nov 2026: "Dark mode: some items can't be seen at
// all, colour combinations"). In the app's dark theme, every visible run of text and every drawn icon is measured
// against what is really painted under it (the stack of backgrounds at that point, each layer's alpha composited),
// and it fails below WCAG AA: 4.5:1 for body text, 3:1 for large text (24 px, or 18.66 px bold) and for icons.
// Disabled controls are exempt (WCAG 1.4.3), and so is text over a picture or gradient (it can't be measured
// from colours alone; it is counted, not judged). A finding keeps its element's tag and first class, never its
// text beyond a short label for the report (fixtures are fictional).

export const WIDTHS = [363, 1280];
export const HEIGHT = 800;

/** "rgb(1, 2, 3)" / "rgba(1, 2, 3, 0.5)" / "rgb(1 2 3 / 50%)" / "transparent" as [r, g, b, a]; null if unknown. */
export function parseColour(text) {
  if (!text) return null;
  const value = String(text).trim().toLowerCase();
  if (value === "transparent") return [0, 0, 0, 0];
  const match = value.match(/^rgba?\(([^)]+)\)$/);
  if (!match) return null;
  const parts = match[1].split(/[\s,/]+/).filter(Boolean);
  if (parts.length < 3) return null;
  const channel = (part) => (part.endsWith("%") ? (parseFloat(part) * 255) / 100 : parseFloat(part));
  const alpha =
    parts[3] === undefined ? 1 : parts[3].endsWith("%") ? parseFloat(parts[3]) / 100 : parseFloat(parts[3]);
  const out = [channel(parts[0]), channel(parts[1]), channel(parts[2]), alpha];
  return out.every((n) => Number.isFinite(n)) ? out : null;
}

/** A colour with alpha painted over an opaque one. */
export function over(top, under) {
  const a = top[3];
  return [0, 1, 2].map((i) => top[i] * a + under[i] * (1 - a)).concat(1);
}

/** WCAG relative luminance of an opaque colour. */
export function luminance(colour) {
  const [r, g, b] = colour.slice(0, 3).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio of two opaque colours, 1 to 21. */
export function ratio(a, b) {
  // As luminance(), written out: it runs in the page on its own.
  const lum = (colour) => {
    const [r, g, bl] = colour.slice(0, 3).map((v) => {
      const c = v / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The ratio a run of text or an icon needs: 3 for large text and icons, 4.5 for the rest. */
export function needed({ icon = false, px = 16, weight = 400 } = {}) {
  if (icon) return 3;
  return px >= 24 || (px >= 18.66 && weight >= 700) ? 3 : 4.5;
}

/**
 * Runs in the page on its own: every visible text run and icon under rootSelector, measured as painted.
 * h holds the helpers above (passed in whole, so page and tests use the same rules).
 */
export function scanContrast(rootSelector, h) {
  const root = document.querySelector(rootSelector) ?? document.body;
  // Computed colours can be color(srgb ...), oklab() or oklch() (color-mix tokens): the canvas reads any of them.
  const paint = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  const cache = new Map();
  const colourOf = (text) => {
    const plain = h.parseColour(text);
    if (plain || !text || text === "none") return plain;
    if (cache.has(text)) return cache.get(text);
    paint.clearRect(0, 0, 1, 1);
    paint.fillStyle = "rgba(0, 0, 0, 0)";
    paint.fillStyle = text;
    paint.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = paint.getImageData(0, 0, 1, 1).data;
    const out = a ? [(r * 255) / a, (g * 255) / a, (b * 255) / a, a / 255].map((v, i) => (i < 3 ? Math.min(255, v) : v)) : [0, 0, 0, 0];
    cache.set(text, out);
    return out;
  };
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const label = (el) => {
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/)[0] : "";
    return el.tagName.toLowerCase() + (cls ? `.${cls.replace(/-module__[A-Za-z0-9_-]{6}__/, ":")}` : "");
  };
  const path = (el) => {
    const out = [];
    for (let node = el; node && node !== document.body && out.length < 3; node = node.parentElement)
      out.unshift(label(node));
    return out.join(" > ");
  };
  const hidden = (el) => {
    for (let node = el; node; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.display === "none" || s.visibility === "hidden" || s.contentVisibility === "hidden") return true;
      if (parseFloat(s.opacity) < 0.05) return true;
      if (node.getAttribute?.("aria-hidden") === "true" && node.tagName.toLowerCase() !== "svg" && !node.closest("svg"))
        return true;
    }
    return false;
  };
  const disabled = (el) =>
    !!el.closest("[disabled], [aria-disabled='true'], fieldset[disabled], [inert]");
  const opacityOf = (el) => {
    let o = 1;
    for (let node = el; node; node = node.parentElement) o *= parseFloat(getComputedStyle(node).opacity) || 0;
    return o;
  };
  const canvas = () => {
    for (const node of [document.body, document.documentElement]) {
      const c = colourOf(getComputedStyle(node).backgroundColor);
      if (c && c[3] > 0) return h.over(c, [255, 255, 255, 1]);
    }
    return [255, 255, 255, 1];
  };
  /** What is painted under (x, y) for el: el's own layer and everything beneath it, composited. */
  const backdrop = (el, x, y) => {
    let stack = document.elementsFromPoint(x, y);
    const at = stack.findIndex((node) => node === el || node.contains(el));
    if (at >= 0) stack = stack.slice(at);
    else {
      // pointer-events: none hides el from the stack: fall back to its ancestors.
      stack = [];
      for (let node = el; node; node = node.parentElement) stack.push(node);
    }
    const layers = [];
    for (const node of stack) {
      // Only el's own box and the boxes that contain it or sit under the point count as background.
      const s = getComputedStyle(node);
      if (/url\(/.test(s.backgroundImage) || ["img", "video", "canvas", "picture"].includes(node.tagName.toLowerCase()))
        return { picture: true };
      if (s.backgroundImage && /gradient\(/.test(s.backgroundImage)) {
        // A gradient: judge it by its colour stops, worst case for the text (taken below).
        const stops = [...s.backgroundImage.matchAll(/(?:rgba?|color|oklab|oklch|lab|lch|hsla?)\([^)]*\)/g)]
          .map((m) => colourOf(m[0]))
          .filter(Boolean);
        if (stops.length) return { gradient: stops, under: layers.slice() };
      }
      const c = colourOf(s.backgroundColor);
      if (c && c[3] > 0) {
        const o = opacityOf(node);
        layers.push([c[0], c[1], c[2], c[3] * o]);
        if (c[3] * o >= 0.999) break;
      }
    }
    let colour = canvas();
    for (let i = layers.length - 1; i >= 0; i--) colour = h.over(layers[i], colour);
    return { colour };
  };
  const measure = (el, fgText, box, icon, px, weight) => {
    const fg = colourOf(fgText);
    if (!fg || fg[3] === 0) return null;
    const x = Math.min(vw - 1, Math.max(0, box.left + Math.min(box.width / 2, 6)));
    const y = Math.min(vh - 1, Math.max(0, box.top + box.height / 2));
    const under = backdrop(el, x, y);
    if (under.picture) return { picture: true };
    const alpha = fg[3] * opacityOf(el);
    const lay = (bg) => h.ratio(h.over([fg[0], fg[1], fg[2], alpha], bg), bg);
    let r;
    let bg;
    if (under.gradient) {
      let base = canvas();
      for (let i = under.under.length - 1; i >= 0; i--) base = h.over(under.under[i], base);
      const options = under.gradient.map((stop) => h.over(stop, base));
      const scored = options.map((c) => ({ c, r: lay(c) })).sort((a, b) => a.r - b.r);
      // The text sits over the middle of the gradient more than its ends: take the second-worst stop if any.
      ({ c: bg, r } = scored[Math.min(1, scored.length - 1)]);
    } else {
      bg = under.colour;
      r = lay(bg);
    }
    const need = h.needed({ icon, px, weight });
    return { r, need, fg: fgText, bg: `rgb(${bg.slice(0, 3).map(Math.round).join(", ")})` };
  };
  const failures = [];
  let runs = 0;
  let pictures = 0;
  const seen = new Set();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let text = walker.nextNode(); text; text = walker.nextNode()) {
    const content = text.textContent.replace(/\s+/g, " ").trim();
    if (!content || !/[\p{L}\p{N}]/u.test(content)) continue;
    const el = text.parentElement;
    if (!el || seen.has(el) || el.closest("svg, script, style, noscript, template")) continue;
    seen.add(el);
    const range = document.createRange();
    range.selectNodeContents(text);
    const box = [...range.getClientRects()].find((b) => b.width > 1 && b.height > 1);
    if (!box || box.bottom < 0 || box.top > vh || box.right < 0 || box.left > vw) continue;
    if (hidden(el) || disabled(el)) continue;
    const s = getComputedStyle(el);
    // Clipped away (sr-only and similar).
    if (s.clipPath && s.clipPath !== "none" && el.getBoundingClientRect().width <= 2) continue;
    runs++;
    const m = measure(el, s.color, box, false, parseFloat(s.fontSize), parseInt(s.fontWeight, 10) || 400);
    if (!m) continue;
    if (m.picture) {
      pictures++;
      continue;
    }
    if (m.r + 0.005 < m.need)
      failures.push({ el: path(el), text: content.slice(0, 24), ratio: +m.r.toFixed(2), need: m.need, fg: m.fg, bg: m.bg });
  }
  for (const svg of root.querySelectorAll("svg")) {
    const box = svg.getBoundingClientRect();
    if (box.width < 8 || box.height < 8 || box.width > 96) continue;
    if (box.bottom < 0 || box.top > vh || box.right < 0 || box.left > vw) continue;
    if (hidden(svg) || disabled(svg)) continue;
    // An icon's ink: the first visible shape's stroke, else its fill.
    let ink = null;
    for (const shape of svg.querySelectorAll("path, circle, rect, line, polyline, polygon, ellipse")) {
      const s = getComputedStyle(shape);
      if (s.display === "none" || s.visibility === "hidden") continue;
      const stroke = colourOf(s.stroke);
      const fill = colourOf(s.fill);
      if (stroke && stroke[3] > 0 && parseFloat(s.strokeWidth) > 0) ink = s.stroke;
      else if (fill && fill[3] > 0) ink = s.fill;
      if (ink) break;
    }
    // Multi-colour drawings (illustrations, avatars, logos) are pictures, not icons.
    const fills = new Set([...svg.querySelectorAll("[fill]")].map((n) => n.getAttribute("fill")));
    if (!ink || fills.size > 3) continue;
    runs++;
    const m = measure(svg, ink, box, true, 0, 400);
    if (!m || m.picture) continue;
    if (m.r + 0.005 < m.need)
      failures.push({ el: path(svg), text: "(icon)", ratio: +m.r.toFixed(2), need: m.need, fg: m.fg, bg: m.bg });
  }
  failures.sort((a, b) => a.ratio / a.need - b.ratio / b.need);
  return { runs, pictures, failures: failures.slice(0, 40), total: failures.length };
}

/** The scan as one expression for page.evaluate, the helpers passed in whole. */
export const inPage = (rootSelector) =>
  `(${scanContrast.toString()})(${JSON.stringify(rootSelector)}, { parseColour: ${parseColour.toString()}, over: ${over.toString()}, luminance: ${luminance.toString()}, ratio: ${ratio.toString()}, needed: ${needed.toString()} })`;

/** One line per screen and width with failures, the worst first; nothing when every state is clean. */
export function summarise(rows) {
  return rows
    .filter((row) => row.error || row.total)
    .sort((a, b) => Number(!!b.error) - Number(!!a.error) || b.total - a.total)
    .map((row) =>
      row.error
        ? `${row.page} @ ${row.state}: could not measure (${row.error})`
        : `${row.page} @ ${row.state}: ${row.total} below AA · ` +
          row.failures
            .slice(0, 4)
            .map((f) => `${f.el} "${f.text}" ${f.ratio}:1 (needs ${f.need})`)
            .join(", "),
    );
}
