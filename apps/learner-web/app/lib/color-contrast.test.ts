import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const styles = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
const themeStyles = readFileSync(
  new URL("../theme.css", import.meta.url),
  "utf8",
);

function colorToken(name: string): string {
  const match = styles.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, "i"));

  if (!match?.[1]) {
    throw new Error(`Missing hex color token --${name}`);
  }

  return match[1];
}

function luminance(hex: string): number {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    ?.map((channel) => Number.parseInt(channel, 16) / 255);

  if (!channels || channels.length !== 3) {
    throw new Error(`Invalid hex color ${hex}`);
  }

  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );

  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(foreground: string, background: string): number {
  const foregroundLuminance = luminance(foreground);
  const backgroundLuminance = luminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);

  return (lighter + 0.05) / (darker + 0.05);
}

function themeBlock(theme: "light" | "dark"): string {
  const selector = theme === "dark" ? 'html\\[data-theme="dark"\\]' : "html";
  const match = themeStyles.match(new RegExp(`${selector}\\s*\\{([^}]*)\\}`));

  if (!match?.[1]) {
    throw new Error(`Missing ${theme} theme token block`);
  }

  return match[1];
}

function themeToken(theme: "light" | "dark", name: string): string {
  const match = themeBlock(theme).match(
    new RegExp(`--theme-${name}:\\s*(#[0-9a-f]{6})`, "i"),
  );

  if (!match?.[1]) {
    throw new Error(`Missing ${theme} theme token --theme-${name}`);
  }

  return match[1];
}

function selectorBlock(selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styles.match(
    new RegExp(`${escapedSelector}[^\\{]*\\{([^}]*)\\}`),
  );

  if (!match?.[1]) {
    throw new Error(`Missing selector block ${selector}`);
  }

  return match[1];
}

function themeSelectorBlock(selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = themeStyles.match(
    new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`),
  );

  if (!match?.[1]) {
    throw new Error(`Missing theme selector block ${selector}`);
  }

  return match[1];
}

function expectSemanticPairing({
  selector,
  foreground,
  background,
  minimum = 4.5,
}: {
  selector: string;
  foreground: string;
  background: string;
  minimum?: number;
}): void {
  const block = selectorBlock(selector);

  expect(block, `${selector} foreground`).toContain(
    `color: var(--${foreground})`,
  );

  const ratio = contrastRatio(colorToken(foreground), colorToken(background));
  expect(ratio, `--${foreground} on --${background}`).toBeGreaterThanOrEqual(
    minimum,
  );
}

describe("learner color tokens", () => {
  it("defines the complete semantic appearance token contract in both themes", () => {
    const requiredTokens = [
      "canvas",
      "surface",
      "surface-raised",
      "surface-subtle",
      "input",
      "text",
      "text-muted",
      "text-subtle",
      "text-inverse",
      "border",
      "border-strong",
      "action",
      "action-hover",
      "action-text",
      "focus",
      "disabled-surface",
      "disabled-text",
      "info-surface",
      "info-text",
      "success-surface",
      "success-text",
      "warning-surface",
      "warning-text",
      "danger-surface",
      "danger-text",
    ];

    for (const theme of ["light", "dark"] as const) {
      for (const token of requiredTokens) {
        expect(themeToken(theme, token)).toMatch(/^#[0-9a-f]{6}$/i);
      }
    }
  });

  it("keeps text, actions, disabled labels, and state text legible", () => {
    const pairings = [
      ["text", "canvas"],
      ["text", "surface"],
      ["text-muted", "surface"],
      ["action-text", "action"],
      ["disabled-text", "disabled-surface"],
      ["info-text", "info-surface"],
      ["success-text", "success-surface"],
      ["warning-text", "warning-surface"],
      ["danger-text", "danger-surface"],
    ] as const;

    for (const theme of ["light", "dark"] as const) {
      for (const [foreground, background] of pairings) {
        expect(
          contrastRatio(
            themeToken(theme, foreground),
            themeToken(theme, background),
          ),
          `${theme} --theme-${foreground} on --theme-${background}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps light Emerald and Amber primary button text at WCAG AA", () => {
    const lightAccentTokens = {
      emerald: { action: "#047857", hover: "#065f46" },
      amber: { action: "#b45309", hover: "#92400e" },
    } as const;

    for (const [accent, tokens] of Object.entries(lightAccentTokens)) {
      const block = themeSelectorBlock(`html[data-accent="${accent}"]`);
      expect(block).toContain(`--theme-action: ${tokens.action}`);
      expect(block).toContain(`--theme-action-hover: ${tokens.hover}`);
      expect(
        contrastRatio("#ffffff", tokens.action),
        `${accent} action white text contrast`,
      ).toBeGreaterThanOrEqual(4.5);
      expect(
        contrastRatio("#ffffff", tokens.hover),
        `${accent} hover white text contrast`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("routes learner primary button hover through the selected appearance token", () => {
    const clarity = readFileSync(
      new URL("../learner-clarity.css", import.meta.url),
      "utf8",
    );

    expect(clarity).toContain(
      "background: var(--theme-action-hover, var(--color-cobalt-hover));",
    );
    expect(clarity).toContain("background: var(--theme-action, #155eef);");
    expect(clarity).toContain(
      "background: var(--theme-action-hover, #155eef);",
    );
  });

  it("disables learner animations without removing layout transforms", () => {
    expect(themeStyles).toContain(
      'html[data-reduced-motion="true"] .site-frame--learner *',
    );
    expect(themeStyles).toContain("animation: none !important;");
    expect(themeStyles).toContain("transition: none !important;");
    expect(themeStyles).toContain("scroll-behavior: auto !important;");
    expect(themeStyles).toContain(
      ".learner-help-chatbox__trigger:hover {\n  transform: none !important;",
    );
    expect(themeStyles).not.toContain(
      "*::after {\n  animation: none !important;\n  transition: none !important;\n  transform: none !important;",
    );
  });

  it("covers dark form, state, navigation, and mobile overflow regressions", () => {
    const requiredRules = [
      ":-webkit-autofill",
      ":disabled",
      ":focus-visible",
      ".site-header, .site-footer",
      ".surface-state--offline",
      ".surface-state:not(:has(.surface-state__body))",
      ".clarity-auth-mobile-header",
      ".clarity-onboarding-intro h1",
      ".learner-bottom-nav",
      '.learner-sidebar__item[aria-disabled="true"]',
      "overflow-wrap: anywhere",
      ".clarity-auth-card .consent-check a",
      "grid-template-columns: 35px minmax(0, 1fr)",
      "font-size: clamp(1.7rem, 8vw, 2.3rem)",
    ];

    for (const rule of requiredRules) {
      expect(themeStyles, `missing regression rule ${rule}`).toContain(rule);
    }
  });

  it("covers every live small-text surface pairing", () => {
    const pairings = [
      {
        selector: ".current-course-card .status-pill--neutral",
        foreground: "muted-on-ink",
        background: "ink",
      },
      {
        selector: ".first-win-card .kicker",
        foreground: "muted-on-clay",
        background: "clay",
      },
      {
        selector: ".first-win-card > p:not(.kicker)",
        foreground: "muted-on-clay",
        background: "clay",
      },
      {
        selector: ".first-win-card__footer",
        foreground: "muted-on-clay",
        background: "clay",
      },
      {
        selector: ".completion-next .kicker",
        foreground: "muted-on-clay",
        background: "clay",
      },
      {
        selector: ".completion-next > p:not(.kicker)",
        foreground: "muted-on-clay",
        background: "clay",
      },
      {
        selector: ".workspace-card--next .kicker",
        foreground: "muted-on-sage",
        background: "sage",
      },
      {
        selector: ".workspace-card--next > p:not(.kicker)",
        foreground: "muted-on-sage",
        background: "sage",
      },
      {
        selector: ".program-hero__aside .fact-grid dt",
        foreground: "muted-on-sage",
        background: "sage",
      },
      {
        selector: ".module-hero__aside p",
        foreground: "muted-on-sage",
        background: "sage",
      },
      {
        selector: ".review-banner p",
        foreground: "muted-on-sage",
        background: "sage",
      },
      {
        selector: ".module-card__prerequisite",
        foreground: "muted-on-sage",
        background: "paper-light",
      },
    ];

    for (const pairing of pairings) {
      expectSemanticPairing(pairing);
    }
  });

  it("uses a high-contrast focus color wherever focus crosses a dark surface", () => {
    const darkFocusSelectors = [
      ".current-course-card :focus-visible",
      ".closing-cta :focus-visible",
      ".video-preview :focus-visible",
    ];

    for (const selector of darkFocusSelectors) {
      expect(selectorBlock(selector), `${selector} outline`).toContain(
        "outline-color: var(--focus-on-dark)",
      );
    }

    const ratio = contrastRatio(colorToken("focus-on-dark"), colorToken("ink"));
    expect(ratio, "--focus-on-dark on --ink").toBeGreaterThanOrEqual(4.5);
  });

  it("retains the original neutral and olive token guardrails on light surfaces", () => {
    const foregrounds = ["muted-light", "acid-dark"];
    const surfaces = [
      "paper",
      "paper-deep",
      "paper-light",
      "acid",
      "sage",
      "clay",
      "sky",
    ];

    for (const foregroundName of foregrounds) {
      for (const surfaceName of surfaces) {
        const ratio = contrastRatio(
          colorToken(foregroundName),
          colorToken(surfaceName),
        );

        expect(
          ratio,
          `--${foregroundName} on --${surfaceName}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
