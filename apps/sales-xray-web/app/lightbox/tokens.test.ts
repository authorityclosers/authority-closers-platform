import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const appDir = join(here, "..");
const derivative = readFileSync(join(here, "tokens.css"), "utf8");
const source = readFileSync(
  join(
    appDir,
    "../../../docs/design/sales-xray-v02-lightbox-20260924/tokens.css",
  ),
  "utf8",
);
const styles = readFileSync(join(appDir, "styles.css"), "utf8");

type Tokens = Map<string, string>;

function withoutComments(css: string) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function block(css: string, selector: string): string {
  const clean = withoutComments(css);
  const start = clean.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`missing ${selector}`);
  const open = clean.indexOf("{", start);
  return clean.slice(open + 1, clean.indexOf("}", open));
}

function tokens(body: string): Tokens {
  const found: Tokens = new Map();
  for (const match of body.matchAll(/--lx-([a-z0-9-]+):\s*([^;]+);/g))
    found.set(match[1], match[2].trim().replace(/\s+/g, " ").toLowerCase());
  return found;
}

const sourceLight = tokens(block(source, "\n:root"));
const sourceDark = tokens(block(source, ':root[data-theme="dark"]'));
const appLight = tokens(block(derivative, "\n:root"));
const appDarkOverrides = tokens(block(derivative, ':root[data-theme="dark"]'));
const appDark: Tokens = new Map([...appLight, ...appDarkOverrides]);
const sourceDarkResolved: Tokens = new Map([...sourceLight, ...sourceDark]);

type Rgba = [number, number, number, number];

function parseColor(value: string): Rgba {
  const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const digits =
      hex[1].length === 3
        ? [...hex[1]].map((digit) => digit + digit).join("")
        : hex[1];
    return [0, 2, 4]
      .map((offset) => parseInt(digits.slice(offset, offset + 2), 16))
      .concat(1) as Rgba;
  }
  const rgba = value.match(
    /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/,
  );
  if (rgba)
    return [
      Number(rgba[1]),
      Number(rgba[2]),
      Number(rgba[3]),
      rgba[4] === undefined ? 1 : Number(rgba[4]),
    ];
  throw new Error(`not a colour: ${value}`);
}

// Alpha fills are composited over the surface they sit on, as browsers do.
function composite(color: Rgba, base: Rgba): Rgba {
  const alpha = color[3];
  return [
    color[0] * alpha + base[0] * (1 - alpha),
    color[1] * alpha + base[1] * (1 - alpha),
    color[2] * alpha + base[2] * (1 - alpha),
    1,
  ];
}

function luminance([r, g, b]: Rgba) {
  const linear = (channel: number) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(set: Tokens, foreground: string, background: string) {
  const value = (name: string) => {
    const raw = set.get(name);
    if (!raw) throw new Error(`missing --lx-${name}`);
    return parseColor(raw);
  };
  const surface = value("surface");
  const bg = composite(value(background), surface);
  const fg = composite(value(foreground), bg);
  const [light, dark] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

// Every foreground/background pair Lightbox uses for text below 18.66px bold.
const smallTextPairs: [string, string][] = [
  ["ink", "paper"],
  ["ink", "surface"],
  ["ink-2", "surface"],
  ["ink-3", "paper"],
  ["ink-3", "surface"],
  ["ink-3", "sunken"],
  ["muted", "paper"],
  ["muted", "surface"],
  ["muted", "sunken"],
  ["muted-2", "paper"],
  ["muted-2", "paper-2"],
  ["muted-2", "surface"],
  ["teal", "paper"],
  ["teal", "surface"],
  ["on-teal", "teal"],
  ["surface", "ink"],
  ["strength-ink", "strength-soft"],
  ["strength-ink", "surface"],
  ["strength-ink", "paper"],
  ["focus-ink", "focus-soft"],
  ["missed-ink", "missed-soft"],
  ["objection-ink", "objection-soft"],
  ["closing-ink", "closing-soft"],
  ["danger", "danger-soft"],
  ["danger", "surface"],
  ["info", "info-soft"],
  ["warning", "warning-soft"],
  ["hypothesis", "sunken"],
  ["ink-2", "strength-soft"],
  ["ink-2", "focus-soft"],
  ["ink-2", "missed-soft"],
  ["ink-2", "objection-soft"],
  ["ink-2", "closing-soft"],
  ["film-text", "film"],
  ["film-text-2", "film"],
  ["film-text-3", "film"],
  ["film-text-2", "film-2"],
  ["film-text-3", "film-2"],
  ["glow", "film"],
];

describe("Lightbox token derivative", () => {
  it("keeps every source token except the documented corrections", () => {
    const changedLight = new Map([["muted-2", "#646d7f"]]);
    const addedLight = new Set([
      "strength-ink",
      "objection-ink",
      "on-teal",
      "glow-ink",
      "film-lens-outline",
      "film-lens-fill",
    ]);
    const addedDark = new Set([
      "on-teal",
      "strength-ink",
      "objection-ink",
      "closing-ink",
      "hypothesis",
      "info",
      "info-soft",
      "warning",
      "warning-soft",
    ]);

    for (const [name, value] of sourceLight)
      expect([name, appLight.get(name)]).toEqual([
        name,
        changedLight.get(name) ?? value,
      ]);
    expect(
      new Set([...appLight.keys()].filter((name) => !sourceLight.has(name))),
    ).toEqual(addedLight);

    for (const [name, value] of sourceDark)
      expect([name, appDarkOverrides.get(name)]).toEqual([name, value]);
    expect(
      new Set(
        [...appDarkOverrides.keys()].filter((name) => !sourceDark.has(name)),
      ),
    ).toEqual(addedDark);

    expect(appDarkOverrides.get("closing-ink")).toBe("#bfd0ff");
    expect(appLight.get("strength-ink")).toBe("#06736f");
    expect(derivative).toContain('[data-script="deva"]');
  });

  it("documents real source failures that the corrections resolve", () => {
    expect(contrast(sourceLight, "muted-2", "paper")).toBeLessThan(4.5);
    expect(contrast(sourceLight, "teal", "strength-soft")).toBeLessThan(4.5);
    expect(
      contrast(sourceDarkResolved, "objection", "objection-soft"),
    ).toBeLessThan(4.5);
    expect(
      contrast(sourceDarkResolved, "closing-ink", "closing-soft"),
    ).toBeLessThan(4.5);
  });

  it.each([
    ["light", appLight],
    ["dark", appDark],
  ] as const)(
    "gives every small-text pair at least 4.5:1 in %s, including alpha fills",
    (_theme, set) => {
      const failures = smallTextPairs
        .map(([fg, bg]) => ({
          pair: `${fg} on ${bg}`,
          ratio: contrast(set, fg, bg),
        }))
        .filter(({ ratio }) => ratio < 4.5);
      expect(failures).toEqual([]);
    },
  );

  it("mirrors the light tokens into an embed scope the standalone root skips", () => {
    const start = styles.indexOf("/* lightbox-embed-tokens:start");
    const end = styles.indexOf("/* lightbox-embed-tokens:end */");
    expect(start).toBeGreaterThanOrEqual(0);
    expect(end).toBeGreaterThan(start);
    const embed = styles.slice(start, end);
    expect(styles.indexOf("@scope (.xray-app) {")).toBeGreaterThan(end);
    const scoped = tokens(
      block(embed, ":where(html:not([data-lx-root])) .xray-app"),
    );
    expect(scoped).toEqual(appLight);
    // Only the scoped selector declares tokens; no global element or :root rule.
    expect(withoutComments(embed)).not.toMatch(/(^|\n)\s*:root\b/);
  });

  it("keeps new Lightbox modules on tokens, never raw hex colours", () => {
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name))
          files.push(path);
      }
    };
    walk(join(appDir, "lightbox"));
    walk(join(appDir, "shell"));
    files.push(join(appDir, "profile-menu.module.css"));
    const offenders = files
      .filter((path) => !path.endsWith(join("lightbox", "tokens.css")))
      .filter((path) =>
        /#[0-9a-f]{3,8}\b/i.test(withoutComments(readFileSync(path, "utf8"))),
      )
      .map((path) => relative(appDir, path));
    expect(offenders).toEqual([]);
  });
});
