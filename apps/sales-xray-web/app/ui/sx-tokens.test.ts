import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const tokens = readFileSync(
  join(here, "../../../../packages/typescript/ui/src/kit/tokens/screen.css"),
  "utf8",
);
const lightbox = readFileSync(
  join(here, "../../../../packages/typescript/ui/src/kit/tokens/palette.css"),
  "utf8",
);
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

// Native-feel spec, 3 Nov 2026 (owner: "unrealistic, unsized, ugly"):
// Material 3's sizes in rem, so the phone's font size scales text as sp does.
const px = (pattern: RegExp) =>
  [...tokens.matchAll(pattern)].map(([, step, rem]) => [
    step,
    Number(rem) * 16,
  ]);

// Computers keep v1.38's steps; phones keep v1.37's 13, 15 and 16.5 (owner, 4 Nov 2026: v1.38 at least
// as good as v1.37). All in rem, so they follow the phone's font size.
it("allows one text scale per pointer, in rem", () => {
  expect(px(/--sx-text-([\w-]+):\s*([\d.]+)rem;/g)).toEqual([
    ["2xs", 11],
    ["xs", 12],
    ["sm", 14],
    ["md", 16],
    ["xl", 22],
    ["2xl", 28],
    ["3xl", 32],
    ["xs", 13],
    ["sm", 15],
    ["md", 16.5],
  ]);
  // Line heights are ratios of their step, so a line grows with its text
  // however it is enlarged (robot rows at 130 and 200 %, 3 Nov 2026).
  const leading = [
    ...tokens.matchAll(/--sx-leading-(\d+):\s*calc\((\d+) \/ (\d+)\);/g),
  ].map(([, name, line, size]) => [Number(name), Number(line), Number(size)]);
  expect(leading.map(([name]) => name)).toEqual([16, 20, 24, 28, 36]);
  for (const [name, line, size] of leading) {
    expect(line).toBe(name);
    expect([11, 12, 14, 16, 22, 28, 32]).toContain(size);
  }
  const code = tokens.replace(/\/\*[\s\S]*?\*\//g, "");
  expect(code).not.toMatch(/--sx-(text|leading)-[\w-]+:[^;]*\dpx/);
  expect(code).not.toMatch(/--sx-leading-[\w-]+:[^;]*rem/);
});

// v1.37's role weights are back (owner, 4 Nov 2026: v1.38 at least as good as v1.37).
it("gives the roles v1.37's weights", () => {
  const weights = [...tokens.matchAll(/--sx-text-[\w-]+:\s*(\d{3})\s/g)].map(
    ([, weight]) => Number(weight),
  );
  expect(weights.length).toBe(11);
  expect(new Set(weights)).toEqual(new Set([400, 500, 650, 700, 750, 800]));
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

it("draws the accent badge's words darker than the plain accent", () => {
  // The QA robot, 9 Nov 2026 (7d642443): "Owner" and "Admin" were 4.32:1.
  const kit = readFileSync(
    join(here, "../../../../packages/typescript/ui/src/kit/kit.module.css"),
    "utf8",
  );
  const badge = /\.badge\[data-tone="accent"\] \{([^}]*)\}/.exec(kit)?.[1];
  expect(badge).toContain(
    "color: color-mix(in oklab, var(--sx-accent) 80%, var(--sx-ink));",
  );
});
