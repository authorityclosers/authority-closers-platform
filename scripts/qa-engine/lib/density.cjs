// Density probe (orchestrator, 2 Nov 2026, features frozen after the owner's "cluttered on a phone"): a read-only measurement of how much is on a screen, the "before" baseline the later "after" is compared with.
// Screens: seller Home, /leads (To Call), the lead page (?lead=), the after-call sheet, /analysis/calls. People: priya and karan (a second seller; the owner dashboard needs an owner session, which the robot does not have).
// Variants (light): 360x800, 390x844, and 360x800 with the root font at 1.3x. Per run, above the fold and on the full page: interactive controls, chips and badges, text lines, cards and boxes, notices and banners,
// distinct colours; a fold screenshot and a full-page screenshot. Writes the table (density-table.md, density.json, density.csv) and the pictures to OUT. Fictional data only; every write is refused; nothing is saved.
// Run on ac: node lib/density.cjs   (QA_DENSITY_OUT overrides the folder)
const fs = require("fs");
const path = require("path");
const session = require("./session.cjs");
const cfg = require("./config.cjs");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const OUT = process.env.QA_DENSITY_OUT || "/home/acdev/qa-engine/out/density-20261102/";
const POOL = path.join(cfg.STATE, "qa-pool.json");

// everything is counted inside the page, once for the first screen (top of the page, viewport height) and once for the whole page
function measure(vh) {
  const vw = document.documentElement.clientWidth;
  const visible = (e) => {
    if (!e.checkVisibility || !e.checkVisibility()) return false;
    const r = e.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2;
  };
  // a sheet (the lead page, the after-call question) is measured on its own: what lies behind it on the list is not part of it
  const dialogs = [...document.querySelectorAll("dialog[open],[role=dialog]")].filter(visible);
  const root = dialogs.length ? dialogs[dialogs.length - 1] : document.body;
  const scope = dialogs.length ? "dialog" : "page";
  const scrollHeight = scope === "dialog" ? Math.max(root.scrollHeight, Math.round(root.getBoundingClientRect().height)) : Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);
  const all = [...root.querySelectorAll("*")].filter((e) => !/^(SCRIPT|STYLE|NOSCRIPT|SVG|PATH|G|DEFS|LINK|META)$/i.test(e.tagName) && visible(e));
  const rectOf = (e) => e.getBoundingClientRect();
  const inFold = (r) => r.bottom > 0 && r.top < vh;
  const parse = (c) => {
    const m = /rgba?\(([^)]+)\)/.exec(c || "");
    if (!m) return null;
    const p = m[1].split(",").map((x) => parseFloat(x));
    return { r: Math.round(p[0]), g: Math.round(p[1]), b: Math.round(p[2]), a: p.length > 3 ? p[3] : 1 };
  };
  const key = (c) => `${c.r},${c.g},${c.b}`;
  const bodyBg = parse(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };

  // interactive controls: the outermost matching element only
  const CONTROL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=tab],[role=switch],[role=checkbox],[role=radio],[role=menuitem],[role=option],[tabindex]:not([tabindex="-1"])';
  const controls = [...root.querySelectorAll(CONTROL)].filter(visible);
  const outer = controls.filter((e) => !controls.some((o) => o !== e && o.contains(e)));

  // chips and badges: small rounded or tag-classed elements with a few words; descendants of a counted one are not counted again
  const chips = [];
  for (const e of all) {
    const r = rectOf(e);
    const text = (e.innerText || "").replace(/\s+/g, " ").trim();
    if (!text || text.length > 28 || r.height > 34 || r.width > 240) continue;
    const cs = getComputedStyle(e);
    const radius = parseFloat(cs.borderTopLeftRadius) || 0;
    const bg = parse(cs.backgroundColor);
    const tagged = /chip|badge|pill|tag\b|label/i.test(String(e.className));
    if (!(tagged || (radius >= 10 && bg && bg.a > 0.05))) continue;
    if (chips.some((c) => c.contains(e))) continue;
    chips.push(e);
  }

  // cards and boxes: a bordered, shadowed or filled block of some size, not a page-level wrapper
  const cards = [];
  for (const e of all) {
    if (!/^(DIV|SECTION|ARTICLE|LI|A|BUTTON|DETAILS|FORM|ASIDE|DL)$/.test(e.tagName)) continue;
    const r = rectOf(e);
    if (r.width < 100 || r.height < 44) continue;
    if (e === root || r.height > scrollHeight * 0.9 || (r.width >= vw * 0.98 && r.height > vh * 0.8)) continue;
    const cs = getComputedStyle(e);
    const bw = parseFloat(cs.borderTopWidth) || 0;
    const bc = parse(cs.borderTopColor);
    const bg = parse(cs.backgroundColor);
    const bordered = bw >= 1 && bc && bc.a > 0.1;
    const shadowed = cs.boxShadow && cs.boxShadow !== "none";
    const filled = bg && bg.a >= 0.9 && key(bg) !== key(bodyBg);
    if (bordered || shadowed || filled) cards.push(e);
  }

  // notices and banners: status and alert regions, live regions, notice-like classes, and floating pills or cards that are not navigation
  const notices = all.filter((e) => {
    if (e.matches('[role=status],[role=alert],[aria-live="polite"],[aria-live="assertive"]') && (e.innerText || "").trim()) return true;
    if (/notice|banner|toast|callout|alert/i.test(String(e.className)) && (e.innerText || "").trim() && rectOf(e).height <= 220) return true;
    const cs = getComputedStyle(e);
    if (cs.position === "fixed" && !e.closest("nav,header,footer,[role=navigation],[role=banner],dialog,[role=dialog]") && (e.innerText || "").trim() && rectOf(e).height <= 160 && !/^(NAV|HEADER)$/.test(e.tagName)) return true;
    return false;
  });
  const noticesOuter = notices.filter((e) => !notices.some((o) => o !== e && o.contains(e)));

  // text lines: the line boxes of the visible text, fragments on one line merged
  const lines = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!/\S/.test(n.nodeValue || "")) continue;
    const el = n.parentElement;
    if (!el || !visible(el) || /^(SCRIPT|STYLE|NOSCRIPT)$/i.test(el.tagName)) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    const tops = new Set();
    for (const r of range.getClientRects()) if (r.width >= 2 && r.height >= 4) tops.add(Math.round(r.top / 3));
    for (const t of tops) lines.push({ top: t * 3, h: range.getBoundingClientRect().height });
  }

  // colours: text, filled backgrounds and visible borders of the shown elements
  const colours = (list) => {
    const set = new Set();
    for (const e of list) {
      const cs = getComputedStyle(e);
      const hasText = [...e.childNodes].some((c) => c.nodeType === 3 && /\S/.test(c.nodeValue || ""));
      const t = parse(cs.color);
      if (hasText && t && t.a > 0.05) set.add(key(t));
      const bg = parse(cs.backgroundColor);
      if (bg && bg.a > 0.05) set.add(key(bg));
      const bc = parse(cs.borderTopColor);
      if (bc && bc.a > 0.05 && parseFloat(cs.borderTopWidth) >= 1) set.add(key(bc));
    }
    return set.size;
  };

  const part = (pick) => ({
    controls: outer.filter((e) => pick(rectOf(e))).length,
    chips: chips.filter((e) => pick(rectOf(e))).length,
    textLines: lines.filter((l) => pick({ top: l.top, bottom: l.top + 4 })).length,
    cards: cards.filter((e) => pick(rectOf(e))).length,
    notices: noticesOuter.filter((e) => pick(rectOf(e))).length,
    colours: colours(all.filter((e) => pick(rectOf(e)))),
  });
  return { vw, vh, scope, scrollHeight, fold: part((r) => r.bottom > 0 && r.top < vh), full: part(() => true) };
}

// large text: every element's text is made 1.3x as big, the way the zoom family of the state attacks does it (the app sizes its text in px, so the root font size alone changes nothing: tried 2 Nov 2026)
const ZOOM = (k) => {
  const els = [...document.querySelectorAll("body *")].filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()));
  const sizes = els.map((el) => parseFloat(getComputedStyle(el).fontSize));
  els.forEach((el, i) => el.style.setProperty("font-size", `${(sizes[i] * k).toFixed(2)}px`, "important"));
};
// the page is measured once its height stops changing (lists fill in after the first paint)
async function stable(page) {
  let last = -1;
  for (let i = 0; i < 14; i++) {
    const h = await page.evaluate(() => Math.max(document.documentElement.scrollHeight, document.body.scrollHeight, ...[...document.querySelectorAll("dialog[open],[role=dialog]")].map((d) => d.scrollHeight))).catch(() => 0);
    if (h === last && h > 0) return;
    last = h;
    await sleep(1500);
  }
}
const VARIANTS = [
  { key: "360x800", width: 360, height: 800, zoom: null },
  { key: "390x844", width: 390, height: 844, zoom: null },
  { key: "360x800-large-text", width: 360, height: 800, zoom: 1.3 },
];
const SCREENS = [
  { key: "home", route: "/dashboard" },
  { key: "leads-to-call", route: "/leads" },
  { key: "lead-page", route: null, open: "lead" },
  { key: "after-call-sheet", route: null, open: "after-call" },
  { key: "analysis-calls", route: "/analysis/calls" },
];
const PEOPLE = ["priya", "karan"];

async function openTabAs(alias, variant) {
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const tab = await session.openTab({ alias, device: "360 px", theme: "light", state: "normal" });
      await tab.page.setViewportSize({ width: variant.width, height: variant.height });
      await tab.context.route("**/*", (rt) => (["GET", "HEAD", "OPTIONS"].includes(rt.request().method()) ? rt.fallback() : rt.abort("blockedbyclient")));
      return tab;
    } catch {
      await sleep(15000);
    }
  }
  return null;
}

async function gotoScreen(tab, alias, screen) {
  const page = tab.page;
  if (screen.route) {
    await session.go(tab, screen.route, { wait: 40000 });
    await sleep(4500);
    return true;
  }
  if (alias === "priya") {
    const pool = JSON.parse(fs.readFileSync(POOL, "utf8"));
    await session.go(tab, `/leads?lead=${pool[0].id}`, { wait: 40000 });
  } else {
    await session.go(tab, "/leads?view=all", { wait: 40000 });
    await sleep(3000);
    const row = page.getByRole("button", { name: /^Open (?!lead$)(?!.* menu$)/ }).filter({ visible: true }).first();
    await row.click({ timeout: 8000 }).catch(() => null);
  }
  await sleep(4500);
  if (screen.open === "after-call") {
    const log = page.getByRole("button", { name: /^Log a call/ }).filter({ visible: true }).first();
    if (!(await log.count())) return false;
    await log.click({ timeout: 6000 }).catch(() => null);
    await sleep(2000);
  }
  return true;
}

async function run() {
  fs.mkdirSync(OUT, { recursive: true });
  const rows = [];
  for (const alias of PEOPLE) {
    for (const variant of VARIANTS) {
      for (const screen of SCREENS) {
        const label = `${screen.key}__${alias}__${variant.key}`;
        const tab = await openTabAs(alias, variant);
        if (!tab) {
          console.log(`${label}: no sign-in`);
          continue;
        }
        try {
          const ok = await gotoScreen(tab, alias, screen);
          if (ok) await stable(tab.page);
          if (ok && variant.zoom) {
            await tab.page.evaluate(ZOOM, variant.zoom);
            await sleep(1200);
          }
          await tab.page.evaluate(() => window.scrollTo(0, 0));
          await sleep(500);
          if (!ok) {
            console.log(`${label}: screen did not open`);
            rows.push({ screen: screen.key, person: alias, variant: variant.key, error: "did not open" });
            continue;
          }
          const m = await tab.page.evaluate(measure, variant.height);
          await tab.page.screenshot({ path: path.join(OUT, `${label}__fold.png`) });
          await tab.page.screenshot({ path: path.join(OUT, `${label}__full.png`), fullPage: true }).catch(() => null);
          rows.push({ screen: screen.key, person: alias, variant: variant.key, ...m });
          console.log(`${label}: fold ${JSON.stringify(m.fold)} | full ${JSON.stringify(m.full)} | page ${m.scrollHeight}px`);
        } catch (error) {
          console.log(`${label}: failed ${String(error).split("\n")[0].slice(0, 120)}`);
          rows.push({ screen: screen.key, person: alias, variant: variant.key, error: String(error).split("\n")[0].slice(0, 120) });
        }
        await session.closeTab(tab);
        await sleep(2500);
      }
    }
  }
  fs.writeFileSync(path.join(OUT, "density.json"), JSON.stringify(rows, null, 1));
  const cols = ["controls", "chips", "textLines", "cards", "notices", "colours"];
  const csv = ["screen,person,variant,scope,height_px," +cols.map((c) => "fold_" + c).join(",") + "," + cols.map((c) => "full_" + c).join(",")];
  const md = [
    "# Density baseline, 2 Nov 2026 (light, fictional data, read-only)",
    "",
    "Counts per run: above the fold (first screen, viewport height) / on the full page. Controls = outermost interactive elements; chips = small rounded or tag-classed elements with up to 28 characters; text lines = line boxes of visible text; cards = bordered, shadowed or filled blocks of at least 100x44 px that are not page wrappers; notices = status/alert/live regions, notice-like classes and floating non-navigation cards; colours = distinct text, fill and border colours.",
    "",
    "The lead page and the after-call sheet are sheets: only what is inside the sheet is counted (scope = sheet, height = the sheet's own); the others are measured on the whole page.",
    "",
    "| screen | person | variant | scope | height px | controls | chips | text lines | cards | notices | colours |",
    "|---|---|---|---|---|---|---|---|---|---|---|",
  ];
  for (const r of rows) {
    if (r.error) {
      md.push(`| ${r.screen} | ${r.person} | ${r.variant} | - | - | ${r.error} | | | | | |`);
      continue;
    }
    const scope = r.scope === "dialog" ? "sheet" : "page";
    csv.push([r.screen, r.person, r.variant, scope, r.scrollHeight, ...cols.map((c) => r.fold[c]), ...cols.map((c) => r.full[c])].join(","));
    md.push(`| ${r.screen} | ${r.person} | ${r.variant} | ${scope} | ${r.scrollHeight} | ${cols.map((c) => `${r.fold[c]} / ${r.full[c]}`).join(" | ")} |`);
  }
  fs.writeFileSync(path.join(OUT, "density.csv"), csv.join("\n") + "\n");
  fs.writeFileSync(path.join(OUT, "density-table.md"), md.join("\n") + "\n");
  console.log(`written to ${OUT}: ${rows.length} runs`);
  await session.shutdown();
}

module.exports = { run, measure };
if (require.main === module) {
  run().then(() => process.exit(0)).catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
