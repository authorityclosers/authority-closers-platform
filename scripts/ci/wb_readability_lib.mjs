// The Readability Gate's logic (wb_readability.mjs; owner, 18 Nov 2026: "How come there are bugs that are just
// visible?" then "Yes, start stage 1"; plan: QA system research 18 Nov, sections 4.4 and 6, steps 3a, 4a and 5a).
// One gate from the checks that already existed apart, run on the worst states a person really uses:
// - the bug radar's scan (wb_radar_lib.mjs): sideways overflow, things drawn over each other, cut labels and text,
//   small tap targets, faint text, wrapped tabs;
// - the phone overlap check's scan (wb_overlap_lib.mjs): text running into text, text cut with no ellipsis;
// - the contrast scan (wb_contrast_lib.mjs, written by the dark-mode worker): text and icons against what is
//   really painted under them, WCAG AA, in light and dark;
// - axe-core's serious and critical rules, with its tap-size rule switched on;
// - and the few checks none of them had (extraScan below): junk on screen ("undefined", "NaN", "[object Object]",
//   "Invalid Date", a missing-glyph box), tiny text, a control with something else drawn over its centre, a control
//   that cannot be reached, and a page that drew nothing.
// Every screen runs twice in each state: as its fixture is, and with long real-shaped data (stressInit below: long
// names, long stage labels, crore amounts, 100%, Devanagari), since real names and stages are longer than a
// fixture's. All data is fictional. A finding keeps its element's tag and class, never the text on screen.
//
// It blocks on what is new: today's findings are the baseline (wb-readability-baseline.json), so the gate starts
// green and fails only when a state gains a finding it did not have. A baseline finding that is gone is listed, so
// the baseline can be tightened.

/** The four corner states (research 4.3): the worst phone state, the plain phone, the laptop light and dark. */
export const CORNERS = [
  { key: "360 dark 130%", width: 360, height: 780, theme: "dark", scale: 1.3, phone: true },
  { key: "360 light 100%", width: 360, height: 780, theme: "light", scale: 1, phone: true },
  { key: "1280 light", width: 1280, height: 800, theme: "light", scale: 1, phone: false },
  { key: "1280 dark", width: 1280, height: 800, theme: "dark", scale: 1, phone: false },
];

/** Each screen runs as its fixture is ("plain") and with long real-shaped data ("long"). */
export const VARIANTS = ["plain", "long"];

const FIRST_LEAD = "00000000-0000-4000-8000-000000000300";
// A fixture with no <main> of its own is ready when its first heading or button is drawn.
const HEADED = "h1, h2, button";

/** The top 20 screens, from the review fixtures (fictional data, no API origin, no credentials). */
export const SCREENS = [
  { key: "home", path: "/review-fixture/home", ready: "main" },
  { key: "leads-list", path: "/review-fixture/leads", ready: "[data-lead-row]", readyWide: "main" },
  {
    key: "leads-open",
    path: "/review-fixture/leads?tab=all&stage=open",
    ready: "[data-lead-row]",
    readyWide: "main",
  },
  {
    key: "lead-page",
    path: `/review-fixture/leads#lead=${FIRST_LEAD}`,
    ready: "[data-lead-page]",
    readyWide: "main",
  },
  {
    key: "lead-page-long-path",
    path: `/review-fixture/leads?path=long#lead=${FIRST_LEAD}`,
    ready: "[data-lead-page]",
    readyWide: "main",
  },
  { key: "calls", path: "/review-fixture/calls", ready: "main" },
  { key: "work-calls", path: "/review-fixture/work-calls", ready: "main" },
  { key: "reports", path: "/review-fixture/reports", ready: "main" },
  { key: "report", path: "/review-fixture/report", ready: "[data-synthetic-report]" },
  { key: "report-coaching", path: "/review-fixture/report/coaching", ready: "main" },
  { key: "chats", path: "/review-fixture/chats", ready: "main" },
  { key: "growth", path: "/review-fixture/growth", ready: "main" },
  { key: "insights", path: "/review-fixture/insights", ready: HEADED },
  { key: "coaching", path: "/review-fixture/coaching", ready: HEADED },
  { key: "ask-dipak", path: "/review-fixture/ask-dipak", ready: "main" },
  { key: "settings", path: "/review-fixture/settings", ready: "main" },
  { key: "notifications", path: "/review-fixture/notifications", ready: "main" },
  { key: "alerts", path: "/review-fixture/alerts", ready: "main" },
  { key: "upload", path: "/review-fixture/upload", ready: "main" },
  { key: "sign-in", path: "/review-fixture/sign-in", ready: HEADED },
];

/** Every load the gate makes: screen x corner x variant. */
export function loads(screens = SCREENS) {
  return screens.flatMap((screen) =>
    CORNERS.flatMap((corner) => VARIANTS.map((variant) => ({ screen, corner, variant }))),
  );
}

/** Where a finding lives: one screen, data variant and state. */
export const cellOf = (load) => `${load.screen.key} | ${load.variant} | ${load.corner.key}`;

/** A class name without the build's hash ("leads-module__Ab12Cd__row" reads "leads:row"). */
export function plainClass(name) {
  return String(name ?? "")
    .replace(/-module__[A-Za-z0-9_-]{4,10}__/g, ":")
    .replace(/__[A-Za-z0-9_-]{5,8}$/, "")
    .slice(0, 40);
}

/** A selector as the baseline keeps it: hashes out, positions out, at most 120 characters. */
export function plainSelector(selector) {
  return String(selector ?? "")
    .split(/\s*>\s*|\s+/)
    .filter(Boolean)
    .map((part) =>
      part
        .replace(/-module__[A-Za-z0-9_-]{4,10}__/g, ":")
        // React's generated ids ("_r_0_", "_R_eatpesncflb_", ":r1:") differ from one render to the next.
        .replace(/#_[rR]_[A-Za-z0-9]*_|#\\?:[rR][A-Za-z0-9]*\\?:/g, "#:id:")
        .replace(/:nth-(child|of-type)\(\d+\)/g, "")
        .replace(/\[data-radar-[a-z]+="[^"]*"\]/g, "")
        // axe names an element by whichever attributes make it unique at that moment: the kit's tap reach
        // (data-reach) is added after load, so the same button was "[data-reach]" in one run and
        // "[type=button]" in the next (v1.88.0 cut, 19 Nov 2026). Neither says which element it is.
        .replace(/\[data-reach(="[^"]*")?\]|\[type="button"\]/g, ""),
    )
    .join(" > ")
    .slice(0, 120);
}

/** One finding's name inside its cell: the check and the element, never the text on screen. */
export const nameOf = (finding) =>
  finding.check === "page-error"
    ? `page-error | ${String(finding.selector).replace(/\s+/g, " ").slice(0, 80)}`
    : `${finding.check} | ${plainSelector(finding.selector)}`;

/** The findings of one load as sorted, unique names. */
export const namesOf = (findings) => [...new Set(findings.map(nameOf))].sort();

/**
 * What changed against the baseline. `found` and `baseline` map a cell to its names. A cell the run did not reach
 * (an error, or --only) is left alone: nothing in it counts as new or as gone.
 */
export function compare(found, baseline) {
  const fresh = [];
  const gone = [];
  for (const [cell, names] of Object.entries(found)) {
    const known = new Set(baseline[cell] ?? []);
    for (const name of names) if (!known.has(name)) fresh.push({ cell, name });
    const now = new Set(names);
    for (const name of known) if (!now.has(name)) gone.push({ cell, name });
  }
  return { fresh, gone };
}

/** Two runs of the same tree folded into one baseline: a finding either run saw is known. */
export function union(a, b) {
  const out = {};
  for (const cell of [...new Set([...Object.keys(a), ...Object.keys(b)])].sort())
    out[cell] = [...new Set([...(a[cell] ?? []), ...(b[cell] ?? [])])].sort();
  return out;
}

/**
 * A baseline from the rows of one or more recording runs: a finding any run saw is known. A load that could not
 * be measured in a run adds nothing from that run. Returns { cells, errors } (errors: the loads that failed).
 */
export function baselineFrom(runs) {
  let cells = {};
  const errors = [];
  for (const rows of runs) {
    const found = {};
    for (const row of rows) {
      if (row.error) errors.push(`${row.cell}: ${row.error}`);
      else found[row.cell] = row.names ?? [];
    }
    cells = union(cells, found);
  }
  return { cells, errors };
}

/** What each check means, in the report's words. The radar's own checks keep the radar's words. */
export const CHECKS = {
  "text-overlap": "text runs into other text",
  "text-cut": "text cut off with no ellipsis",
  "contrast-aa": "text or icon below WCAG AA",
  junk: "junk on screen (undefined, NaN, a missing-glyph box)",
  "tiny-text": "text under 11 px",
  covered: "something is drawn over the control's centre",
  "out-of-reach": "a control that cannot be scrolled into view",
  blank: "the page drew nothing",
  "page-error": "uncaught error",
};

/** Junk a person should never read. Whole words only; "null" only when it is all a piece of text says. */
export const JUNK = /\bundefined\b|\bNaN\b|\[object Object\]|Invalid Date|\uFFFD|\u25A1/;
export const isJunk = (text) => {
  const value = String(text ?? "").trim();
  return JUNK.test(value) || value === "null" || /[:=]\s*null$/.test(value);
};

// ---------------------------------------------------------------------------------------------------------------
// Long real-shaped data (step 4a). Fictional: no real person, company or number.

export const LONG = {
  people: [
    "Venkataraghavan Subramaniam Chidambaranathan",
    "Dr. Anuradha Lakshminarayanan Deshpande-Kulkarni",
    "श्रीमती अनुराधा लक्ष्मीनारायण देशपांडे-कुलकर्णी",
    "Mohammed Abdul Rahman Shaikh Inamdar-Pathan",
  ],
  companies: [
    "Shree Siddhivinayak Infrastructure & Developers Private Limited",
    "Sample Sahyadri Agro-Processing Co-operative Society (Fictional)",
  ],
  labelTail: " – Awaiting Family Decision After the Second Site Visit",
  place: "Thiruvananthapuram (Kazhakoottam Technopark Phase III)",
  source: "Meta Ads: Sunleaf Residences 2 & 3 BHK Diwali Festive Offer form (Marathi)",
  sentence:
    " Customer bolale ki दिवाळीनंतर पुन्हा कॉल करा, budget 1.25 crore tak ja sakta hai, lekin loan approval pending aahe.",
  amount: 123456789,
};

/** A small stable number from a string, so the same value always gets the same long stand-in. */
export function pick(text, count) {
  let sum = 0;
  for (const char of String(text)) sum = (sum * 31 + char.codePointAt(0)) % 9973;
  return sum % count;
}

/**
 * The long stand-in for one value of a fixture's JSON, by its key and shape; the value itself when it should stay
 * (ids, dates, links, enum words, phones, emails). Runs in the page on its own (stressInit passes it in whole).
 */
export function stressValue(key, value, L, pickOf) {
  const k = String(key).toLowerCase();
  if (typeof value === "number") {
    if (!Number.isFinite(value) || value <= 0) return value;
    if (/amount|revenue|worth|deal_value|target_value/.test(k)) return L.amount;
    if (/percent|pct/.test(k) && value <= 100) return 100;
    return value;
  }
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (text.length < 2 || text.length > 160) return value;
  // Not words a person reads: ids, enum keys, dates, links, phones, emails.
  if (/^[a-z0-9_.:\-/]+$/.test(text) || /^\d{4}-\d{2}-\d{2}/.test(text)) return value;
  if (/^(https?:|\/|#|\+?\d[\d\s-]{6,}$)/.test(text) || /@/.test(text)) return value;
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-/.test(text)) return value;
  if (/company|organi[sz]ation|workspace|business|firm|employer/.test(k))
    return L.companies[pickOf(text, L.companies.length)];
  if (/city|location|place|address/.test(k)) return L.place;
  if (/source|campaign|form/.test(k)) return L.source;
  const personKey =
    /(^|_)(name|display_name|full_name|owner|seller|person|contact|assignee|by|author|lead)(_name)?$/.test(k);
  const personShape = /^[\p{Lu}][\p{L}.'-]+(\s[\p{Lu}][\p{L}.'-]+){1,3}$/u.test(text);
  if (personKey && personShape) return L.people[pickOf(text, L.people.length)];
  if (/^(label|name|title|stage|stage_label|step_label|status_label|heading)$/.test(k) && text.length <= 40)
    return text + L.labelTail;
  if (/note|summary|message|interest|reason|description|body|text/.test(k) && /\s/.test(text))
    return text + L.sentence;
  return value;
}

/**
 * Runs in the page before any of its scripts. A review fixture answers the app's reads by replacing window.fetch;
 * this keeps a wrapper in that seat, so every JSON answer (the fixture's, whatever it is) comes back with long
 * real-shaped values. window.__stressed counts the values changed, so a screen whose data never passes through
 * fetch shows as 0 in the report.
 */
export function stressInit(L, valueOf, pickOf) {
  window.__stressed = 0;
  const walk = (data, key) => {
    if (Array.isArray(data)) return data.map((item) => walk(item, key));
    if (data && typeof data === "object") {
      const out = {};
      for (const [k, v] of Object.entries(data)) out[k] = walk(v, k);
      return out;
    }
    const next = valueOf(key ?? "", data, L, pickOf);
    if (next !== data) window.__stressed += 1;
    return next;
  };
  const wrap = (fn) =>
    async function stressed(input, init) {
      const response = await fn.call(this, input, init);
      try {
        if (!response || typeof response.json !== "function") return response;
        const type = response.headers?.get?.("content-type") ?? "application/json";
        if (!/json/i.test(type)) return response;
        if (typeof response.clone !== "function") {
          const read = response.json.bind(response);
          return Object.assign(Object.create(Object.getPrototypeOf(response)), response, {
            json: async () => walk(await read()),
          });
        }
        const data = walk(await response.clone().json());
        return new Response(JSON.stringify(data), {
          status: response.status,
          statusText: response.statusText,
          headers: response.headers,
        });
      } catch {
        return response;
      }
    };
  let seat = wrap(window.fetch);
  Object.defineProperty(window, "fetch", {
    configurable: true,
    get: () => seat,
    set: (fn) => {
      seat = typeof fn === "function" && fn.name !== "stressed" ? wrap(fn) : fn;
    },
  });
}

/**
 * Runs in the page once it has drawn, for the screens whose fixture keeps its data in the page (nothing to wrap).
 * The data a person reads there is made long where it stands: a person-shaped name becomes a long name, a rupee
 * amount a nine-digit one, a percentage 100%. Headings, buttons, tabs, labels and navigation are the app's own
 * words and stay. Returns how many pieces of text changed.
 */
export function stressDom(L, pickOf) {
  const person = /^[A-Z][a-z]{1,14}(?: [A-Z][a-z.]{1,14}){1,2}$/;
  const skip = "script, style, noscript, template, svg, button, nav, label, th, h1, h2, h3, a, [role='tab'], [role='button'], input, textarea, select, option";
  let changed = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node);
  for (const node of nodes) {
    const el = node.parentElement;
    const text = node.textContent;
    const plain = text.trim();
    if (!el || !plain || el.closest(skip)) continue;
    let next = text;
    if (person.test(plain)) next = text.replace(plain, L.people[pickOf(plain, L.people.length)]);
    else {
      next = next.replace(/₹\s?\d[\d,.]*(\s?(?:L|Cr|K|lakh|crore))?/g, "₹12,34,56,789");
      next = next.replace(/\b\d{1,2}(\.\d)?%/g, "100%");
    }
    if (next !== text) {
      node.textContent = next;
      changed += 1;
    }
  }
  window.__stressed = (window.__stressed ?? 0) + changed;
  return changed;
}

/** stressDom as one expression for page.evaluate. */
export const stressDomInPage = () => `(${stressDom.toString()})(${JSON.stringify(LONG)}, ${pick.toString()})`;

/** stressInit as one init script, its helpers passed in whole. */
export const stressScript = () =>
  `(${stressInit.toString()})(${JSON.stringify(LONG)}, ${stressValue.toString()}, ${pick.toString()});`;

// ---------------------------------------------------------------------------------------------------------------
// In the page: the checks the three older scans do not make.

/**
 * Runs in the page on its own. `scale` is the text scale the page is shown at (tiny text is judged at 100% only).
 * Returns { findings: [{check, selector, detail}], chars } with `chars` the visible text's length.
 */
export function extraScan(options, junkSource) {
  const junk = new RegExp(junkSource);
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const findings = [];
  const seen = new Set();
  const label = (el) => {
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/)[0] : "";
    return el.tagName.toLowerCase() + (cls ? `.${cls}` : "");
  };
  const path = (el) => {
    const out = [];
    for (let node = el; node && node !== document.body && out.length < 3; node = node.parentElement)
      out.unshift(label(node));
    return out.join(" > ");
  };
  const add = (check, el, detail) => {
    const selector = path(el);
    if (seen.has(`${check}|${selector}`)) return;
    seen.add(`${check}|${selector}`);
    findings.push({ check, selector, detail });
  };
  const shown = (el) =>
    typeof el.checkVisibility === "function"
      ? el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true })
      : getComputedStyle(el).visibility !== "hidden";

  const layerOf = (el) => {
    for (let at = el; at; at = at.parentElement) {
      const position = getComputedStyle(at).position;
      if (position === "fixed" || position === "sticky") return at;
    }
    return null;
  };

  // Junk and tiny text, from the text a person can see.
  let chars = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.replace(/\s+/g, " ").trim();
    if (!text) continue;
    const el = node.parentElement;
    if (!el || el.closest("script, style, noscript, template, svg") || !shown(el)) continue;
    const box = el.getBoundingClientRect();
    if (box.width <= 2 || box.height <= 2) continue; // for screen readers only
    chars += text.length;
    if (junk.test(text) || text === "null" || /[:=]\s*null$/.test(text))
      add("junk", el, (text.match(junk)?.[0] ?? "null").slice(0, 20));
    if (options.scale === 1) {
      const px = parseFloat(getComputedStyle(el).fontSize);
      if (px > 0 && px < 10.95) add("tiny-text", el, `${Math.round(px * 10) / 10} px`);
    }
  }

  // A control with something else drawn over its centre, or one that cannot be reached.
  const controls = document.querySelectorAll(
    "button, a[href], [role='button'], [role='tab'], [role='link'], [role='switch'], input:not([type='hidden']), select, textarea",
  );
  const width = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  for (const el of controls) {
    if (!shown(el) || el.closest("[inert], [aria-hidden='true']")) continue;
    if (el.disabled || el.getAttribute("aria-disabled") === "true") continue;
    const style = getComputedStyle(el);
    if (style.pointerEvents === "none") continue;
    const box = el.getBoundingClientRect();
    if (box.width < 8 || box.height < 8) continue; // a hidden native input behind its drawn control
    if (box.right <= 0 || (box.left >= vw && box.left >= width - 1)) {
      // Past the edge with nothing that scrolls to it.
      let scrolls = false;
      for (let node = el.parentElement; node; node = node.parentElement) {
        const s = getComputedStyle(node);
        if (/(auto|scroll)/.test(s.overflowX) && node.scrollWidth > node.clientWidth + 1) scrolls = true;
      }
      if (!scrolls) add("out-of-reach", el, `left ${Math.round(box.left)} of ${vw}`);
      continue;
    }
    const x = box.left + box.width / 2;
    const y = box.top + box.height / 2;
    if (x < 0 || x >= vw || y < 0 || y >= vh) continue; // below the fold: reached by scrolling, judged when seen
    const top = document.elementFromPoint(x, y);
    if (!top || top === el || el.contains(top) || top.contains(el)) continue;
    // Its own label, or a drawn stand-in beside a native input in the same label, takes the tap for it.
    const own = el.closest("label");
    if (own && own.contains(top)) continue;
    if (top.closest("label")?.control === el) continue;
    // Page content scrolled under a fixed or sticky bar is by design (it scrolls clear). What counts: two things
    // in the same layer, or a fixed thing over another fixed thing (a notice card on the sticky action).
    const mine = layerOf(el);
    const theirs = layerOf(top);
    if (mine === null && theirs !== null) continue;
    // A sheet or dialog over the page is a different layer by design: its backdrop is not "covering" a control.
    if (top.closest("dialog, [role='dialog'], [aria-modal='true']") && !el.closest("dialog, [role='dialog'], [aria-modal='true']"))
      continue;
    add("covered", el, `under ${label(top)}`);
  }
  if (chars < 20) findings.push({ check: "blank", selector: "body", detail: `${chars} characters` });
  return { findings, chars };
}

/** extraScan as one expression for page.evaluate. */
export const extraInPage = (scale) =>
  `(${extraScan.toString()})(${JSON.stringify({ scale })}, ${JSON.stringify(JUNK.source)})`;

// ---------------------------------------------------------------------------------------------------------------
// The report.

/** The run's report: the verdict, what is new (the reason it fails), what is gone, and counts by check. */
export function reportMarkdown({ rows, fresh, gone, recorded, baselineCells }) {
  const errors = rows.filter((row) => row.error);
  const byCheck = new Map();
  for (const row of rows)
    for (const name of row.names ?? []) {
      const check = name.split(" | ")[0];
      byCheck.set(check, (byCheck.get(check) ?? 0) + 1);
    }
  const total = [...byCheck.values()].reduce((a, b) => a + b, 0);
  const unstressed = [...new Set(rows.filter((r) => r.variant === "long" && r.stressed === 0).map((r) => r.screen))];
  const thin = [...new Set(rows.filter((r) => !r.error && r.chars < 200).map((r) => r.screen))];
  const lines = ["## Readability Gate", ""];
  lines.push(
    `${new Set(rows.map((r) => r.screen)).size} screens x ${CORNERS.length} corner states x plain and long data = ${rows.length} loads; ${total} findings in all.`,
    "",
  );
  if (recorded)
    lines.push("No baseline yet: this run only records. Nothing blocks until wb-readability-baseline.json is committed.", "");
  else if (!fresh.length && !errors.length)
    lines.push(`**Green.** Nothing new against the baseline (${baselineCells} states known).`, "");
  else
    lines.push(
      `**Red.** ${fresh.length} new finding${fresh.length === 1 ? "" : "s"}${errors.length ? `, ${errors.length} load${errors.length === 1 ? "" : "s"} that could not be measured` : ""}.`,
      "",
    );
  if (fresh.length) {
    lines.push("### New (these block)", "", "| screen, data, state | check | element |", "| --- | --- | --- |");
    for (const { cell, name } of fresh.slice(0, 80)) {
      const [check, ...rest] = name.split(" | ");
      lines.push(`| ${cell.replace(/ \| /g, ", ")} | ${check} | \`${rest.join(" | ").replace(/\|/g, "\\|")}\` |`);
    }
    if (fresh.length > 80) lines.push(`| ... | | ${fresh.length - 80} more in readability.json |`);
    lines.push("");
  }
  if (errors.length) {
    lines.push("### Could not measure", "");
    for (const row of errors.slice(0, 20)) lines.push(`- ${row.cell}: ${row.error}`);
    lines.push("");
  }
  if (gone.length)
    lines.push(
      `### Gone (${gone.length})`,
      "",
      "In the baseline, not seen now. If a fix removed them, tighten the baseline: `node scripts/ci/wb_readability.mjs <out> --write-baseline --prune`.",
      "",
    );
  lines.push("### Findings by check", "", "| check | count |", "| --- | --- |");
  for (const [check, count] of [...byCheck].sort((a, b) => b[1] - a[1])) lines.push(`| ${check} | ${count} |`);
  lines.push("");
  if (unstressed.length)
    lines.push(`Long data did not reach: ${unstressed.join(", ")} (no name, amount or percentage on them).`, "");
  if (thin.length)
    lines.push(`Thin screens (under 200 characters drawn, so little was checked): ${thin.join(", ")}.`, "");
  return lines.join("\n");
}
