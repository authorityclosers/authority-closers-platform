/**
 * Spec section 33, mobile usability, as rules on the stylesheet (the
 * screenshots at 363 x 735, text x1.3, light and dark, check the rest): no
 * sideways scroll, words wrap instead of being cut, every tap target is at
 * least 44 px, focus shows, colour comes from the theme's tokens and text
 * scales with the phone's font size.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "ask-dipak.module.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

/** The declarations of a rule whose selector list is exactly this. */
function rule(selector: string): string {
  const found = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].find(
    ([, head]) => head.trim() === selector,
  );
  if (!found) throw new Error(`no rule ${selector}`);
  return found[2];
}

const px = (body: string, property: string) => {
  const value = body.match(new RegExp(`(?:^|[;\\s])${property}:\\s*(\\d+)px`));
  return value ? Number(value[1]) : null;
};

it("cuts no words and never scrolls sideways", () => {
  expect(css).not.toMatch(
    /text-overflow|line-clamp|overflow-x:\s*(auto|scroll)/,
  );
  expect(rule(".root")).toMatch(/overflow-wrap:\s*anywhere/);
  // Full-width rows include their padding and border, as in the sample.
  expect(rule(".root,\n.root *,\n.root *::before,\n.root *::after")).toMatch(
    /box-sizing:\s*border-box/,
  );
  // Two columns that shrink with the phone, never a fixed width.
  expect(rule(".topicGrid")).toMatch(
    /grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/,
  );
  expect(css).not.toMatch(/(?:^|[;\s])(min-)?width:\s*(3\d\d|[4-9]\d\d)px/);
  expect(css).not.toMatch(/position:\s*fixed/);
});

it.each([
  [".tool", "height"],
  [".breadcrumb", "min-height"],
  [".see", "min-height"],
  [".searchHome,\n.searchField", "min-height"],
  [".topicCard", "min-height"],
  [".entry", "min-height"],
  [".questionRow", "min-height"],
  [".mcq", "min-height"],
  [".fold", "min-height"],
  [".mark", "height"],
  [".check", "height"],
  [".related", "min-height"],
  [".smallBtn", "min-height"],
])("gives %s a tap target of at least 44 px", (selector, property) => {
  const body = rule(selector);
  expect(px(body, property)).toBeGreaterThanOrEqual(44);
  if (property === "height")
    expect(px(body, "width")).toBeGreaterThanOrEqual(44);
});

it("shows where the keyboard is", () => {
  expect(rule(".root :where(a, button, input):focus-visible")).toMatch(
    /outline:\s*2px solid var\(--xr-green\)/,
  );
});

it("colours from the theme's tokens only, so light and dark both read", () => {
  expect(css).not.toMatch(/#[0-9a-f]{3,8}\b|\b(rgb|rgba|hsl|hsla)\(/i);
  const used = new Set(
    [...css.matchAll(/var\((--[\w-]+)\)/g)].map(([, name]) => name),
  );
  for (const name of used)
    expect(name).toMatch(/^--(sx|xr)-|^--lx-leading-devanagari$/);
  // The sample's green, as the app's green: selected, saved and done.
  expect(rule(".mcq.selected")).toContain("var(--xr-green)");
  expect(rule(".mark.active")).toContain("var(--xr-green)");
  expect(rule(".check.done::before")).toContain("var(--xr-green)");
});

it("takes text from the app's one type scale, which grows with the phone's text size", () => {
  const sizes = [...css.matchAll(/font-size:\s*([^;]+);/g)].map(([, v]) =>
    v.trim(),
  );
  expect(sizes.length).toBeGreaterThan(20);
  for (const size of sizes) expect(size).toMatch(/^var\(--sx-text-[\w-]+\)$/);
  // Hindi-English lines keep the Devanagari lift; the rest the scale's steps.
  for (const [, height] of css.matchAll(/line-height:\s*([^;]+);/g))
    expect(height.trim()).toMatch(
      /^var\(--(sx-leading-(16|20|24|28|36)|lx-leading-devanagari)\)$/,
    );
});

it("keeps motion to a turn of the Deep lesson's arrow, and none for reduced motion", () => {
  expect(css.match(/transition:/g)).toHaveLength(1);
  expect(css).toMatch(
    /@media \(prefers-reduced-motion: no-preference\)\s*\{\s*\.foldArrow\s*\{\s*transition/,
  );
});
