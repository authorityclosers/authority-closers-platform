import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const operations = readFileSync(
  new URL(
    "../../../packages/typescript/operations-web/src/styles.css",
    import.meta.url,
  ),
  "utf8",
);
const learner = readFileSync(
  new URL("../../learner-web/app/theme.css", import.meta.url),
  "utf8",
);
const pair = (name: string) => {
  const match = operations.match(
    new RegExp(`--${name}: light-dark\\((#[a-f0-9]{6}), (#[a-f0-9]{6})\\)`),
  );
  if (!match) throw new Error(`Missing semantic pair: ${name}`);
  return match.slice(1);
};
const luminance = (hex: string) => {
  const channels = [1, 3, 5].map((offset) => {
    const value = Number.parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
};
const contrast = (a: string, b: string) => {
  const values = [luminance(a), luminance(b)].sort((x, y) => x - y);
  return (values[1] + 0.05) / (values[0] + 0.05);
};

describe("shared Admin and Coach Clarity/cobalt palette", () => {
  it("tracks the actual learner light/dark semantic pairs", () => {
    const light = learner.match(/html\s*\{([^}]+)\}/)?.[1] ?? "";
    const dark =
      learner.match(/html\[data-theme="dark"\]\s*\{([^}]+)\}/)?.[1] ?? "";
    const mappings = {
      bg: "canvas",
      panel: "surface",
      "panel-raised": "surface-raised",
      "panel-soft": "surface-subtle",
      input: "input",
      line: "border",
      "line-strong": "border-strong",
      text: "text",
      muted: "text-muted",
      quiet: "disabled-text",
      signal: "action",
      "signal-hover": "action-hover",
      "signal-ink": "action-text",
      focus: "focus",
      "accent-soft": "info-surface",
      amber: "warning-text",
      "warning-surface": "warning-surface",
      danger: "danger-text",
      "danger-surface": "danger-surface",
      info: "success-text",
      "success-surface": "success-surface",
      "disabled-surface": "disabled-surface",
      "disabled-text": "disabled-text",
    };
    for (const [name, source] of Object.entries(mappings)) {
      const values = [light, dark].map(
        (block) =>
          block.match(new RegExp(`--theme-${source}: (#[a-f0-9]{6});`))?.[1],
      );
      expect(pair(name), name).toEqual(values);
    }
  });

  it.each([0, 1])(
    "keeps content and diagnostic states readable in mode %i",
    (mode) => {
      for (const text of ["text", "muted", "quiet"]) {
        for (const surface of [
          "bg",
          "panel",
          "panel-raised",
          "panel-soft",
          "input",
        ]) {
          expect(
            contrast(pair(text)[mode], pair(surface)[mode]),
            `${text}/${surface}`,
          ).toBeGreaterThanOrEqual(4.5);
        }
      }
      for (const [text, surface] of [
        ["signal-ink", "signal"],
        ["signal-ink", "signal-hover"],
        ["signal", "accent-soft"],
        ["amber", "warning-surface"],
        ["danger", "danger-surface"],
        ["info", "success-surface"],
      ]) {
        expect(
          contrast(pair(text)[mode], pair(surface)[mode]),
          `${text}/${surface}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
      expect(
        contrast(pair("focus")[mode], pair("panel")[mode]),
      ).toBeGreaterThanOrEqual(3);
      expect(
        new Set([
          pair("signal")[mode],
          pair("amber")[mode],
          pair("danger")[mode],
          pair("info")[mode],
        ]).size,
      ).toBe(4);
    },
  );

  it("defaults to learner-matching light and opts into system or explicit dark", () => {
    expect(operations).toMatch(/:root\s*\{[^}]*color-scheme:\s*light;/);
    expect(operations).toMatch(
      /html\[data-theme="system"\]\s*\{\s*color-scheme: light dark;/,
    );
    for (const theme of ["light", "dark"]) {
      expect(operations).toMatch(
        new RegExp(
          `html\\[data-theme="${theme}"\\]\\s*\\{\\s*color-scheme: ${theme};`,
        ),
      );
    }
    expect(operations.match(/\.clarity-shell\s*\{([^}]+)\}/)?.[1]).not.toMatch(
      /--(?:bg|panel|signal|text|muted|quiet):/,
    );
    expect(operations).not.toMatch(/#d9ff56|217, 255, 86|#10130f/i);
  });

  it("keeps secondary actions distinct on standalone sign-in as well as Studio", () => {
    const rule = operations.match(/\n\.button-secondary\s*\{([^}]+)\}/)?.[1];
    expect(rule).toContain("background: var(--panel)");
    expect(rule).toContain("color: var(--signal)");
    expect(operations).toMatch(
      /\.dev-admin-login-card input\s*\{[^}]*font-size: 1rem;/,
    );
    expect(operations).toMatch(/body\s*\{[^}]*min-width: 0;/);
    expect(operations).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation-iteration-count: 1 !important;/,
    );
  });

  it("keeps the Clarity operations nav in a wrapping two-column mobile grid", () => {
    const breakpointStart = operations.indexOf("@media (max-width: 1180px)");
    const breakpointEnd = operations.indexOf(
      "@media (max-width: 760px)",
      breakpointStart,
    );
    const mobileBreakpoint = operations.slice(breakpointStart, breakpointEnd);
    expect(mobileBreakpoint).toMatch(
      /\.clarity-shell \.sidebar-nav \{[^}]*display: grid;[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);[^}]*min-width: 0;[^}]*gap: 5px;[^}]*overflow: visible;/s,
    );
    expect(mobileBreakpoint).toMatch(
      /\.clarity-shell \.sidebar-nav a \{[^}]*min-width: 0;[^}]*min-height: 44px;[^}]*white-space: normal;/s,
    );
    expect(mobileBreakpoint).toMatch(
      /\.clarity-shell \.sidebar-nav a > svg \{[^}]*flex: 0 0 auto;/s,
    );
    expect(mobileBreakpoint).toMatch(
      /\.clarity-shell \.sidebar-nav a > span \{[^}]*min-width: 0;/s,
    );
    expect(mobileBreakpoint).not.toMatch(
      /\.clarity-shell \.sidebar-nav \{[^}]*overflow-x:/s,
    );
  });
});
