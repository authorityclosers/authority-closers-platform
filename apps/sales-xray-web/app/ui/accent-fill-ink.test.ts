import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

/**
 * Words on the accent fill (v1.99 twin judge, 25 Nov 2026): Settings > Call uploads' "Get the Android app" was a
 * blank green pill, its label in --sx-primary-ink (Home's green as an ink for a surface) on the green fill, 1.05:1.
 * A rule that paints var(--sx-accent) behind it never writes its words in an ink meant for a surface; it takes the
 * accent's own ink (--sx-accent-ink / --lx-on-teal), or sets none (bars, dots, tracks).
 */
const APP = join(dirname(fileURLToPath(import.meta.url)), "..");
const SURFACE_INKS =
  /var\(--(?:sx-primary-ink|sx-accent|sx-accent-soft|sx-ink|sx-ink-2|sx-muted|sx-tone-[a-z-]+|lx-teal|lx-home-primary|lx-home-emerald)\)/;

function stylesheets(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory())
      return name === "node_modules" ? [] : stylesheets(path);
    return name.endsWith(".css") ? [path] : [];
  });
}

it("never writes surface-ink words on the accent fill", () => {
  const bad: string[] = [];
  for (const path of stylesheets(APP)) {
    const css = readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const [, selector, body] of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (
        !/(?:^|[;\s])background(?:-color)?\s*:\s*var\(--sx-accent\)\s*;/.test(
          body,
        )
      )
        continue;
      const ink = body.match(/(?:^|[;\s])color\s*:\s*([^;]+);/)?.[1]?.trim();
      if (ink && SURFACE_INKS.test(ink))
        bad.push(
          `${relative(APP, path).split(sep).join("/")} ${selector.trim()}: ${ink}`,
        );
    }
  }
  expect(bad).toEqual([]);
});

/** WCAG relative luminance contrast of two #rrggbb colours. */
function contrast(a: string, b: string): number {
  const lum = (hex: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

it("keeps the accent's own ink at 4.5:1 on its fill, in every palette block", () => {
  const files = [
    join(APP, "styles.css"),
    join(
      APP,
      "..",
      "..",
      "..",
      "packages",
      "typescript",
      "ui",
      "src",
      "kit",
      "tokens",
      "palette.css",
    ),
  ];
  const pairs: Array<[string, string, string]> = [];
  for (const file of files) {
    for (const block of readFileSync(file, "utf8").split("}")) {
      const hex = (name: string) =>
        block.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})\\b`))?.[1];
      const teal = hex("lx-teal");
      const onTeal = hex("lx-on-teal");
      if (teal && onTeal) pairs.push([file, teal, onTeal]);
      // Settings paints the accent Home's green with white words (settings-shell.module.css) in both themes.
      const green = hex("lx-home-primary");
      const white = hex("lx-film-text") ?? (green ? "#ffffff" : undefined);
      if (green && white) pairs.push([file, green, white]);
    }
  }
  expect(pairs.length).toBeGreaterThan(2);
  const weak = pairs
    .map(([file, fill, ink]) => [
      relative(APP, file),
      fill,
      ink,
      contrast(fill, ink).toFixed(2),
    ])
    .filter(([, , , ratio]) => Number(ratio) < 4.5);
  expect(weak).toEqual([]);
});
