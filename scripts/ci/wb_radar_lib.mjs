// The bug radar's parts (`wb-ci --radar`; the orchestrator for the owner, 26 Oct 2026: "find the UI bugs I report by
// hand on every build, without a person clicking": the leads list past the right edge (#28), the Review pill over a
// title, centred cards wasting a phone's width, Leads setup tabs that don't switch, Now / All leads / More cut at
// 320 px with 130% text). wb_radar.mjs runs them in Chromium on GitHub-hosted runners against the review fixtures
// (fictional data, no API); ac-bug-radar turns the groups into AC Pulse cards.
//
// Three kinds of code live here:
// - plain helpers (colours, class names, labels, element paths), unit-tested in Node and handed to the page as
//   window.__radar by helperScript();
// - in-page functions (radarScan, radarTargets, radarArm, radarMark, radarChanged, radarObserve, ...), passed to
//   page.evaluate, so each is self-contained apart from window.__radar;
// - the report: stable finding keys, dedupe across states, groups by root cause, markdown and JSON.
import { createHash } from "node:crypto";

// Phones at 320, 360 and 390 px and one computer at 1280; 100% and 130% as browser text scaling everywhere, and 130%
// as the Android app zooms on phones (clamped to 1.2, so 130% on 320 px leaves 267 CSS px); light and dark.
export const RADAR_SIZES = [
  { label: "320x640", width: 320, height: 640 },
  { label: "360x800", width: 360, height: 800 },
  { label: "390x844", width: 390, height: 844 },
  { label: "1280x800", width: 1280, height: 800, desktop: true },
];
export const RADAR_THEMES = ["light", "dark"];
// The tap crawler's state: a phone, 100%, light (and the computer for screens that ask for it).
export const CRAWL_SIZE = RADAR_SIZES[2];
// The Android app as a budget phone runs it (27 Oct 2026, the testing plan's second profile):
// - the app's user agent, so pages draw their in-app version (data-sx-app), which no other load does;
// - the app's own font-scale handshake at its 1.2 cap (window.SXFontScale, in-app.ts), not a browser zoom;
// - a 360 px phone with the CPU 4x slower, so taps can land while a page still hydrates.
export const ANDROID_PROFILE = {
  size: RADAR_SIZES[1],
  userAgent:
    "Mozilla/5.0 (Linux; Android 13; Fictional A05 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0.0.0 Mobile Safari/537.36 SalesXrayApp/1.0.42",
  fontScale: 1.2,
  cpu: 4,
};

/**
 * One page load per size, theme and zoom: 100% then 130% text on the same load; the app's 130% zoom on its own;
 * and the Android app profile, light and dark.
 */
export function radarLoads() {
  const android = RADAR_THEMES.map((theme) => ({
    size: ANDROID_PROFILE.size,
    theme,
    zoom: 1,
    android: ANDROID_PROFILE,
    states: [
      {
        ...ANDROID_PROFILE.size,
        theme,
        scale: ANDROID_PROFILE.fontScale,
        mode: "android",
      },
    ],
  }));
  return RADAR_SIZES.flatMap((size) =>
    RADAR_THEMES.flatMap((theme) => [
      {
        size,
        theme,
        zoom: 1,
        states: [
          { ...size, theme, scale: 1, mode: "app" },
          { ...size, theme, scale: 1.3, mode: "text" },
        ],
      },
      ...(size.desktop
        ? []
        : [
            {
              size,
              theme,
              zoom: 1.2,
              states: [{ ...size, theme, scale: 1.3, mode: "app" }],
            },
          ]),
    ]),
  ).concat(android);
}

/** A screen's loads: all of them, without the Android app's for a screen that says android: false. */
export const screenLoads = (screen = {}) =>
  radarLoads().filter((load) => !(load.android && screen.android === false));

/**
 * Every measured state of a page: 3 phones x 3 scales x 2 themes + 1280 x 2 scales x 2 themes + the Android app x 2
 * themes = 24.
 */
export const radarStates = () => radarLoads().flatMap((load) => load.states);

/** A state's place in a finding's "where" list, e.g. "320x640 130% text dark". */
export const stateTag = (state) =>
  `${state.label} ${Math.round(state.scale * 100)}% ${state.mode} ${state.theme}`;

/** A fixture path's screen name: /review-fixture/report-review -> report-review. */
export const fixtureKey = (path) =>
  path
    .replace(/^\/review-fixture\/?/, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60) || "root";

/**
 * The radar's pages: every named matrix screen (each reaches a state by its taps) and every other fixture page the app
 * has (`app/review-fixture/** /page.tsx`), so a new fixture is swept the day it lands.
 */
export function radarScreens(screens = {}, fixturePaths = []) {
  const entries = Object.entries(screens);
  const covered = new Set(
    entries.map(([, screen]) => screen.path.split("?")[0]),
  );
  const names = new Set(entries.map(([key]) => key));
  for (const path of [...fixturePaths].sort()) {
    if (covered.has(path)) continue;
    let key = fixtureKey(path);
    if (names.has(key)) key = `${key}-page`;
    names.add(key);
    covered.add(path);
    entries.push([key, { path }]);
  }
  return entries;
}

/** The pages a request asks for (names or fixture paths); none means all. */
export function pickRadarScreens(routes = [], screens = {}, fixturePaths = []) {
  const all = radarScreens(screens, fixturePaths);
  if (!routes.length) return all;
  const byName = new Map(all);
  return routes.map((route) => {
    if (byName.has(route)) return [route, byName.get(route)];
    if (!route.startsWith("/"))
      throw new Error(`unknown radar screen ${route}`);
    return [
      fixtureKey(route.split("?")[0]) +
        (route.includes("?") ? `-${fixtureKey(route.split("?")[1])}` : ""),
      { path: route },
    ];
  });
}

/** Shard i of n: every n-th page, so slow and quick fixtures spread over the shards. */
export const shardOf = (entries, index, count) =>
  entries.filter((_, i) => i % count === index);

// ---------------------------------------------------------------------------------------------------------------
// Helpers shared with the page (window.__radar). Each refers only to its arguments, `document` and the others here.

/** WCAG relative luminance of an sRGB colour [r, g, b] (0-255). */
export function luminance(rgb) {
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return (
    0.2126 * channel(rgb[0]) +
    0.7152 * channel(rgb[1]) +
    0.0722 * channel(rgb[2])
  );
}

/** WCAG contrast ratio of two opaque colours, 1-21. */
export function contrastRatio(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/** Colour `top` [r, g, b, alpha 0-1] painted over the opaque colour `bottom`. */
export function over(top, bottom) {
  const a = top[3] ?? 1;
  return [0, 1, 2].map((i) => top[i] * a + bottom[i] * (1 - a)).concat(1);
}

/** Large text for WCAG: 24 px, or 18.66 px bold. Large text needs 3:1, the rest 4.5:1. */
export const isLarge = (px, weight) =>
  px >= 24 || (px >= 18.66 && weight >= 700);

/** "#6b7280" for [107, 114, 128] (alpha dropped). */
export const hex = (rgb) =>
  `#${rgb
    .slice(0, 3)
    .map((v) => Math.round(v).toString(16).padStart(2, "0"))
    .join("")}`;

/**
 * A class name as a stable path part: CSS modules lose their build hash ("lightbox-shell-module__3nIbHW__tabPill" ->
 * "lightbox-shell__tabPill"); generated or icon-only names are dropped (null).
 */
export function cleanClass(name) {
  const module = /^(.+?)-module__[A-Za-z0-9_-]{5,8}__(.+)$/.exec(name);
  if (module) return `${module[1]}__${module[2]}`;
  if (name === "lucide" || /^(css|sc|jsx|emotion)-/.test(name)) return null;
  if (/\d{3,}|[^\w-]/.test(name) || name.length > 40) return null;
  return name;
}

/** Money is never shown or carried (owner rule): amounts in a label become "[amount]". */
export const scrub = (text) =>
  String(text ?? "")
    .replace(/[₹$€£]\s?[\d.,]+(\s?(k|K|L|lakh|cr|crore))?/g, "[amount]")
    .replace(/\b(Rs\.?|INR|USD)\s?[\d.,]+/g, "[amount]");

/**
 * Names out of card and report text: two capitalised words in a row ("Asha Fictional", "Fictional Homes") become
 * "[name]". Fixture people are fictional, but cards never carry a name (owner rule), so the radar doesn't either.
 */
const COMMON =
  /^(All|Now|More|Lead|Leads|Call|Calls|Review|Team|Home|Settings|Search|Notifications|Save|Edit|New|Open|Add|Show|Set|My|Your)$/;
export const namesOut = (text) =>
  String(text ?? "").replace(
    /\b[A-Z][a-z]+(?: [A-Z][a-z]+)+(?:'s)?/g,
    (match) => {
      const words = match.split(" ");
      const kept = [];
      while (words.length > 1 && COMMON.test(words[0]))
        kept.push(words.shift());
      return [...kept, words.length > 1 ? "[name]" : words[0]].join(" ");
    },
  );

/** What a person reads on an element: its accessible name, its text or its title, one line, scrubbed. */
export function labelOf(el, max = 48) {
  const text =
    el.getAttribute?.("aria-label") ||
    (el.innerText ?? el.textContent ?? "") ||
    el.labels?.[0]?.innerText ||
    el.getAttribute?.("placeholder") ||
    el.getAttribute?.("title") ||
    "";
  return scrub(text.trim().replace(/\s+/g, " ")).slice(0, max);
}

/** One step of an element path: tag, a stable id, the role, a data-sx-* switch and the first stable class. */
export function segmentOf(el) {
  const tag = el.tagName.toLowerCase();
  // React's generated ids (":r1:", "«r1»", and React 19.1's "_r_a_") change with the markup around them: never in a
  // key (the first nightly split one cut title into four groups when a card gained aria-labelledby).
  const generated = /[:«»\d]|^_[rR]_.*_$/.test(el.id ?? "");
  const id = el.id && el.id.length < 30 && !generated ? `#${el.id}` : "";
  const role = el.getAttribute("role")
    ? `[role=${el.getAttribute("role")}]`
    : "";
  const data = [...(el.attributes ?? [])]
    .map((attribute) => attribute.name)
    .find((name) => /^data-(sx|testid)/.test(name));
  let cls = "";
  for (const name of el.classList ?? []) {
    const clean = cleanClass(name);
    if (!clean) continue;
    if (!cls || clean.includes("__")) cls = `.${clean}`;
    if (clean.includes("__")) break;
  }
  return `${tag}${id}${role}${data && !id ? `[${data}]` : ""}${cls}`;
}

/**
 * A stable element path: the element and up to three meaningful ancestors (bare divs and spans skipped), never row
 * text or a position, so the same component keeps its key from build to build and across pages.
 */
export function pathOf(el) {
  const parts = [segmentOf(el)];
  for (
    let p = el.parentElement;
    p && p.tagName && !/^(BODY|HTML)$/.test(p.tagName) && parts.length < 4;
    p = p.parentElement
  ) {
    const part = segmentOf(p);
    if (/^(div|span)$/.test(part)) continue;
    parts.unshift(part);
  }
  return parts.join(" > ");
}

/** A chip, pill, tab, badge or segment by its class words ("tabPill" reads as "tab pill"). */
export const labelish = (el) =>
  /\b(chip|pill|tab|badge|tag|segment|seg)s?\b/.test(
    String(el.className?.baseVal ?? el.className ?? "")
      .replace(/-module__[A-Za-z0-9_-]{5,8}__/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .toLowerCase(),
  );

// The crawler never taps these (orchestrator, 26 Oct 2026): anything labelled Delete, Remove, Log out, Send, Call or
// WhatsApp, and anything that pays or signs out. "Calls" (the tab) is fine; "Call" is not.
export const RISKY =
  /\b(delete|remove|log ?out|sign ?out|send|call|whatsapp|erase|discard|pay|buy|purchase|upgrade|subscribe|unsubscribe|deactivate|block|leave)\b/i;
export const risky = (label) => RISKY.test(String(label ?? ""));

/** A link that leaves the app: a phone call, mail, a message app, another site, a new window or a download. */
export function leaves(href, origin, target = "", download = false) {
  if (download || target === "_blank") return true;
  if (!href) return false;
  if (/^(tel|mailto|sms|whatsapp|intent|javascript|market):/i.test(href))
    return true;
  if (/wa\.me|api\.whatsapp\.com/i.test(href)) return true;
  try {
    return new URL(href, origin).origin !== origin;
  } catch {
    return true;
  }
}

/** djb2, for "did this text change". */
export function textHash(text) {
  let h = 5381;
  for (let i = 0; i < text.length; i++)
    h = ((h << 5) + h + text.charCodeAt(i)) | 0;
  return h >>> 0;
}

/** Any CSS colour as [r, g, b, alpha] in sRGB, through a 1x1 canvas (Chrome may report oklch or color()). */
export function parseColor(value) {
  const cache = (parseColor.cache ??= new Map());
  if (cache.has(value)) return cache.get(value);
  let rgba = null;
  const plain =
    /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/.exec(
      value,
    );
  if (plain) {
    const alpha =
      plain[4] === undefined
        ? 1
        : plain[4].endsWith("%")
          ? parseFloat(plain[4]) / 100
          : Number(plain[4]);
    rgba = [Number(plain[1]), Number(plain[2]), Number(plain[3]), alpha];
  } else if (value === "transparent") {
    rgba = [0, 0, 0, 0];
  } else if (
    typeof document !== "undefined" &&
    globalThis.CSS?.supports?.("color", value)
  ) {
    const canvas = (parseColor.canvas ??= document.createElement("canvas"));
    canvas.width = canvas.height = 1;
    const ctx = (parseColor.ctx ??= canvas.getContext("2d", {
      willReadFrequently: true,
    }));
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = value;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    rgba = [d[0], d[1], d[2], d[3] / 255];
  }
  cache.set(value, rgba);
  return rgba;
}

/**
 * The sheet that covers the page now, or null: the last modal dialog (with two open, a composer over the lead sheet,
 * the last is on top), else the last open dialog whose own box or a child's (its scrim, its panel) covers a quarter
 * of the screen (a sheet opened with show(); a small popover does not count).
 */
export function openSheet() {
  const screen = document.documentElement.clientWidth * innerHeight;
  const big = (d) =>
    d.checkVisibility?.() !== false &&
    [d, ...d.children].some((c) => {
      const r = c.getBoundingClientRect();
      return r.width * r.height >= 0.25 * screen;
    });
  return (
    [...document.querySelectorAll("dialog:modal")].at(-1) ??
    [
      ...document.querySelectorAll(
        'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]',
      ),
    ]
      .filter(big)
      .at(-1) ??
    null
  );
}

const SHARED = {
  openSheet,
  luminance,
  contrastRatio,
  over,
  isLarge,
  hex,
  cleanClass,
  scrub,
  labelOf,
  segmentOf,
  pathOf,
  labelish,
  risky,
  leaves,
  textHash,
  parseColor,
};

/** The page-side copy of the helpers: one init script that sets window.__radar. */
export function helperScript() {
  const body = Object.entries(SHARED)
    .map(([name, fn]) => `const ${name} = ${fn.toString()};`)
    .join("\n");
  return `(() => {\nconst RISKY = ${RISKY.toString()};\n${body}\nwindow.__radar = { ${Object.keys(SHARED).join(", ")} };\n})();`;
}

// ---------------------------------------------------------------------------------------------------------------
// In the page.

/**
 * Runs in the page: the static checks on what is drawn now. `scope` limits them to one element (a sheet opened by a
 * tap). Returns { findings: [{check, severity, selector, label, detail, hit, colors?}] }; `hit` names the
 * data-radar-hit mark on the element(s), for the cropped screenshot.
 */
export function radarScan(options = {}) {
  const R = window.__radar;
  if (!R) throw new Error("radar helpers missing");
  const doc = document.documentElement;
  const W = doc.clientWidth;
  const phone = options.phone ?? W < 768;
  const scope = options.scope
    ? document.querySelector(options.scope)
    : document.body;
  if (!scope) return { findings: [] };
  for (const el of document.querySelectorAll("[data-radar-hit]"))
    el.removeAttribute("data-radar-hit");
  const findings = [];
  const seen = new Set();
  let hits = 0;
  const mark = (els) => {
    const n = String(++hits);
    for (const el of els)
      el.setAttribute(
        "data-radar-hit",
        `${el.getAttribute("data-radar-hit") ?? ""} ${n}`.trim(),
      );
    return n;
  };
  const add = (finding, els) => {
    const once = `${finding.check}|${finding.selector}|${finding.colors ?? ""}`;
    if (seen.has(once)) return;
    seen.add(once);
    findings.push({
      ...finding,
      label: R.scrub(finding.label ?? ""),
      hit: mark(els),
    });
  };

  const styles = new Map();
  const st = (el) => {
    let s = styles.get(el);
    if (!s) styles.set(el, (s = getComputedStyle(el)));
    return s;
  };
  const rects = new Map();
  const rectOf = (el) => {
    let r = rects.get(el);
    if (!r) {
      const b = el.getBoundingClientRect();
      rects.set(
        el,
        (r = {
          l: b.left,
          t: b.top,
          r: b.right,
          b: b.bottom,
          w: b.width,
          h: b.height,
        }),
      );
    }
    return r;
  };
  const opacities = new Map();
  const opacity = (el) => {
    if (!el || el === doc) return 1;
    if (!opacities.has(el))
      opacities.set(el, Number(st(el).opacity) * opacity(el.parentElement));
    return opacities.get(el);
  };
  // checkVisibility also hides what is laid out but never painted: a closed <details>'s menu (baseline 26 Oct:
  // 42 "overlap" groups were closed menus over the report's tabs) and content-visibility: hidden.
  const shown = (el) => {
    const s = st(el);
    return (
      s.display !== "none" &&
      s.visibility !== "hidden" &&
      s.visibility !== "collapse" &&
      opacity(el) > 0.05 &&
      (!el.checkVisibility || el.checkVisibility())
    );
  };
  // Where an element's content can be seen: hidden or clipped overflow cuts it; a scroller doesn't (it scrolls).
  const NONE = { l: -1e9, t: -1e9, r: 1e9, b: 1e9 };
  const clips = new Map();
  const clipOf = (el) => {
    if (!el || el === doc || el === document.body) return NONE;
    if (clips.has(el)) return clips.get(el);
    const s = st(el);
    let c = s.position === "fixed" ? NONE : clipOf(el.parentElement);
    const both =
      (s.clipPath && s.clipPath !== "none") || (s.clip && s.clip !== "auto");
    const x = both || /hidden|clip/.test(s.overflowX);
    const y = both || /hidden|clip/.test(s.overflowY);
    if (x || y) {
      const b = rectOf(el);
      c = {
        l: x ? Math.max(c.l, b.l) : c.l,
        r: x ? Math.min(c.r, b.r) : c.r,
        t: y ? Math.max(c.t, b.t) : c.t,
        b: y ? Math.min(c.b, b.b) : c.b,
      };
    }
    clips.set(el, c);
    return c;
  };
  const inter = (a, c) => {
    const l = Math.max(a.l, c.l);
    const r = Math.min(a.r, c.r);
    const t = Math.max(a.t, c.t);
    const b = Math.min(a.b, c.b);
    return { l, r, t, b, w: Math.max(0, r - l), h: Math.max(0, b - t) };
  };
  // Elements are compared only inside one layer: the page, a fixed or sticky bar, or a dialog.
  const LAYER =
    'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"], [popover]';
  const layers = new Map();
  const layerOf = (el) => {
    if (!el || el === document.body || el === doc) return document.body;
    if (!layers.has(el)) {
      const s = st(el);
      layers.set(
        el,
        s.position === "fixed" || s.position === "sticky" || el.matches(LAYER)
          ? el
          : layerOf(el.parentElement),
      );
    }
    return layers.get(el);
  };
  // The box an element scrolls with. Content scrolled under a sheet's footer or a bar is by design, so overlaps
  // count only inside one scroller.
  const ports = new Map();
  const portOf = (el) => {
    if (!el || el === document.body || el === doc) return document.body;
    if (!ports.has(el)) {
      const p = el.parentElement;
      const s = p && p !== document.body ? st(p) : null;
      ports.set(
        el,
        s && /auto|scroll/.test(`${s.overflowX} ${s.overflowY}`)
          ? p
          : portOf(p),
      );
    }
    return ports.get(el);
  };
  // A fixed bar slid off the screen until it is needed (a selection bar below the bottom edge): not drawn.
  const parked = (el) => {
    const r = rectOf(el);
    if (r.t < innerHeight && r.b > 0 && r.l < W && r.r > 0) return false;
    for (let p = el; p && p !== document.body; p = p.parentElement)
      if (st(p).position === "fixed") return true;
    return false;
  };
  // Inside a box that scrolls sideways on purpose (a chip strip, a wide table).
  const inScroller = (el) => {
    for (
      let p = el.parentElement;
      p && p !== document.body;
      p = p.parentElement
    )
      if (/auto|scroll/.test(st(p).overflowX) && rectOf(p).r <= W + 1)
        return true;
    return false;
  };
  const TAPPABLE =
    'a[href], button, [role="button"], [role="tab"], [role="link"], [role="menuitem"], [role="option"], [role="switch"], [role="checkbox"], [role="radio"], summary, input:not([type="hidden"]), select, textarea';
  const CONTROL =
    'button, [role="button"], [role="tab"], [role="link"], [role="menuitem"], [role="option"], [role="switch"], [role="radio"], [role="checkbox"], a[href], summary, label';

  const all = [...scope.querySelectorAll("*")].filter(
    (el) =>
      !(el instanceof SVGElement && el.tagName.toLowerCase() !== "svg") &&
      !/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|LINK|META)$/.test(el.tagName) &&
      shown(el) &&
      // Parked above or left of the page until focused (a skip link): not seen, not measured.
      rectOf(el).b > 0 &&
      rectOf(el).r > 0 &&
      !parked(el),
  );
  const range = document.createRange();
  const texts = [];
  for (const el of all)
    for (const node of el.childNodes) {
      if (node.nodeType !== 3 || !node.textContent.trim()) continue;
      range.selectNodeContents(node);
      const boxes = [...range.getClientRects()]
        .map((b) =>
          inter({ l: b.left, t: b.top, r: b.right, b: b.bottom }, clipOf(el)),
        )
        .filter((b) => b.w >= 2 && b.h >= 2);
      if (boxes.length)
        texts.push({ node, el, boxes, text: node.textContent.trim() });
    }

  // 1. Past the right edge: the page scrolls sideways, or an element (outside a scroller) crosses the edge.
  const wide = [];
  for (const el of all) {
    const r = rectOf(el);
    if (r.w < 3 || r.h < 3 || (r.r <= W + 1 && r.l >= -1)) continue;
    if (r.l >= W - 1 || r.r <= 1) continue; // parked off the page (a closed drawer)
    if (inScroller(el)) continue;
    const c = clipOf(el.parentElement);
    if (c.r <= W + 1 && c.l >= -1) continue; // cut by a box inside the page: not a page overflow
    if (wide.some((w) => w.contains(el))) continue;
    wide.push(el);
    add(
      {
        check: "overflow-element",
        severity: phone ? "high" : "medium",
        selector: R.pathOf(el),
        label: R.labelOf(el),
        detail:
          r.r > W + 1
            ? `${Math.round(r.r - W)} px past the right edge`
            : `${Math.round(-r.l)} px past the left edge`,
      },
      [el],
    );
  }
  if (!options.scope && !wide.length) {
    const sw = Math.max(doc.scrollWidth, document.body.scrollWidth);
    if (sw > W + 1)
      add(
        {
          check: "overflow-page",
          severity: phone ? "high" : "medium",
          selector: "html",
          label: "",
          detail: `the page is ${sw} px wide in ${W}`,
        },
        [doc],
      );
  }

  // 2. Overlap: text or controls drawn over each other in one layer (a pill over a title).
  const items = [];
  for (const el of all) {
    if (!el.matches(TAPPABLE)) continue;
    // An inline link that wraps is two line boxes, not their union (which covers the next link).
    const pieces =
      st(el).display === "inline"
        ? [...el.getClientRects()].map((b) => ({
            l: b.left,
            t: b.top,
            r: b.right,
            b: b.bottom,
          }))
        : [rectOf(el)];
    for (const piece of pieces) {
      const r = inter(piece, clipOf(el.parentElement));
      if (r.w >= 4 && r.h >= 4)
        items.push({
          kind: "box",
          el,
          r,
          layer: layerOf(el),
          port: portOf(el),
        });
    }
  }
  for (const t of texts)
    for (const r of t.boxes)
      items.push({
        kind: "text",
        el: t.el,
        node: t.node,
        r,
        layer: layerOf(t.el),
        port: portOf(t.el),
      });
  const labelFor = (text, control) => {
    const label = text.el.closest("label");
    return label && (label.control === control || label.contains(control));
  };
  const pairs = new Set();
  items.sort((a, b) => a.r.t - b.r.t);
  for (let i = 0; i < items.length; i++)
    for (
      let j = i + 1;
      j < items.length && items[j].r.t < items[i].r.b - 3;
      j++
    ) {
      const a = items[i];
      const b = items[j];
      if (a.layer !== b.layer || a.port !== b.port) continue;
      if (a.node && a.node === b.node) continue;
      const ox = Math.min(a.r.r, b.r.r) - Math.max(a.r.l, b.r.l);
      const oy = Math.min(a.r.b, b.r.b) - Math.max(a.r.t, b.r.t);
      if (ox < 4 || oy < 4) continue;
      if (a.kind === "box" && b.kind === "box") {
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
        // Two controls' boxes touching at an edge (a sheet's close button over a wide row's corner, 8 x 4 px) hide
        // nothing: skip a thin overlap that is also a small share of the smaller one. Two fields overlapping by
        // 28 x 44 px (Lead rules' From and To) still count.
        const smaller = Math.min(a.r.w * a.r.h, b.r.w * b.r.h);
        if (Math.min(ox, oy) < 8 && ox * oy < 0.15 * smaller) continue;
      }
      const [box, text] = a.kind === "box" ? [a, b] : [b, a];
      if (box.kind === "box" && text.kind === "text") {
        if (
          box.el.contains(text.el) ||
          text.el.contains(box.el) ||
          labelFor(text, box.el)
        )
          continue;
      }
      if (a.kind === "text" && b.kind === "text" && a.el === b.el && oy < 6)
        continue; // one line split in two nodes
      const sa = R.pathOf(a.el);
      const sb = R.pathOf(b.el);
      const selector = [sa, sb].sort().join(" ⟂ ");
      if (pairs.has(selector)) continue;
      pairs.add(selector);
      add(
        {
          check: "overlap",
          severity: a.kind === "box" || b.kind === "box" ? "high" : "medium",
          selector,
          label: `"${R.labelOf(a.el, 30)}" over "${R.labelOf(b.el, 30)}"`,
          detail: `${Math.round(ox)} x ${Math.round(oy)} px drawn over each other`,
        },
        [a.el, b.el],
      );
    }

  // 3. Labels cut short: a tab, button, chip or heading whose words end in an ellipsis or are clipped, or run out of it.
  // The finding names the box that cuts (the line that ends in "…"), not a word inside it.
  const clipped = new Set();
  for (const t of texts) {
    const el = t.el;
    const control =
      el.closest(CONTROL) ?? (R.labelish(el) ? el : el.closest("h1, h2, h3"));
    if (!control || !scope.contains(control)) continue;
    let cut = null;
    for (let p = el; p; p = p.parentElement) {
      const s = st(p);
      const ellipsis = s.textOverflow === "ellipsis";
      if (
        (ellipsis || /hidden|clip/.test(s.overflowX)) &&
        p.scrollWidth > p.clientWidth + 1
      ) {
        cut = {
          box: p,
          how: ellipsis ? "ends in …" : "is clipped",
          shown: p.clientWidth,
          full: p.scrollWidth,
        };
        break;
      }
      if (
        s.webkitLineClamp &&
        s.webkitLineClamp !== "none" &&
        p.scrollHeight > p.clientHeight + 1
      ) {
        cut = {
          box: p,
          how: "is cut by a line clamp",
          shown: p.clientHeight,
          full: p.scrollHeight,
        };
        break;
      }
      if (p === control) break;
    }
    if (cut) {
      if (clipped.has(cut.box)) continue;
      clipped.add(cut.box);
      const text = (cut.box.innerText ?? t.text).trim().replace(/\s+/g, " ");
      const words = (control.innerText ?? "").trim();
      const tabLike =
        control.matches('[role="tab"]') ||
        R.labelish(control) ||
        R.labelish(cut.box);
      // A table cell's words are data (a name, a stage): cut on purpose, so never a label.
      const cell = !!control.closest(
        'td, th, [role="cell"], [role="gridcell"]',
      );
      const label =
        !cell &&
        (tabLike ||
          (text.length <= 28 && words.length <= 48) ||
          /^H[1-3]$/.test(control.tagName));
      add(
        {
          check: label ? "clipped-label" : "clipped-text",
          severity: !label
            ? "low"
            : cut.shown / cut.full < 0.6
              ? "high"
              : "medium",
          selector: R.pathOf(cut.box),
          label: R.labelOf(cut.box),
          detail: `"${R.scrub(text).slice(0, 40)}" ${cut.how}: ${cut.shown} of ${cut.full} px shown`,
        },
        [cut.box],
      );
      continue;
    }
    // Text running visibly out of its control, nothing clipping it.
    if (!el.closest('button, a, [role="button"], [role="tab"], label'))
      continue;
    // Beyond rounding (2 px sideways) and tall scripts' glyph boxes (4 px down, Devanagari).
    const box = rectOf(control);
    for (const b of t.boxes)
      if (b.r > box.r + 2 || b.l < box.l - 2 || b.b > box.b + 4) {
        add(
          {
            check: "text-spill",
            severity: "medium",
            selector: R.pathOf(control),
            label: R.labelOf(control),
            detail: `text ${Math.round(b.r - b.l)} px wide runs out of a ${Math.round(box.w)} px control`,
          },
          [control],
        );
        break;
      }
  }

  // 4. Taps under 44 x 44 on a phone (an inline link inside a sentence is exempt; a pseudo-element can widen a target).
  if (phone)
    for (const el of all) {
      if (
        !el.matches(TAPPABLE) ||
        el.closest('[aria-hidden="true"], [inert]') ||
        el.matches(":disabled")
      )
        continue;
      const r = rectOf(el);
      // A visually hidden input (1 x 1, opened by its label or a button) is not what a person taps.
      if (r.w < 4 && r.h < 4) continue;
      const s = st(el);
      if (
        el.tagName === "A" &&
        s.display === "inline" &&
        [...(el.parentElement?.childNodes ?? [])].some(
          (n) => n !== el && n.nodeType === 3 && n.textContent.trim(),
        )
      )
        continue;
      let w = r.w;
      let h = r.h;
      for (const which of ["::before", "::after"]) {
        const ps = getComputedStyle(el, which);
        if (ps.content === "none" || ps.position !== "absolute") continue;
        const [top, right, bottom, left] = [
          ps.top,
          ps.right,
          ps.bottom,
          ps.left,
        ].map((v) => (v.endsWith("px") ? parseFloat(v) : null));
        if ([top, right, bottom, left].every((v) => v !== null)) {
          w = Math.max(w, r.w - left - right);
          h = Math.max(h, r.h - top - bottom);
        }
      }
      if (
        el.matches(
          'input[type="checkbox"], input[type="radio"], [role="checkbox"], [role="radio"]',
        )
      ) {
        const label =
          el.closest("label") ??
          (el.id
            ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`)
            : null);
        if (label) {
          w = Math.max(w, rectOf(label).w);
          h = Math.max(h, rectOf(label).h);
        }
      }
      if (w >= 44 && h >= 44) continue;
      add(
        {
          check: "tap-target",
          severity: Math.min(w, h) < 24 ? "medium" : "low",
          selector: R.pathOf(el),
          label: R.labelOf(el),
          detail: `${Math.round(w)} x ${Math.round(h)} px to tap`,
        },
        [el],
      );
    }

  // 5. Faint text: under 4.5:1 against what is behind it (3:1 for large text); unknown over pictures and gradients.
  const dark =
    matchMedia("(prefers-color-scheme: dark)").matches &&
    /dark/.test(st(doc).colorScheme ?? "");
  const canvas = dark ? [18, 18, 18, 1] : [255, 255, 255, 1];
  const backdrop = (el) => {
    const layers = [];
    for (let p = el; p; p = p.parentElement) {
      const s = st(p);
      if (s.backgroundImage && s.backgroundImage !== "none") return null;
      if (s.backdropFilter && s.backdropFilter !== "none") return null;
      const c = R.parseColor(s.backgroundColor);
      if (c && c[3] > 0.01) {
        layers.push(c);
        if (c[3] >= 0.99)
          return {
            color: layers
              .reverse()
              .reduce((under, top) => R.over(top, under), canvas),
            owner: p,
          };
      }
    }
    return {
      color: layers
        .reverse()
        .reduce((under, top) => R.over(top, under), canvas),
      owner: doc,
    };
  };
  const checked = new Set();
  for (const t of texts) {
    const el = t.el;
    if (checked.has(el)) continue;
    checked.add(el);
    if (el.closest(':disabled, [aria-disabled="true"], [inert]')) continue;
    const s = st(el);
    const fg = R.parseColor(s.color);
    const back = backdrop(el);
    if (!fg || !back) continue;
    const fade = opacity(el) / (back.owner === doc ? 1 : opacity(back.owner));
    const ink = R.over([fg[0], fg[1], fg[2], (fg[3] ?? 1) * fade], back.color);
    const ratio = R.contrastRatio(ink, back.color);
    const large = R.isLarge(
      parseFloat(s.fontSize),
      Number(s.fontWeight) || 400,
    );
    const needed = large ? 3 : 4.5;
    if (ratio >= needed) continue;
    const colors = `${R.hex(ink)} on ${R.hex(back.color)}`;
    // One or two letters (a monogram, a brand mark) are a picture more than words: listed, never urgent.
    const mark = t.text.length <= 2;
    add(
      {
        check: "contrast",
        severity: mark
          ? "low"
          : ratio < 2
            ? "high"
            : ratio < 3
              ? "medium"
              : "low",
        selector: R.pathOf(el),
        label: R.labelOf(el),
        detail: `${ratio.toFixed(2)}:1 (needs ${needed}:1) for ${Math.round(parseFloat(s.fontSize))} px text, ${colors}`,
        colors,
      },
      [el],
    );
  }

  // 6. A narrow card centred on a phone: over a quarter of the width left empty, split on both sides.
  if (phone && !options.scope) {
    const cards = [];
    for (const el of all) {
      const r = rectOf(el);
      if (r.w < 160 || r.h < 80) continue;
      const left = r.l;
      const right = W - r.r;
      if (
        left < 0.1 * W ||
        right < 0.1 * W ||
        left + right < 0.25 * W ||
        Math.abs(left - right) > 12
      )
        continue;
      if (cards.some((card) => card.contains(el)) || inScroller(el)) continue;
      const s = st(el);
      const bg = R.parseColor(s.backgroundColor);
      const parentBg = el.parentElement
        ? R.parseColor(st(el.parentElement).backgroundColor)
        : null;
      const box =
        (s.boxShadow && s.boxShadow !== "none") ||
        (parseFloat(s.borderTopWidth) > 0 &&
          parseFloat(s.borderBottomWidth) > 0 &&
          (R.parseColor(s.borderTopColor)?.[3] ?? 0) > 0.05) ||
        (bg &&
          bg[3] > 0.05 &&
          (!parentBg ||
            R.hex(bg) !== R.hex(parentBg) ||
            bg[3] !== parentBg[3]));
      if (!box || (el.innerText ?? "").trim().length < 10) continue;
      cards.push(el);
      const dialog = el.closest(LAYER);
      add(
        {
          check: "centred-card",
          severity: dialog ? "low" : "medium",
          selector: R.pathOf(el),
          label: R.labelOf(el, 40),
          detail: `${Math.round(r.w)} px wide in ${W}: ${Math.round(left)} px empty on the left, ${Math.round(right)} on the right`,
        },
        [el],
      );
    }
  }
  // 7. A tab, segment or chip whose label wraps (owner bug #43, 27 Oct 2026: "Connected / apps" and "AI / replies"
  // in the Connections bar): the label's text runs taller than 1.5 of its lines. Short words only (32 characters),
  // so a card title that wraps on purpose is never a label.
  const TABLIKE =
    '[role="tab"], [aria-pressed], [role="group"] > button, [role="tablist"] :is(a, button)';
  // A chip by its class's last word ("signalTag", "routing-rules__chip"); "tagGroupHeading" is a heading.
  const chipClass = (el) =>
    !/^H[1-6]$/.test(el.tagName) &&
    String(el.className?.baseVal ?? el.className ?? "")
      .split(/\s+/)
      .some((name) =>
        /(chip|pill|tab|badge|tag|segment|seg)s?$/i.test(
          name.replace(/__[A-Za-z0-9_-]{5}$/, ""),
        ),
      );
  const tabOf = (el) => {
    const tab = el.closest(TABLIKE);
    if (tab) return tab;
    for (
      let p = el, up = 0;
      p && p !== document.body && up < 3;
      p = p.parentElement, up++
    )
      if (chipClass(p) && p.children.length <= 3) return p;
    return null;
  };
  const words = (text) =>
    String(text ?? "")
      .replace(/\s+/g, " ")
      .trim();
  const wrapped = new Set();
  for (const t of texts) {
    if (t.text.length > 32) continue;
    const tab = tabOf(t.el);
    if (!tab || wrapped.has(tab)) continue;
    // The label is the control's whole text: a choice card's title over its description, or a count over its
    // name, wraps by design (the first baseline of this check: setup choices, report count cards).
    if (words(tab.innerText) !== words(t.text)) continue;
    const s = st(t.el);
    const size = parseFloat(s.fontSize) || 16;
    const line = parseFloat(s.lineHeight) || size * 1.2; // "normal" is about 1.2
    const top = Math.min(...t.boxes.map((b) => b.t));
    const bottom = Math.max(...t.boxes.map((b) => b.b));
    if (bottom - top <= 1.5 * line) continue;
    wrapped.add(tab);
    const lines = new Set(t.boxes.map((b) => Math.round(b.t / (line / 2))))
      .size;
    add(
      {
        check: "label-wraps",
        severity: phone ? "high" : "medium",
        selector: R.pathOf(tab),
        label: R.labelOf(tab),
        detail: `"${R.scrub(t.text).slice(0, 32)}" wraps to ${Math.max(2, lines)} lines: ${Math.round(bottom - top)} px of text on a ${Math.round(line)} px line`,
      },
      [tab],
    );
  }

  // 8. A tab bar cut by the screen's edge (bug #43: "Puls…" at the right): its last item runs past the edge, or is
  // clipped there, and nothing in the bar scrolls to reach it (a bar that scrolls inside the screen is fine).
  const BAR = '[role="tablist"], [role="group"], [role="radiogroup"], nav';
  const ITEM = 'a[href], button, [role="tab"], [role="radio"]';
  for (const bar of all) {
    if (!bar.matches(BAR) && !R.labelish(bar)) continue;
    const box = rectOf(bar);
    if (box.h > 120) continue; // a row of tabs, not a panel of controls
    const items = [...bar.querySelectorAll(ITEM)].filter(
      (item) => shown(item) && rectOf(item).w >= 3 && rectOf(item).h >= 3,
    );
    if (items.length < 2 || items.length > 24) continue;
    const last = items.reduce((a, b) => (rectOf(b).r > rectOf(a).r ? b : a));
    const r = rectOf(last);
    // What of it can be seen: up to the screen's edge, or a clip at that edge (the page's own wrapper).
    const limit = Math.min(W, clipOf(last).r);
    if (r.r <= limit + 2 || limit < W - 24 || inScroller(last)) continue;
    add(
      {
        check: "tabs-clipped",
        severity: phone ? "high" : "medium",
        selector: R.pathOf(bar),
        label: R.labelOf(last),
        detail:
          r.l >= limit
            ? `its last item, "${R.labelOf(last, 24)}", is past the screen edge; the bar does not scroll`
            : `its last item, "${R.labelOf(last, 24)}", is cut at the screen edge: ${Math.round(limit - r.l)} of ${Math.round(r.w)} px shown; the bar does not scroll`,
      },
      [bar],
    );
  }

  return { findings };
}

/** Runs in the page: each scroll position, kept while crops scroll elements into view, then put back. */
export function radarScrollSave() {
  const kept = [];
  for (const el of [
    document.scrollingElement,
    ...document.querySelectorAll("*"),
  ])
    if (el && (el.scrollTop || el.scrollLeft))
      kept.push([el, el.scrollTop, el.scrollLeft]);
  window.__radarScroll = kept;
}
export function radarScrollRestore() {
  // "instant" for the same reason as in radarFocusHit: the next scan must not measure a page still scrolling.
  const to = (el, left, top) =>
    el?.scrollTo({ left, top, behavior: "instant" });
  for (const el of document.querySelectorAll("*"))
    if (el.scrollTop || el.scrollLeft) to(el, 0, 0);
  to(document.scrollingElement, 0, 0);
  for (const [el, top, left] of window.__radarScroll ?? []) to(el, left, top);
}

/** Runs in the page: the marked element(s) scrolled into view and outlined; their box in the viewport. */
export function radarFocusHit(id) {
  const els = [...document.querySelectorAll(`[data-radar-hit~="${id}"]`)];
  if (!els.length) return null;
  if (!document.getElementById("radar-outline")) {
    const style = document.createElement("style");
    style.id = "radar-outline";
    style.textContent =
      "[data-radar-on]{outline:2px solid #e5484d!important;outline-offset:1px!important}";
    document.head.append(style);
  }
  // Scroll only what is off the screen: scrolling a sticky bar that is already in view moved it out of the crop.
  const first = els[0].getBoundingClientRect();
  if (first.bottom <= 0 || first.top >= innerHeight)
    // "instant": the app's scroll-behavior: smooth would still be moving when the box is measured.
    els[0].scrollIntoView({
      behavior: "instant",
      block: "center",
      inline: "nearest",
    });
  let box = null;
  for (const el of els) {
    if (el !== document.documentElement) el.setAttribute("data-radar-on", "");
    const r = el.getBoundingClientRect();
    box = box
      ? {
          l: Math.min(box.l, r.left),
          t: Math.min(box.t, r.top),
          r: Math.max(box.r, r.right),
          b: Math.max(box.b, r.bottom),
        }
      : { l: r.left, t: r.top, r: r.right, b: r.bottom };
  }
  return box;
}
export function radarUnfocus() {
  for (const el of document.querySelectorAll("[data-radar-on]"))
    el.removeAttribute("data-radar-on");
}

/**
 * A crop around a box: 40 px of context, at least 280 x 140 so a person sees where it is, inside the viewport, at
 * most 480 px tall.
 */
export function cropBox(box, viewport) {
  const whole = {
    x: 0,
    y: 0,
    width: viewport.width,
    height: Math.min(viewport.height, 480),
  };
  if (!box || box.r - box.l < 1 || box.b - box.t < 1) return whole;
  // Grow a span to `min` around its middle, keep it inside 0..limit, and grow the other way if an edge cut it.
  const span = (from, to, min, limit) => {
    const grow = Math.max(0, min - (to - from)) / 2;
    let a = Math.max(0, Math.floor(from - grow));
    let b = Math.min(limit, Math.ceil(to + grow));
    if (b - a < min) {
      if (a === 0) b = Math.min(limit, min);
      else a = Math.max(0, b - min);
    }
    return [a, b];
  };
  const [x, right] = span(box.l - 40, box.r + 40, 280, viewport.width);
  const [y, bottom] = span(box.t - 40, box.b + 40, 140, viewport.height);
  if (right - x < 8 || bottom - y < 8) return whole;
  return { x, y, width: right - x, height: Math.min(bottom - y, 480) };
}

// The tap crawler, in the page. A control's identity is its path, its label and its place among equals, so the same
// control is found again after a reload.
export const CRAWL =
  'a[href], button, [role="button"], [role="tab"], [role="link"], [role="menuitem"], [role="switch"], [role="option"], summary';

/** Runs in the page: every visible control a person could tap (options.selector: CRAWL), numbered with data-radar-id. */
export function radarTargets(options = {}) {
  const R = window.__radar;
  const SELECTOR = options.selector ?? "button";
  const W = document.documentElement.clientWidth;
  const out = [];
  const count = new Map();
  let n = 0;
  // While a modal sheet is open, only its controls can be tapped; the page behind its scrim is not a target.
  const modal = R.openSheet();
  for (const el of document.querySelectorAll(SELECTOR)) {
    el.removeAttribute("data-radar-id");
    if (modal && !modal.contains(el)) continue;
    if (el.checkVisibility && !el.checkVisibility()) continue; // a closed <details>'s menu
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (
      r.width < 3 ||
      r.height < 3 ||
      s.visibility === "hidden" ||
      Number(s.opacity) < 0.05
    )
      continue;
    if (r.bottom <= 0 || r.right <= 0) continue; // parked off the page until focused (a skip link)
    if (
      el.closest('[aria-hidden="true"], [inert], nextjs-portal') ||
      el.matches(":disabled, [aria-disabled='true']")
    )
      continue;
    if (r.left >= W || r.right <= 0) {
      let scrolls = false;
      for (let p = el.parentElement; p && !scrolls; p = p.parentElement)
        scrolls = /auto|scroll/.test(getComputedStyle(p).overflowX);
      if (!scrolls) continue;
    }
    let hidden = false;
    for (let p = el; p && !hidden; p = p.parentElement)
      hidden =
        getComputedStyle(p).display === "none" ||
        Number(getComputedStyle(p).opacity) < 0.05;
    if (hidden) continue;
    const id = String(n++);
    el.setAttribute("data-radar-id", id);
    const selector = R.pathOf(el);
    const label = R.labelOf(el, 60);
    const identity = `${selector}|${label}`;
    const index = count.get(identity) ?? 0;
    count.set(identity, index + 1);
    const role = el.getAttribute("role") ?? el.tagName.toLowerCase();
    const parentRole = el.parentElement?.getAttribute("role") ?? "";
    // A segmented switch: toggles side by side with exactly one pressed. Several pressed (days of the week) is a
    // multi-choice, not tabs.
    const toggles = [...(el.parentElement?.children ?? [])].filter((c) =>
      c.hasAttribute("aria-pressed"),
    );
    const pressedGroup =
      el.hasAttribute("aria-pressed") &&
      toggles.length > 1 &&
      toggles.filter((c) => c.getAttribute("aria-pressed") === "true")
        .length === 1;
    // Real tabs say so (role, aria-selected, a tab list); a segmented switch may be a mode (a playback speed).
    const tabLike =
      role === "tab" ||
      el.hasAttribute("aria-selected") ||
      /^(tablist|radiogroup)$/.test(parentRole)
        ? "tab"
        : pressedGroup
          ? "segment"
          : false;
    const on = (name) => el.getAttribute(name);
    const selected =
      on("aria-selected") === "true" ||
      on("aria-pressed") === "true" ||
      on("aria-checked") === "true" ||
      (on("aria-current") !== null && on("aria-current") !== "false");
    const href = el.getAttribute("href");
    let skip = null;
    if (R.risky(label)) skip = "risky";
    else if (
      href !== null &&
      R.leaves(
        href,
        location.origin,
        el.getAttribute("target") ?? "",
        el.hasAttribute("download"),
      )
    )
      skip = "leaves";
    out.push({ id, selector, label, index, role, tabLike, selected, skip });
  }
  return out;
}

/**
 * Runs in the page: a sheet that opened by itself after the list was made (a prompt that waits for the page to
 * settle) now covers control `id`, so a tap would land on the sheet.
 */
export function radarCovered(id) {
  const sheet = window.__radar.openSheet();
  const el = document.querySelector(`[data-radar-id="${id}"]`);
  return !!(sheet && el && !sheet.contains(el));
}

/** Runs in the page: start watching; changes made before radarMark() (clocks, sliding figures) are the page's own. */
export function radarArm() {
  const tap = window.__radarTap;
  tap?.observer?.disconnect();
  const state = (window.__radarTap = {
    noise: new WeakSet(),
    counting: false,
    changes: 0,
  });
  state.observer = new MutationObserver((list) => {
    for (const m of list) {
      const target =
        m.target.nodeType === 1 ? m.target : m.target.parentElement;
      if (!target || target.closest?.("nextjs-portal")) continue;
      if (m.type === "attributes" && /^data-radar/.test(m.attributeName ?? ""))
        continue;
      if (!state.counting) state.noise.add(target);
      else if (!state.noise.has(target)) state.changes++;
    }
  });
  state.observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    characterData: true,
  });
}

/** Runs in the page: what the page looks like just before the tap on control `id`. */
export function radarMark(id) {
  const R = window.__radar;
  const state = window.__radarTap;
  const el = document.querySelector(`[data-radar-id="${id}"]`);
  // The control's own strip (a tab list, a segmented switch): its text is not "the content".
  const group = el
    ? (el.closest(
        '[role="tablist"], [role="radiogroup"], [role="group"], [role="toolbar"], nav',
      ) ?? el.parentElement)
    : null;
  const outside = () =>
    R.textHash(document.body.innerText.replace(group?.innerText ?? "", ""));
  const scrolls = [document.scrollingElement, ...document.querySelectorAll("*")]
    .filter((e) => e && (e.scrollTop || e.scrollLeft))
    .map((e) => `${e.scrollTop},${e.scrollLeft}`)
    .join(";");
  const dialogs = new Set(
    [
      ...document.querySelectorAll(
        'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]',
      ),
    ].filter((d) => d.getBoundingClientRect().width > 0),
  );
  Object.assign(state, {
    counting: true,
    url: location.href,
    scrolls,
    active: document.activeElement,
    checked: [...document.querySelectorAll("input")]
      .map((i) => `${i.checked}`)
      .join(""),
    dialogs,
    outside: outside(),
  });
  state.outsideNow = outside;
  state.scrollsNow = () =>
    [document.scrollingElement, ...document.querySelectorAll("*")]
      .filter((e) => e && (e.scrollTop || e.scrollLeft))
      .map((e) => `${e.scrollTop},${e.scrollLeft}`)
      .join(";");
}

/** Runs in the page: did anything change since radarMark()? */
export function radarChanged() {
  const state = window.__radarTap;
  return !state || state.changes > 0 || location.href !== state.url;
}

/** Runs in the page: what the tap did. New sheets are measured against the viewport and marked for a scoped scan. */
export function radarObserve(id) {
  const state = window.__radarTap;
  if (!state) return { navigated: true };
  const W = document.documentElement.clientWidth;
  const H = window.innerHeight;
  const R = window.__radar;
  const el = document.querySelector(`[data-radar-id="${id}"]`);
  const on = (name) => el?.getAttribute(name);
  const sheets = [];
  let n = 0;
  for (const d of document.querySelectorAll(
    'dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"]',
  )) {
    const r = d.getBoundingClientRect();
    if (state.dialogs.has(d) || r.width < 1 || r.height < 1) continue;
    // The sheet's panel: its largest opaque box (the dialog itself may be a full-screen scrim).
    let panel = d;
    let best = 0;
    for (const c of [
      d,
      ...d.querySelectorAll(":scope > *, :scope > * > *, :scope > * > * > *"),
    ]) {
      const bg = R.parseColor(getComputedStyle(c).backgroundColor);
      const cr = c.getBoundingClientRect();
      if (bg && bg[3] > 0.9 && cr.width * cr.height > best) {
        best = cr.width * cr.height;
        panel = c;
      }
    }
    const p = panel.getBoundingClientRect();
    let scrolls = false;
    for (let q = panel; q && !scrolls; q = q === d ? null : q.parentElement)
      scrolls =
        /auto|scroll/.test(getComputedStyle(q).overflowY) &&
        q.scrollHeight > q.clientHeight + 1;
    const off = [];
    if (p.left < -2) off.push(`${Math.round(-p.left)} px past the left edge`);
    if (p.right > W + 2)
      off.push(`${Math.round(p.right - W)} px past the right edge`);
    if (p.top < -2) off.push(`${Math.round(-p.top)} px above the top`);
    if (p.top >= H - 8) off.push("below the bottom of the screen");
    else if (p.bottom > H + 2 && !scrolls)
      off.push(
        `${Math.round(p.bottom - H)} px below the bottom, and it does not scroll`,
      );
    d.setAttribute("data-radar-scope", String(++n));
    sheets.push({
      scope: String(n),
      selector: R.pathOf(panel),
      label: R.labelOf(d, 40),
      off,
    });
  }
  const active = document.activeElement;
  return {
    changes: state.changes,
    url:
      location.href !== state.url
        ? location.pathname + location.search + location.hash
        : null,
    scrolled: state.scrollsNow() !== state.scrolls,
    focused:
      active !== state.active &&
      active !== el &&
      active !== document.body &&
      !!active?.matches?.('input, textarea, select, [contenteditable="true"]'),
    checked:
      [...document.querySelectorAll("input")]
        .map((i) => `${i.checked}`)
        .join("") !== state.checked,
    contentChanged: state.outsideNow() !== state.outside,
    selectedNow:
      on("aria-selected") === "true" ||
      on("aria-pressed") === "true" ||
      on("aria-checked") === "true" ||
      (on("aria-current") !== null &&
        on("aria-current") !== undefined &&
        on("aria-current") !== "false"),
    sheets,
  };
}

/** Which controls to tap: safe ones, one or two of each repeated control (every tab), at most `cap` a page. */
export function chooseTaps(targets, cap = 40) {
  const per = new Map();
  const chosen = [];
  const skipped = { risky: 0, leaves: 0, repeat: 0, cap: 0 };
  for (const target of targets) {
    if (target.skip) {
      skipped[target.skip]++;
      continue;
    }
    const seen = per.get(target.selector) ?? 0;
    if (seen >= (target.tabLike ? 12 : 2)) {
      skipped.repeat++;
      continue;
    }
    if (chosen.length >= cap) {
      skipped.cap++;
      continue;
    }
    per.set(target.selector, seen + 1);
    chosen.push(target);
  }
  return { chosen, skipped };
}

/** The same control after a reload: same path, label and place among equals. */
export const sameTarget = (a, b) =>
  a.selector === b.selector && a.label === b.label && a.index === b.index;

// ---------------------------------------------------------------------------------------------------------------
// Findings, groups and the report.

export const SEVERITY = { high: 3, medium: 2, low: 1 };
const worst = (a, b) => ((SEVERITY[a] ?? 0) >= (SEVERITY[b] ?? 0) ? a : b);

/** An error message without the parts that change from run to run (ports, ids, numbers, query strings). */
export const normalizeMessage = (text) =>
  scrub(String(text ?? ""))
    .replace(/https?:\/\/127\.0\.0\.1:\d+/g, "")
    .replace(/\?[^\s"')]*/g, "")
    .replace(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
      "<id>",
    )
    .replace(/\b\d+(\.\d+)?\b/g, "#")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 160);

/** A finding's stable key: check, page and element path (or message). Width, scale and theme go to `where`. */
export const findingKey = (f) => `${f.check} | ${f.page} | ${f.selector}`;

/** Short, stable ids for files and markers. */
export const shortId = (text, length = 10) =>
  createHash("sha1").update(text).digest("hex").slice(0, length);

/** One finding per key, with every state it shows in, its worst severity and the first crop. */
export function dedupe(raw) {
  const byKey = new Map();
  for (const f of raw) {
    const key = findingKey(f);
    const known = byKey.get(key);
    const where = f.state ? [f.state] : [];
    if (!known) {
      byKey.set(key, { ...f, key, id: shortId(key), where, count: 1 });
      continue;
    }
    known.count++;
    for (const w of where) if (!known.where.includes(w)) known.where.push(w);
    known.severity = worst(known.severity, f.severity);
    known.crop ??= f.crop;
  }
  return [...byKey.values()];
}

/** The component of an element path: its nearest CSS-module part, and the element itself. */
export function componentOf(selector) {
  const parts = String(selector).split(" > ");
  const own = parts.at(-1);
  if (own.includes("__")) return own;
  const module = [...parts].reverse().find((part) => part.includes("__"));
  return module ? `${module} … ${own}` : own;
}

/**
 * The root cause a finding belongs to: the same component (or colour pair, or message) on any page is one group.
 * Faint text groups by its colour pair (one design token everywhere); errors by their message; overlaps by both
 * components; a page that scrolls sideways with no element to blame is its own group.
 */
export function groupKeyOf(f) {
  switch (f.check) {
    case "contrast":
      return `contrast | ${f.colors}`;
    case "console-error":
    case "page-error":
    case "request-failed":
    case "tap-error":
      return `${f.check} | ${f.message ?? f.selector}`;
    case "overflow-page":
      // Per page: a key with the page's width in it churned when the width moved by 3 px (first nightly).
      return `overflow-page | ${f.page}`;
    case "overlap":
      return `overlap | ${String(f.selector)
        .split(" ⟂ ")
        .map(componentOf)
        .sort()
        .join(" ⟂ ")}`;
    case "overflow-element":
    case "tap-target":
    case "text-spill":
    case "centred-card":
      // Siblings of one component spill or shrink together: one CSS module, one group.
      return `${f.check} | ${moduleOf(f.selector) ?? componentOf(f.selector)}`;
    default:
      return `${f.check} | ${componentOf(f.selector)}`;
  }
}

/** The CSS module an element path ends in ("coaching" for ….coaching__compare), or null. */
export function moduleOf(selector) {
  const parts = String(selector).split(" > ").reverse();
  for (const part of parts) {
    const found = /\.([\w-]+?)__[\w-]+/.exec(part);
    if (found) return found[1];
  }
  return null;
}

/** Groups, the worst first: severity, then how many pages, then how many states. */
export function groupFindings(findings) {
  const groups = new Map();
  for (const f of findings) {
    const key = groupKeyOf(f);
    let g = groups.get(key);
    if (!g)
      groups.set(
        key,
        (g = {
          id: shortId(key, 12),
          key,
          check: f.check,
          severity: f.severity,
          findings: [],
        }),
      );
    g.findings.push(f);
    g.severity = worst(g.severity, f.severity);
  }
  return [...groups.values()]
    .map((g) => {
      const pages = [...new Set(g.findings.map((f) => f.page))];
      const states = new Set(
        g.findings.flatMap((f) => f.where.map((w) => `${f.page} ${w}`)),
      ).size;
      return {
        ...g,
        pages,
        states,
        crop: g.findings.find((f) => f.crop)?.crop ?? null,
        score:
          (SEVERITY[g.severity] ?? 0) * 1000 +
          Math.min(pages.length, 40) * 20 +
          Math.min(states, 99),
      };
    })
    .sort((a, b) => b.score - a.score || a.key.localeCompare(b.key));
}

// What each check means, in the report's words.
export const CHECKS = {
  "overflow-element": "past the screen's edge",
  "overflow-page": "the page scrolls sideways",
  overlap: "drawn over each other",
  "clipped-label": "label cut short",
  "clipped-text": "text cut short (long data)",
  "text-spill": "text runs out of its control",
  "tap-target": "tap target under 44 px",
  contrast: "faint text",
  "centred-card": "narrow card centred on a phone",
  "label-wraps": "tab or chip label wraps",
  "tabs-clipped": "tab bar cut at the screen edge",
  "console-error": "console error",
  "page-error": "uncaught error",
  "request-failed": "failed request",
  "dead-tap": "tap does nothing",
  "tab-no-switch": "tab does not switch",
  "tap-blocked": "something covers the control",
  "tap-error": "error after a tap",
  "sheet-offscreen": "sheet opens off-screen",
};

// What the checks cannot tell (kept in every report, so a reader can discount the known kinds of false alarm).
export const CAVEATS = [
  "Fixtures have no API: a tap that would call one fails here (tap-error, request-failed on /v1) without being a bug in the app.",
  "Faint text is measured against the element's own and its parents' backgrounds; text over a picture, a gradient or a frosted bar is skipped, and text over a sibling (an absolute badge) may read wrong.",
  "Overlap compares text lines and controls in one layer (the page, a fixed or sticky bar, a dialog); a badge placed over its own icon on purpose shows up when the two are siblings.",
  "Tap targets count the element and an absolute ::before/::after that widens it; a parent row that takes the tap is not counted, so a small icon inside a big tappable row is still listed (low).",
  "A dead tap is nothing changing in the page, the address, scroll, focus or checkboxes within 1 s; a copy-to-clipboard with no toast is listed on purpose (no feedback).",
  "Centred cards need a visible box (background, border or shadow); a centred alert dialog is listed as low.",
  "A segmented switch (one of several pressed) may set a mode with no content of its own (a playback speed): when it lights up and nothing else changes it is a low tab-no-switch; real tabs (role tab) are high.",
  "Overlap is compared inside one scroller: content scrolled under a sheet's footer is by design and not compared.",
  "A wrapped label is a tab, segment or chip (by role, a pressed button, or its class) whose words of up to 32 characters run taller than 1.5 lines; a tab bar is cut when its last item ends past the screen edge (or a clip there) and no box around it scrolls sideways within the screen.",
];

// Every cell loses names (fixture people stay out of the report too) and anything that would break the table.
const cell = (text) => namesOut(text).replace(/\|/g, "\\|").replace(/\n/g, " ");

/** The run's report: counts by check, the top groups with crops, every group, the pages that failed. */
export function reportMarkdown(run, top = 15) {
  const { groups, pages = [], findings = [] } = run;
  const lines = ["### Bug radar", ""];
  const failed = pages.filter((p) => p.failed?.length);
  const crawled = pages.filter((p) => p.crawled).length;
  lines.push(
    `${findings.length} findings in ${groups.length} groups on ${pages.length} pages` +
      (run.source_sha
        ? ` for \`${String(run.source_sha).slice(0, 12)}\``
        : "") +
      `: 320, 360 and 390 px and 1280; 100% and 130% text (and the app's 130% zoom on phones); light and dark; ` +
      `taps on every safe control of ${crawled} pages.`,
    "",
    "| check | groups | findings | high | medium | low |",
    "|---|---|---|---|---|---|",
  );
  for (const check of Object.keys(CHECKS)) {
    const mine = findings.filter((f) => f.check === check);
    if (!mine.length) continue;
    const by = (sev) => mine.filter((f) => f.severity === sev).length;
    lines.push(
      `| ${check} (${CHECKS[check]}) | ${groups.filter((g) => g.check === check).length} | ${mine.length} | ${by("high")} | ${by("medium")} | ${by("low")} |`,
    );
  }
  lines.push("", `#### Top ${Math.min(top, groups.length)} groups`, "");
  lines.push(
    "| # | severity | check | component | pages | states | example | crop |",
    "|---|---|---|---|---|---|---|---|",
  );
  groups.slice(0, top).forEach((g, i) => {
    const example = g.findings[0];
    lines.push(
      `| ${i + 1} | ${g.severity} | ${g.check} | \`${cell(g.key.split(" | ").slice(1).join(" | ")).slice(0, 90)}\` | ${g.pages.length} | ${g.states} | ${cell(example.label).slice(0, 40)}: ${cell(example.detail).slice(0, 80)} | ${g.crop ? `![](${g.crop})` : ""} |`,
    );
  });
  lines.push("", "#### Every group", "");
  for (const g of groups) {
    lines.push(
      `- **${g.severity}** \`radar:${g.id}\` ${g.check}: \`${cell(g.key.split(" | ").slice(1).join(" | ")).slice(0, 140)}\``,
    );
    for (const f of g.findings.slice(0, 4))
      lines.push(
        `  - ${f.page}${f.context ? ` (${f.context})` : ""}: ${cell(f.label).slice(0, 50)} — ${cell(f.detail).slice(0, 120)} [${f.where.slice(0, 3).join("; ")}${f.where.length > 3 ? `; +${f.where.length - 3}` : ""}]`,
      );
    if (g.findings.length > 4)
      lines.push(`  - … ${g.findings.length - 4} more pages or elements`);
  }
  if (failed.length) {
    lines.push("", "#### Pages that could not be checked everywhere", "");
    for (const p of failed)
      lines.push(
        `- ${p.key} (${p.path}): ${cell(p.failed[0]).slice(0, 160)}${p.failed.length > 1 ? ` (+${p.failed.length - 1})` : ""}`,
      );
  }
  lines.push(
    "",
    "#### What the checks cannot tell",
    "",
    ...CAVEATS.map((c) => `- ${c}`),
  );
  return lines.join("\n") + "\n";
}
