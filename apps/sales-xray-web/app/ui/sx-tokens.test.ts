import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const tokens = readFileSync(join(here, "sx-tokens.css"), "utf8");
const lightbox = readFileSync(join(here, "../lightbox/tokens.css"), "utf8");
const styles = readFileSync(join(here, "../styles.css"), "utf8");

it("holds no raw colour: every colour aliases or tints a Lightbox token", () => {
  const code = tokens.replace(/\/\*[\s\S]*?\*\//g, "");
  expect(code).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  expect(code).not.toMatch(/\b(rgb|rgba|hsl|hsla|oklch)\(/i);
});

it("aliases only Lightbox tokens that exist", () => {
  const used = [...tokens.matchAll(/var\((--lx-[\w-]+)\)/g)].map(
    ([, name]) => name,
  );
  expect(used.length).toBeGreaterThan(10);
  for (const name of new Set(used))
    expect(lightbox, name).toMatch(new RegExp(`${name}:`));
});

it("allows three text sizes plus title and figure styles", () => {
  const sizes = [...tokens.matchAll(/--sx-text-[\w-]+:\s*([^;]+);/g)].map(
    ([, value]) => value.match(/(\d+(?:\.\d+)?)px/)?.[1],
  );
  // Liquid Glass (owner, 22 Oct): 12.5/14/15 on computers, then panel,
  // headline, title, figure and large title; Apple's 13/15/16.5 on phones.
  expect(sizes).toEqual([
    "12.5",
    "14",
    "15",
    "16",
    "17",
    "22",
    "30",
    "32",
    "13",
    "15",
    "16.5",
  ]);
});

it("gives low-memory phones a lighter glass", () => {
  const code = tokens.replace(/\/\*[\s\S]*?\*\//g, "");
  expect(code).toMatch(
    /:root\[data-sx-glass="lite"\][^{]*\{[^}]*--sx-glass-blur: blur\(8px\)/,
  );
});

it("keeps glass on one material with solid fallbacks (design system v2)", () => {
  const code = tokens.replace(/\/\*[\s\S]*?\*\//g, "");
  expect(code).toMatch(
    /\.sx-glass\s*\{[^}]*backdrop-filter:\s*var\(--sx-glass-blur\)/,
  );
  expect(code).toMatch(/@supports not \(\s*\(backdrop-filter/);
  expect(code).toMatch(
    /prefers-reduced-transparency: reduce[^@]*--sx-glass: var\(--sx-elevated\)/,
  );
  expect(code).toMatch(
    /prefers-contrast: more[^@]*--sx-glass: var\(--sx-elevated\)/,
  );
});

it("gives motion springs and a reduced-motion answer", () => {
  const code = tokens.replace(/\/\*[\s\S]*?\*\//g, "");
  expect(code).toMatch(/--sx-spring:\s*linear\(/);
  expect(code).toMatch(
    /prefers-reduced-motion: reduce\)\s*\{\s*:root\s*\{[^}]*--sx-spring: var\(--sx-ease-out\)/,
  );
});

it("is loaded for every screen", () => {
  expect(styles).toContain('@import "./ui/sx-tokens.css";');
});
