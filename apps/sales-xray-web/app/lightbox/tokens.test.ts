import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { Window } from "happy-dom";

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
    found.set(
      match[1],
      match[2]
        .trim()
        .replace(/\s+/g, " ")
        .toLowerCase()
        // Prettier adds leading zeroes to decimals in alpha, easing and shadow
        // values. Preserve the numeric value while ignoring that formatting.
        .replace(
          /(^|[\s,(])(-?)\.(\d+)/g,
          (_, prefix, sign, digits) => `${prefix}${sign}0.${digits}`,
        ),
    );
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
    const changedLight = new Map([
      ["muted-2", "#646d7f"],
      // r17 phone shell: a 56 px tab bar, as in Pulse (was 76 px).
      ["bottom-nav-h", "56px"],
    ]);
    const addedLight = new Set([
      "strength-ink",
      "objection-ink",
      "on-teal",
      "glow-ink",
      "film-lens-outline",
      "film-lens-fill",
      "control-compact-h",
      "control-h",
      "table-head-h",
      "row-min-h",
      "panel-head-min-h",
      "tile-min-h",
      "density-control-compact",
      "density-control",
      "density-table-head",
      "density-row-min",
      "density-panel-head",
      "density-tile-min",
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
    // The 29 Sep 2026 vibrant palette resolved teal on strength-soft in the source.
    // It also resolved dark objection on objection-soft.
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

  it("keeps a light report surface coherent inside a dark app theme", () => {
    const surface = block(derivative, '[data-lx-surface="light"]');
    const declared = tokens(surface);
    // Every token the dark theme overrides, plus tokens whose var() at :root
    // references one (their computed value would otherwise inherit dark colours).
    const referencesDark = (value: string) =>
      [...value.matchAll(/var\(--lx-([a-z0-9-]+)\)/g)].some(([, name]) =>
        appDarkOverrides.has(name),
      );
    const required = new Set([
      ...appDarkOverrides.keys(),
      ...[...appLight.entries()]
        .filter(([, value]) => referencesDark(value))
        .map(([name]) => name),
    ]);
    expect(required.has("ring-focus")).toBe(true);
    const mismatched = [...required].filter(
      (name) => declared.get(name) !== appLight.get(name),
    );
    expect(mismatched).toEqual([]);
    expect(withoutComments(surface)).toMatch(/color-scheme:\s*light;/);
    expect(withoutComments(surface)).toMatch(
      /background-color:\s*var\(--lx-paper\);/,
    );
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
    // The report navigation (tab strip, section list, return control).
    files.push(join(appDir, "report-modes.module.css"));
    // Every report module follows the app theme, dark included.
    for (const name of [
      "call-map.module.css",
      "speaker.module.css",
      "dipak-overview.module.css",
      "prospect-snapshot.module.css",
      "report-moments.module.css",
      "sales-skills.module.css",
      "next-call-plan.module.css",
      "report-transcript.module.css",
      "transcript-reader.module.css",
      "report-factors.module.css",
      "report-explorer.module.css",
    ])
      files.push(join(appDir, name));
    const offenders = files
      .filter((path) => !path.endsWith(join("lightbox", "tokens.css")))
      .filter((path) =>
        /#[0-9a-f]{3,8}\b/i.test(withoutComments(readFileSync(path, "utf8"))),
      )
      .map((path) => relative(appDir, path));
    expect(offenders).toEqual([]);
  });

  describe("Scoped Pulse-role to Sales Xray teal adapter (AUT-1451 card 2)", () => {
    const pulseTokensPath = join(appDir, "ui", "pulse-tokens.css");
    const pulseTokensCss = readFileSync(pulseTokensPath, "utf8");

    it("declares all 20 Pulse semantic roles in ui/pulse-tokens.css", () => {
      const pulseRoles = [
        "canvas",
        "surface",
        "surface-subtle",
        "text",
        "text-muted",
        "border",
        "border-strong",
        "action",
        "action-hover",
        "action-text",
        "focus",
        "brand-2",
        "info",
        "success",
        "warning",
        "danger",
        "disabled-surface",
        "disabled-text",
        "shadow",
        "transition-duration",
      ];

      const clean = withoutComments(pulseTokensCss);
      for (const role of pulseRoles) {
        expect(clean).toMatch(new RegExp(`--theme-${role}:`));
      }
      expect(pulseRoles).toHaveLength(20);
    });

    it("maps Pulse roles strictly to Sales Xray teal/neutral tokens without iris or circular aliases", () => {
      const clean = withoutComments(pulseTokensCss);

      // No Iris action or brand colors
      expect(clean).not.toMatch(
        /#(5b45d6|4a35c0|7a68e6|a99cff|bdb3ff|b8adff)/i,
      );

      // No circular aliases (--lx-* mapping back to --theme-*)
      expect(clean).not.toMatch(/--lx-[a-z0-9-]+:\s*var\(--theme-/);

      // Action and brand map to teal
      expect(clean).toMatch(/--theme-action:\s*var\(--lx-teal\);/);
      expect(clean).toMatch(/--theme-action-hover:\s*var\(--lx-teal-hover\);/);
      expect(clean).toMatch(/--theme-action-text:\s*var\(--lx-on-teal\);/);
      expect(clean).toMatch(/--theme-brand-2:\s*var\(--lx-teal-2\);/);

      // Focus outline is teal, NEVER coaching orange --lx-focus
      expect(clean).toMatch(/--theme-focus:\s*var\(--lx-teal\);/);
      expect(clean).not.toMatch(/--theme-focus:\s*var\(--lx-focus\);/);

      // Coaching focus token --lx-focus in tokens.css remains orange (#b45309 in light, #f59e0b in dark)
      expect(appLight.get("focus")).toBe("#b45309");
      expect(appDarkOverrides.get("focus")).toBe("#f59e0b");
    });

    it("scopes the adapter so global :root is not polluted", () => {
      const clean = withoutComments(pulseTokensCss);
      // Must not declare --theme-* at global :root, html or body
      expect(clean).not.toMatch(
        /(?:^|\n)\s*(:root|html|body)\b[^{]*\{[^}]*--theme-/,
      );
      // Must declare under adapted component scope
      expect(clean).toMatch(
        /data-pulse-theme|data-pulse-adapted|\.pulse-adapted/,
      );
    });

    it("is imported in styles.css via scoped import", () => {
      expect(styles).toMatch(/@import\s+["']\.\/ui\/pulse-tokens\.css["'];/);
    });

    it("resolves operational density tokens on adapted components and in root", () => {
      expect(appLight.get("control-compact-h")).toBe("32px");
      expect(appLight.get("control-h")).toBe("36px");
      expect(appLight.get("table-head-h")).toBe("36px");
      expect(appLight.get("row-min-h")).toBe("44px");
      expect(appLight.get("panel-head-min-h")).toBe("48px");
      expect(appLight.get("tile-min-h")).toBe("96px");

      const clean = withoutComments(pulseTokensCss);
      expect(clean).toContain("--theme-control-compact-h");
      expect(clean).toContain("--theme-control-h");
      expect(clean).toContain("--theme-row-min-h");
      expect(clean).toContain("--theme-panel-head-min-h");
      expect(clean).toContain("--theme-tile-min-h");
    });
  });

  describe("Normalized compact controls and accessible touch targets (AUT-1474 card 3)", () => {
    const segmentedCss = readFileSync(
      join(here, "segmented.module.css"),
      "utf8",
    );
    const callsCss = readFileSync(
      join(appDir, "calls-library.module.css"),
      "utf8",
    );
    const reportModesCss = readFileSync(
      join(appDir, "report-modes.module.css"),
      "utf8",
    );
    const shellCss = readFileSync(
      join(appDir, "shell/lightbox-shell.module.css"),
      "utf8",
    );
    const switcherCss = readFileSync(
      join(appDir, "shell/workspace-switcher.module.css"),
      "utf8",
    );
    const profileCss = readFileSync(
      join(appDir, "profile-menu.module.css"),
      "utf8",
    );
    const themeToggleCss = readFileSync(
      join(appDir, "shell/theme-toggle.module.css"),
      "utf8",
    );

    it("ensures desktop compact controls use at least 32px minimum hit area", () => {
      expect(segmentedCss).toContain("--lx-control-compact-h");
      expect(callsCss).toContain("--lx-control-compact-h");
      expect(reportModesCss).toContain("--lx-control-compact-h");
      expect(shellCss).toContain("--lx-control-compact-h");
      expect(switcherCss).toContain("--lx-control-compact-h");
      expect(profileCss).toContain("--lx-control-compact-h");
    });

    it("ensures coarse pointer touch targets use at least 44px minimum hit area", () => {
      for (const css of [
        segmentedCss,
        callsCss,
        reportModesCss,
        shellCss,
        switcherCss,
        profileCss,
        themeToggleCss,
      ]) {
        expect(css).toMatch(/@media\s*\(\s*pointer:\s*coarse\s*\)/);
        expect(css).toContain("44px");
      }
    });

    it("computes at least 44px hit areas under coarse pointer across desktop and mobile layouts", () => {
      const testCoarseStyles = (
        css: string,
        selectors: Record<string, { minHeight?: number; minWidth?: number }>,
        additionalTransform?: (c: string) => string,
      ) => {
        let transformed = css.replace(
          /@media\s*\(\s*pointer:\s*coarse\s*\)/g,
          "@media all",
        );
        if (additionalTransform) {
          transformed = additionalTransform(transformed);
        }
        const win = new Window();
        const doc = win.document;
        const style = doc.createElement("style");
        style.textContent = derivative + "\n" + transformed;
        doc.head.appendChild(style);

        for (const [cls, expected] of Object.entries(selectors)) {
          const el = doc.createElement("button");
          el.className = cls;
          doc.body.appendChild(el);
          const computed = win.getComputedStyle(el);

          if (expected.minHeight !== undefined) {
            const h = parseInt(computed.minHeight || computed.height, 10);
            expect(h).toBeGreaterThanOrEqual(expected.minHeight);
          }
          if (expected.minWidth !== undefined) {
            const w = parseInt(computed.minWidth || computed.width, 10);
            expect(w).toBeGreaterThanOrEqual(expected.minWidth);
          }
        }
      };

      // Desktop layout (1280px)
      testCoarseStyles(shellCss, {
        collapseBtn: { minHeight: 44, minWidth: 44 },
        panelSearch: { minHeight: 44 },
        recentsViewAll: { minHeight: 44 },
        workspaceTrigger: { minHeight: 44 },
        toggle: { minHeight: 44, minWidth: 44 },
        stripBtn: { minHeight: 44, minWidth: 44 },
      });

      // Mobile layout (390px - matches max-width: 899.98px)
      testCoarseStyles(
        shellCss,
        {
          collapseBtn: { minHeight: 44, minWidth: 44 },
          panelSearch: { minHeight: 44 },
          recentsViewAll: { minHeight: 44 },
        },
        (c) =>
          c.replace(/@media\s*\(\s*max-width:\s*899\.98px\s*\)/g, "@media all"),
      );

      // Verify other control families compute 44px hit areas under coarse pointer
      testCoarseStyles(profileCss, {
        themeOption: { minHeight: 44, minWidth: 44 },
        item: { minHeight: 44 },
        headerTrigger: { minHeight: 44 },
      });

      testCoarseStyles(switcherCss, {
        trigger: { minHeight: 44 },
        item: { minHeight: 44 },
        action: { minHeight: 44 },
      });

      testCoarseStyles(themeToggleCss, {
        toggle: { minHeight: 44, minWidth: 44 },
      });

      testCoarseStyles(segmentedCss, {
        label: { minHeight: 44 },
      });
    });

    it("preserves Devanagari leading and flexible text growth without blanket fixed heights", () => {
      expect(segmentedCss).toContain("--lx-leading-devanagari");
      expect(callsCss).toContain("--lx-leading-devanagari");
      expect(reportModesCss).toContain("--lx-leading-devanagari");
      expect(shellCss).toContain("--lx-leading-devanagari");
    });
  });
});
