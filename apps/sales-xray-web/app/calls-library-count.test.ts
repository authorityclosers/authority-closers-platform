import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * The chosen Calls filter's count stays readable (the test robot, 80f01104,
 * 2 Nov 2026: white on a lightened teal was 4.13:1). Its pill is a shade of
 * the ink over the chip's teal, so the count keeps 4.5:1 in light and dark.
 */
const read = (path: string) => readFileSync(join(process.cwd(), path), "utf8");
const palette = read("../../packages/typescript/ui/src/kit/tokens/palette.css");
const css = read("app/calls-library.module.css");

const block = (start: string) => {
  const at = palette.indexOf(start);
  return palette.slice(at, palette.indexOf("\n}\n", at));
};
const token = (text: string, name: string) => {
  const hit = new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "i").exec(text);
  if (!hit) throw new Error(`no ${name}`);
  return hit[1].slice(1);
};
const rgb = (hex: string) =>
  [0, 2, 4].map((at) => parseInt(hex.slice(at, at + 2), 16));
const luminance = (colour: number[]) => {
  const [r, g, b] = colour.map((value) => {
    const share = value / 255;
    return share <= 0.04045 ? share / 12.92 : ((share + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (one: number[], two: number[]) => {
  const [high, low] = [luminance(one), luminance(two)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
};

const rule = css.slice(
  css.indexOf('.filters button[aria-pressed="true"] .chipCount {'),
);
const mix =
  /background: color-mix\(in oklab, var\((--lx-[a-z-]+)\) (\d+)%, transparent\);/.exec(
    rule.slice(0, rule.indexOf("}")),
  );

for (const [theme, start] of [
  ["light", ":root {"],
  ["dark", ':root[data-theme="dark"] {'],
]) {
  it(`keeps the chosen filter's count at 4.5:1 in ${theme}`, () => {
    expect(mix).not.toBeNull();
    const tokens = block(start);
    const shade = rgb(token(tokens, mix![1]));
    const share = Number(mix![2]) / 100;
    const teal = rgb(token(tokens, "--lx-teal"));
    const pill = teal.map(
      (value, index) => shade[index] * share + value * (1 - share),
    );
    expect(ratio(rgb(token(tokens, "--lx-on-teal")), pill)).toBeGreaterThan(
      4.5,
    );
  });
}
