import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const styles = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

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
