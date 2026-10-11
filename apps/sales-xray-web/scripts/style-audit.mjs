// Computed-style audit (owner, 11 Oct 03:30 IST: "fail on unstyled pages").
//
// A screenshot of a page whose CSS failed to load can still look like "a
// page". This audit reads what the browser actually computed and fails when:
//   - a stylesheet link has no sheet, or the page has fewer than MIN_RULES
//     CSS rules in total;
//   - a visible element carries the class "undefined" (a CSS-module class
//     that does not exist) or a CSS-module class that no rule mentions;
//   - a visible button, input, select or textarea has the browser's default
//     look (2 px outset/inset border, or the 13.33 px control font);
//   - the page background does not match the theme (light above 0.6
//     luminance, dark below 0.35) or the text falls back to a serif default;
//   - the layout collapsed: no <main> at least half the window wide (85 %
//     on phones) and 200 px tall, no page heading, no navigation rail on a
//     wide signed-in page, or content on fewer than three distinct rows.
//
// The page matrix runs it on every screen; its negative control blocks every
// stylesheet first and requires the audit to fail (proof it can see).

export const MIN_RULES = 300;

/** Runs in the page. `shell`: a signed-in app page with the navigation rail. */
export function auditPage({ scheme, shell, minRules }) {
  const problems = [];
  const visible = (node) => {
    const box = node.getBoundingClientRect();
    if (box.width <= 1 || box.height <= 1) return false;
    const style = getComputedStyle(node);
    return style.visibility !== "hidden" && style.display !== "none";
  };

  // 1. Stylesheets arrived and carry rules.
  let rules = 0;
  const selectors = [];
  const walk = (list) => {
    for (const rule of list) {
      rules += 1;
      if (rule.selectorText) selectors.push(rule.selectorText);
      if (rule.cssRules) walk(rule.cssRules);
    }
  };
  for (const sheet of document.styleSheets) {
    try {
      walk(sheet.cssRules);
    } catch {
      // A cross-origin sheet: counted as present, rules unreadable.
    }
  }
  for (const link of document.querySelectorAll('link[rel="stylesheet"]'))
    if (!link.sheet)
      problems.push(
        `stylesheet did not load: ${link.getAttribute("href") ?? "?"}`,
      );
  if (rules < minRules)
    problems.push(`only ${rules} CSS rules (expected at least ${minRules})`);

  // 2. Classes with no styles behind them.
  const known = new Set();
  for (const selector of selectors)
    for (const match of selector.matchAll(/\.((?:\\.|[\w-])+)/g))
      known.add(match[1].replace(/\\/g, ""));
  const missing = new Set();
  let undefinedClass = 0;
  for (const node of document.body.querySelectorAll("[class]")) {
    if (!(node instanceof HTMLElement) || !visible(node)) continue;
    for (const token of node.classList) {
      if (token === "undefined") undefinedClass += 1;
      else if (token.includes("module__") && !known.has(token))
        missing.add(token);
    }
  }
  if (undefinedClass)
    problems.push(
      `${undefinedClass} visible element(s) with the class "undefined"`,
    );
  if (missing.size)
    problems.push(
      `CSS-module classes with no rule: ${[...missing].slice(0, 5).join(", ")}`,
    );

  // 3. Controls left with the browser's default look.
  const defaults = [];
  for (const node of document.body.querySelectorAll(
    "button, input, select, textarea",
  )) {
    if (!visible(node)) continue;
    if (
      node instanceof HTMLInputElement &&
      ["checkbox", "radio", "file", "range", "hidden", "color"].includes(
        node.type,
      )
    )
      continue;
    const style = getComputedStyle(node);
    const outset =
      ["outset", "inset"].includes(style.borderTopStyle) &&
      style.borderTopWidth === "2px";
    // The control font matters where the control draws text itself (a
    // field's value, a button's own words), not around an icon or children
    // that set their own size.
    const ownText =
      !(node instanceof HTMLButtonElement) ||
      [...node.childNodes].some(
        (child) =>
          child.nodeType === Node.TEXT_NODE && child.textContent?.trim(),
      );
    const font =
      ownText && Math.abs(parseFloat(style.fontSize) - 13.3333) < 0.01;
    if (outset || font)
      defaults.push(
        `${node.tagName.toLowerCase()}${node.getAttribute("aria-label") ? `[${node.getAttribute("aria-label")}]` : ""} (${outset ? "default border" : "default 13.33 px font"})`,
      );
  }
  if (defaults.length)
    problems.push(
      `${defaults.length} control(s) with the browser's default look: ${defaults.slice(0, 3).join(", ")}`,
    );

  // 4. Theme and type.
  const main = document.querySelector("main");
  const luminance = (color) => {
    const parts = color.match(/[\d.]+/g)?.map(Number) ?? [];
    if (parts.length < 3 || parts[3] === 0) return null;
    const [r, g, b] = parts.slice(0, 3).map((value) => {
      const channel = value / 255;
      return channel <= 0.03928
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  let background = null;
  for (let node = main ?? document.body; node; node = node.parentElement) {
    background = luminance(getComputedStyle(node).backgroundColor);
    if (background !== null) break;
  }
  // The theme the app says it is drawing (a build without the theme
  // preview stays light whatever the system asks), else the system's.
  const theme =
    document.documentElement.getAttribute("data-theme") === "dark"
      ? "dark"
      : document.documentElement.hasAttribute("data-theme")
        ? "light"
        : scheme;
  if (background === null) problems.push("the page has no background colour");
  else if (theme === "dark" ? background >= 0.35 : background <= 0.6)
    problems.push(
      `the background (luminance ${background.toFixed(2)}) does not match the ${theme} theme`,
    );
  const family = getComputedStyle(main ?? document.body).fontFamily;
  if (/^"?(Times|serif)/i.test(family))
    problems.push(`text falls back to the browser's serif (${family})`);

  // 5. Layout (app pages draw <main>; public pages are checked as a whole).
  const width = window.innerWidth;
  const frame = shell ? main : (main ?? document.body);
  if (!frame || !visible(frame)) problems.push("no visible <main>");
  else {
    const box = frame.getBoundingClientRect();
    const share = width < 900 ? 0.85 : 0.5;
    if (box.width < width * share)
      problems.push(
        `<main> is ${Math.round(box.width)} px wide (under ${Math.round(share * 100)} % of ${width})`,
      );
    if (box.height < 200)
      problems.push(`<main> is ${Math.round(box.height)} px tall`);
    const tops = new Set();
    for (const node of frame.querySelectorAll("*")) {
      if (!visible(node)) continue;
      const nodeBox = node.getBoundingClientRect();
      if (nodeBox.height >= 12 && nodeBox.top < window.innerHeight)
        tops.add(Math.round(nodeBox.top / 4));
    }
    if (tops.size < 3)
      problems.push(
        `content collapsed onto ${tops.size} row(s) (expected at least 3)`,
      );
  }
  const heading = [
    ...document.querySelectorAll("h1, h2, [class*='titleText']"),
  ].some(visible);
  if (!heading) problems.push("no visible page heading");
  if (shell && width >= 900) {
    const rail = document.querySelector(
      'aside[aria-label="Sales Xray navigation"]',
    );
    if (!rail || !visible(rail) || rail.getBoundingClientRect().width < 48)
      problems.push("no navigation rail on a wide signed-in page");
  }
  return { problems, rules, theme };
}

/** Run the audit on a loaded page; `shell` marks the signed-in app pages. */
export async function auditStyles(page, { scheme, shell }) {
  const result = await page.evaluate(auditPage, {
    scheme,
    shell,
    minRules: MIN_RULES,
  });
  return result.problems.map((problem) => `style: ${problem}`);
}
