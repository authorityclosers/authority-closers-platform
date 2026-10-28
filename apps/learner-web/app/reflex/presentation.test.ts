import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
const css = readFileSync(
  new URL("./screens.module.css", import.meta.url),
  "utf8",
);
const palette = readFileSync(
  new URL(
    "../../../../packages/typescript/ui/src/kit/tokens/palette.css",
    import.meta.url,
  ),
  "utf8",
);
function luminance(hex: string) {
  const rgb = hex
    .match(/[a-f\d]{2}/gi)!
    .map((channel) => parseInt(channel, 16) / 255)
    .map((channel) =>
      channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
    );
  return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
}
const values = (token: string) =>
  [
    ...palette.matchAll(new RegExp(`--lx-${token}:\\s*(#[a-f\\d]{6})`, "gi")),
  ].map((match) => match[1]);
describe("Reflex screen presentation constraints", () => {
  it("uses shared tokens, solid cards, 44px controls, focus and reduced motion", () => {
    expect(css).not.toMatch(/#[a-f\d]{3,8}\b|\b(?:rgba?|hsla?|oklch)\s*\(/i);
    expect(
      [...css.matchAll(/var\((--[^,)]+)/g)].every((match) =>
        match[1].startsWith("--sx-"),
      ),
    ).toBe(true);
    expect(css).not.toMatch(/backdrop-filter|--sx-glass/);
    expect(css).toContain("min-height: 44px");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("prefers-reduced-motion: reduce");
  });
  it.each([0, 1])(
    "keeps all screen text pairs above 4.5:1 in palette mode %s",
    (mode) => {
      for (const text of ["ink", "ink-2", "muted"]) {
        for (const background of ["paper", "surface", "sunken"]) {
          const a = luminance(values(text)[mode]);
          const b = luminance(values(background)[mode]);
          expect(
            (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
            `${text} on ${background}`,
          ).toBeGreaterThanOrEqual(4.5);
        }
      }
      const a = luminance(values("focus")[mode]);
      const b = luminance(values("on-teal")[mode]);
      expect(
        (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
      ).toBeGreaterThanOrEqual(4.5);
    },
  );
});
