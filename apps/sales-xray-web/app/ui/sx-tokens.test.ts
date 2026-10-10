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
    ([, value]) => value.match(/(\d+)px/)?.[1],
  );
  expect(sizes).toEqual(["12", "13", "14", "15", "20", "24"]);
});

it("is loaded for every screen", () => {
  expect(styles).toContain('@import "./ui/sx-tokens.css";');
});
