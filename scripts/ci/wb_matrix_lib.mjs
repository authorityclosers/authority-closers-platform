// The visual test matrix's pure parts (`wb-ci --matrix`; owner via the orchestrator, 25 Oct 2026: "check symmetry
// and alignment numerically, not by eye", across screen ratios and font scales). wb_matrix.mjs runs them in Chromium
// on a GitHub-hosted runner; nothing here needs a browser, so the tests run with plain `node --test`.
//
// Font scale, two ways, because people meet both:
// - app: the Android app zooms the page by the phone's font scale, clamped to 1-1.2 (in-app.ts), so 130% on a
//   360 px phone leaves 300 CSS px;
// - text: a browser's text scaling: every font size and px line height times the scale, the layout as it was.

export const SIZES = [
  { label: "320x640", width: 320, height: 640 },
  { label: "360x640", width: 360, height: 640 },
  { label: "360x800", width: 360, height: 800 },
  { label: "390x844", width: 390, height: 844 },
  { label: "412x915", width: 412, height: 915 },
  { label: "430x932", width: 430, height: 932 },
  { label: "768x1024", width: 768, height: 1024 },
];

// 85, 100, 115 and 130%: 100% once, the others as browser text scaling, and 115 and 130 as the app zooms them
// (the app clamps 85% to 100%, so it would repeat 100%).
export const SCALES = [
  { scale: 1, mode: "app" },
  { scale: 0.85, mode: "text" },
  { scale: 1.15, mode: "text" },
  { scale: 1.3, mode: "text" },
  { scale: 1.15, mode: "app" },
  { scale: 1.3, mode: "app" },
];

export const THEMES = ["light", "dark"];

// Review fixtures (fictional data, no API), each with the taps that reach its state.
const firstLead = [
  { click: ":is(button, a)[data-row-key], [data-row-key] :is(button, a)" },
  { wait: '[aria-label="History"]' },
];
const asTable = [
  { click: 'button[title="Show as a table"]', optional: true },
  { wait: 'table[aria-label="Leads"]' },
];
export const SCREENS = {
  "leads-desk": { path: "/review-fixture/leads" },
  "leads-all": { path: "/review-fixture/leads?tab=all" },
  "leads-table": { path: "/review-fixture/leads?tab=all", steps: asTable },
  "leads-table-open": {
    path: "/review-fixture/leads?tab=all",
    steps: [
      ...asTable,
      { click: 'button[aria-label^="Show more about"]', optional: true },
    ],
  },
  "leads-board": { path: "/review-fixture/leads?tab=board" },
  "leads-work": { path: "/review-fixture/leads?tab=work" },
  "lead-sheet": {
    path: "/review-fixture/leads?tab=all&hub=1",
    steps: firstLead,
  },
  "message-sheet": {
    path: "/review-fixture/leads?tab=all&hub=1",
    steps: [
      ...firstLead,
      { click: 'button[aria-label="WhatsApp"]' },
      // The composer's channel switch: "Ready messages" is empty (hidden) without templates.
      { wait: 'dialog[open] [aria-label="Send with"]' },
    ],
  },
  home: { path: "/review-fixture/home" },
  // Fictional call analysis numbers: the sliding figures and the attention dot.
  "home-analysis": { path: "/review-fixture/home?analysis=1" },
  "home-mine": { path: "/review-fixture/home?view=mine&analysis=1" },
};

/** The screens a request asks for: screen names or fixture paths ("/review-fixture/..."); none means all. */
export function pickScreens(routes = []) {
  if (!routes.length) return Object.entries(SCREENS);
  return routes.map((route) => {
    if (SCREENS[route]) return [route, SCREENS[route]];
    if (!route.startsWith("/"))
      throw new Error(`unknown matrix screen ${route}`);
    const key =
      route
        .replace(/^\/+/, "")
        .replace(/[^a-zA-Z0-9]+/g, "-")
        .replace(/^-|-$/g, "")
        .slice(0, 60) || "root";
    return [key, { path: route }];
  });
}

/** Every state: 7 sizes x 6 scale variants x 2 themes = 84 per screen. */
export function states() {
  return SIZES.flatMap((size) =>
    SCALES.flatMap((variant) =>
      THEMES.map((theme) => ({ ...size, ...variant, theme })),
    ),
  );
}

/** The app's zoom for a state: its font scale clamped to 1-1.2; text scaling keeps the page at 1. */
export const zoomOf = (state) =>
  state.mode === "app" ? Math.min(Math.max(state.scale, 1), 1.2) : 1;

/** The CSS viewport for a state: the phone's size over the app's zoom. */
export function viewportOf(state) {
  const zoom = zoomOf(state);
  return {
    width: Math.round(state.width / zoom),
    height: Math.round(state.height / zoom),
  };
}

export const tagOf = (key, state) =>
  `${key} ${state.label} ${Math.round(state.scale * 100)}% ${state.mode} ${state.theme}`;

/** The states on a screen's contact sheet: 100% light, 130% both ways light, 100% dark, at every size. */
export const onSheet = (state) =>
  (state.theme === "light" && (state.scale === 1 || state.scale === 1.3)) ||
  (state.theme === "dark" && state.scale === 1);

/** Runs in the page: what is wrong with this state, in numbers. */
export function measure() {
  const W = document.documentElement.clientWidth;
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    return (
      s.visibility !== "hidden" &&
      s.display !== "none" &&
      Number(s.opacity) > 0.01
    );
  };
  const scrolls = (el) => {
    for (
      let p = el.parentElement;
      p && p !== document.body;
      p = p.parentElement
    )
      if (getComputedStyle(p).overflowX !== "visible") return true;
    return false;
  };
  const name = (el) =>
    (el.getAttribute("aria-label") || el.textContent || "")
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 40) ||
    `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0].slice(0, 30)}`;
  const ownText = (el) =>
    [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  const all = [...document.querySelectorAll("body *")].filter((el) => {
    if (!visible(el)) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  });
  const result = {
    overflow: document.documentElement.scrollWidth > W + 1,
    wide: all
      .filter((el) => el.getBoundingClientRect().right > W + 1 && !scrolls(el))
      .slice(0, 8)
      .map(
        (el) =>
          `${name(el)} (+${Math.round(el.getBoundingClientRect().right - W)})`,
      ),
    // Boxes that scroll sideways inside the page: a wide table, or a deliberate chip strip.
    sideways: all
      .filter((el) => {
        const ox = getComputedStyle(el).overflowX;
        return (
          (ox === "auto" || ox === "scroll") &&
          el.scrollWidth > el.clientWidth + 1
        );
      })
      .map((el) => `${name(el)} (${el.scrollWidth} in ${el.clientWidth})`),
    clipped: all
      .filter((el) => {
        if (!ownText(el)) return false;
        const s = getComputedStyle(el);
        const hides =
          s.overflowX !== "visible" || s.textOverflow === "ellipsis";
        const clamp = s.webkitLineClamp && s.webkitLineClamp !== "none";
        return (
          (hides && el.scrollWidth > el.clientWidth + 1) ||
          (clamp && el.scrollHeight > el.clientHeight + 1)
        );
      })
      .map(name),
  };
  // Text running visibly out of its button, chip or link (text cut by an ellipsis or a clip counts as clipped).
  const clips = (from, to) => {
    for (let p = from; p; p = p.parentElement) {
      if (getComputedStyle(p).overflowX !== "visible") return true;
      if (p === to) return false;
    }
    return false;
  };
  const spill = new Set();
  for (const el of all)
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      const box = el.closest('button, a, [role="button"], [role="tab"], label');
      if (!box || clips(el, box)) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      const t = range.getBoundingClientRect();
      const b = box.getBoundingClientRect();
      if (
        t.width &&
        (t.right > b.right + 1 ||
          t.left < b.left - 1 ||
          t.bottom > b.bottom + 1)
      )
        spill.add(
          `${name(box)} (text ${Math.round(t.width)} in ${Math.round(b.width)})`,
        );
    }
  result.spill = [...spill];
  result.small = all
    .filter((el) =>
      el.matches(
        'a[href], button, [role="button"], [role="tab"], input:not([type="hidden"]), select, textarea',
      ),
    )
    .filter((el) => !el.closest("[aria-hidden='true']"))
    .map((el) => [el, el.getBoundingClientRect()])
    .filter(([, r]) => r.width < 44 || r.height < 44)
    .map(
      ([el, r]) => `${name(el)} ${Math.round(r.width)}x${Math.round(r.height)}`,
    );
  result.tiny = [
    ...new Set(
      all
        .filter(
          (el) => ownText(el) && parseFloat(getComputedStyle(el).fontSize) < 11,
        )
        .map((el) => `${name(el)} ${getComputedStyle(el).fontSize}`),
    ),
  ];
  // Buttons side by side on one line with different heights, or off-centre: misaligned edges.
  result.uneven = [];
  for (const row of all) {
    const s = getComputedStyle(row);
    if (!(s.display.includes("flex") && !s.flexDirection.startsWith("column")))
      continue;
    const boxes = [...row.children]
      .filter((el) => visible(el) && el.matches('button, a, [role="button"]'))
      .map((el) => el.getBoundingClientRect());
    if (boxes.length < 2) continue;
    const top = Math.min(...boxes.map((b) => b.top));
    const line = boxes.filter((b) => b.top < top + 8);
    if (line.length < 2) continue;
    const heights = line.map((b) => b.height);
    const centres = line.map((b) => b.top + b.height / 2);
    const dc = Math.max(...centres) - Math.min(...centres);
    if (Math.max(...heights) - Math.min(...heights) > 1 || dc > 1.5)
      result.uneven.push(
        `${name(row)}: heights ${heights.map(Math.round).join("/")}, centres off ${dc.toFixed(1)}`,
      );
  }
  // Groups the code marks as equal (an action row): every box the same size.
  result.unequal = [...document.querySelectorAll("[data-sx-equal]")]
    .filter(visible)
    .map((group) => {
      const boxes = [...group.children]
        .filter(visible)
        .map((el) => el.getBoundingClientRect());
      if (boxes.length < 2) return null;
      const widths = boxes.map((b) => Math.round(b.width));
      const heights = boxes.map((b) => Math.round(b.height));
      return Math.max(...widths) - Math.min(...widths) > 1 ||
        Math.max(...heights) - Math.min(...heights) > 1
        ? `${group.getAttribute("data-sx-equal")}: widths ${widths.join("/")}, heights ${heights.join("/")}`
        : null;
    })
    .filter(Boolean);
  return result;
}

/** Runs in the page: browser text scaling, every font size and px line height times `factor`. */
export function textZoom(factor) {
  const els = [...document.querySelectorAll("body, body *")];
  const before = els.map((el) => {
    const s = getComputedStyle(el);
    return [
      parseFloat(s.fontSize),
      s.lineHeight.endsWith("px") ? parseFloat(s.lineHeight) : null,
    ];
  });
  els.forEach((el, i) => {
    const [size, line] = before[i];
    el.style.setProperty("font-size", `${size * factor}px`, "important");
    if (line !== null)
      el.style.setProperty("line-height", `${line * factor}px`, "important");
  });
}

// What the report counts, the worst first. "sideways" is listed but not a failure: a stage-tab strip scrolls on
// purpose; a table must not.
export const FIELDS = [
  "overflow",
  "wide",
  "spill",
  "unequal",
  "uneven",
  "small",
  "clipped",
  "tiny",
  "sideways",
  "errors",
];

const count = (row, field) =>
  Array.isArray(row[field]) ? row[field].length : row[field] ? 1 : 0;

/** The report: per screen, how many states had each problem, and the first examples with the state that shows them. */
export function report(rows, sourceSha = null) {
  const keys = [...new Set(rows.map((row) => row.key))];
  const lines = [
    "### Visual matrix",
    "",
    `${rows.length} states on ${keys.length} screens (7 sizes x 85/100/115/130% x light and dark)` +
      (sourceSha ? ` for \`${String(sourceSha).slice(0, 12)}\`` : "") +
      ". Each cell: states with the problem, of the screen's states.",
    "",
    `| screen | failed | ${FIELDS.join(" | ")} |`,
    `|---|---|${FIELDS.map(() => "---").join("|")}|`,
  ];
  for (const key of keys) {
    const mine = rows.filter((row) => row.key === key);
    const failed = mine.filter((row) => row.failed).length;
    lines.push(
      `| ${key} | ${failed} | ${FIELDS.map((field) => mine.filter((row) => count(row, field)).length).join(" | ")} |`,
    );
  }
  for (const key of keys) {
    const mine = rows.filter((row) => row.key === key);
    const details = [];
    const failed = mine.find((row) => row.failed);
    if (failed) details.push(`- failed: ${failed.failed} [${failed.tag}]`);
    for (const field of FIELDS) {
      const seen = new Map();
      for (const row of mine)
        for (const item of Array.isArray(row[field])
          ? row[field]
          : row[field]
            ? [String(row[field])]
            : [])
          if (!seen.has(item)) seen.set(item, row.tag);
      if (seen.size)
        details.push(
          `- ${field}: ${[...seen.entries()]
            .slice(0, 5)
            .map(([item, tag]) => `"${item}" [${tag}]`)
            .join("; ")}`,
        );
    }
    if (details.length) lines.push("", `#### ${key}`, "", ...details);
  }
  return lines.join("\n") + "\n";
}
