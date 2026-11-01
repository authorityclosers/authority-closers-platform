// Visual snapshots per route, size and theme against an approved baseline (pixelmatch, which is what Playwright's
// toHaveScreenshot uses underneath). Dev's data changes all day and builders edit it live, so the comparison is of
// the LAYOUT: text is painted transparent and pictures hidden before the shot, which leaves boxes, backgrounds,
// borders, shadows and positions. A text-only change never trips it; a moved or restyled block does.
// The first sighting creates the baseline; `engine.cjs approve <route...>` replaces one after an intended change.
const fs = require("fs");
const path = require("path");
const { PNG } = require("pngjs");
const pixelmatch = require("pixelmatch");
const cfg = require("./config.cjs");

const MASK_CSS = `
*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important}
*{color:transparent!important;text-shadow:none!important;-webkit-text-fill-color:transparent!important}
img,video,canvas,picture,svg image{visibility:hidden!important}
input::placeholder,textarea::placeholder{color:transparent!important}
`;
const SAME_BELOW = 0.004; // share of changed pixels that still counts as the same screen
const slug = (text) => text.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "").slice(0, 60) || "root";

function keyFor(route, deviceKey, theme) {
  return `${slug(route)}__${deviceKey}__${theme}`;
}

async function shoot(tab) {
  const page = tab.page;
  const style = await page.addStyleTag({ content: MASK_CSS }).catch(() => null);
  await page.evaluate(() => window.scrollTo(0, 0)).catch(() => null);
  await page.waitForTimeout(400);
  try {
    return await page.screenshot({ type: "png", animations: "disabled", caret: "hide", timeout: 25000 });
  } finally {
    if (style) await style.evaluate((el) => el.remove()).catch(() => null);
  }
}

function triptych(a, b, diff) {
  const w = a.width + b.width + diff.width;
  const h = Math.max(a.height, b.height, diff.height);
  const out = new PNG({ width: w, height: h });
  out.data.fill(255);
  let x = 0;
  for (const img of [a, b, diff]) {
    PNG.bitblt(img, out, 0, 0, img.width, img.height, x, 0);
    x += img.width;
  }
  return PNG.sync.write(out);
}

/**
 * Returns { status: "baseline" | "same" | "diff", ratio, key, png? (baseline | now | diff side by side) }.
 * `approve` replaces the baseline with this shot.
 */
async function compare(tab, route, theme, { approve = false } = {}) {
  fs.mkdirSync(cfg.BASELINES, { recursive: true });
  const key = keyFor(route, tab.dev.key, theme);
  const file = path.join(cfg.BASELINES, `${key}.png`);
  const buf = await shoot(tab);
  if (approve || !fs.existsSync(file)) {
    fs.writeFileSync(file, buf);
    return { status: "baseline", ratio: 0, key };
  }
  const base = PNG.sync.read(fs.readFileSync(file));
  const now = PNG.sync.read(buf);
  if (base.width !== now.width || base.height !== now.height) {
    const diff = new PNG({ width: now.width, height: now.height });
    return { status: "diff", ratio: 1, key, size: `${base.width}x${base.height} -> ${now.width}x${now.height}`, png: triptych(base, now, diff) };
  }
  const diff = new PNG({ width: now.width, height: now.height });
  const changed = pixelmatch(base.data, now.data, diff.data, now.width, now.height, { threshold: 0.12, includeAA: false });
  const ratio = changed / (now.width * now.height);
  if (ratio < SAME_BELOW) return { status: "same", ratio, key };
  return { status: "diff", ratio, key, png: triptych(base, now, diff) };
}

// A moved or restyled block: small shifts are POLISH, a page that looks different is MAJOR.
function findingFor(result, route, theme, deviceKey) {
  const pct = (result.ratio * 100).toFixed(1);
  const severity = result.ratio > 0.25 ? "MAJOR" : result.ratio > 0.05 ? "MINOR" : "POLISH";
  return {
    rule: "visual:layout-diff",
    selector: `${deviceKey}-${theme}`,
    severity,
    summary: `The layout differs from the approved snapshot (${pct}% of the screen)`,
    detail: `${route} at ${deviceKey} px, ${theme}: left = approved, middle = now, right = difference.${result.size ? ` Size ${result.size}.` : ""}`,
    route,
  };
}

module.exports = { compare, findingFor, keyFor };
