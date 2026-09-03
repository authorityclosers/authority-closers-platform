import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PublicCatalogHome } from "../components/public-catalog-home";

describe("premium public catalog home", () => {
  it("renders the selected product direction without invented catalog state", () => {
    const html = renderToStaticMarkup(createElement(PublicCatalogHome));

    expect(html).toContain("Practice what changes your");
    expect(html).toContain("Watch");
    expect(html).toContain("Reflect");
    expect(html).toContain("Implement");
    expect(html).toContain("Review");
    expect(html).toContain("Improve");
    expect(html).toContain("Loading published programs");
    expect(html).toContain("dipak-learning-hero-v1.png");
    expect(html).not.toContain("65% complete");
    expect(html).not.toContain("weekly activity");
    expect(html).not.toContain("Live Coaching Session");
    expect(html).not.toContain("Module 1 · Shift");
    expect(html).not.toContain("The closer mindset");
  });

  it("keeps the real catalog API and responsive visual contract explicit", () => {
    const componentSource = readFileSync(
      new URL("../components/public-catalog-home.tsx", import.meta.url),
      "utf8",
    );
    const pageSource = readFileSync(
      new URL("../page.tsx", import.meta.url),
      "utf8",
    );
    const styles = readFileSync(
      new URL("../styles.css", import.meta.url),
      "utf8",
    );

    expect(componentSource).toMatch(/api\s*\.listPrograms\(50/);
    expect(componentSource).toContain("program.title");
    expect(componentSource).toContain("program.version_number");
    expect(componentSource).toContain("program.published_at");
    expect(componentSource).toContain("/media/dipak-learning-hero-v1.png");
    expect(componentSource).toContain("ac-public-program-grid--single");
    expect(componentSource).toContain("ac-public-program-card--featured");
    expect(componentSource).not.toContain("Module 1 · Shift");
    expect(componentSource).not.toContain("The closer mindset");
    expect(pageSource).toContain('from "./components/public-catalog-home"');
    expect(styles).toContain(".ac-public-hero");
    expect(styles).toContain(".ac-public-hero__visual");
    expect(styles).toContain(".ac-public-program-grid--single");
    expect(styles).toContain(".ac-public-program-card--featured");
    expect(styles).toContain("@media (max-width: 1040px)");
    expect(styles).toContain("@media (max-width: 760px)");
    expect(styles).toContain("@media (max-width: 430px)");
    expect(styles).toContain("overflow-wrap: anywhere;");
    expect(styles).toContain("env(safe-area-inset-bottom)");
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(styles).toContain(
      ".site-frame:not(.site-frame--learner) :focus-visible",
    );
    expect(styles).toContain(".ac-public-button:focus-visible");
  });

  it("guarantees intrinsic sizing and overflow-wrap anywhere without global root overflow masking", () => {
    const styles = readFileSync(
      new URL("../styles.css", import.meta.url),
      "utf8",
    );
    const clarityStyles = readFileSync(
      new URL("../learner-clarity.css", import.meta.url),
      "utf8",
    );

    function cssRule(css: string, selector: string): string {
      const target = `\n${selector} {`;
      let index = css.indexOf(target);
      if (index === -1) {
        index = css.indexOf(`\r\n${selector} {`);
      }
      if (index === -1) {
        index = css.indexOf(`${selector} {`);
      }
      if (index === -1) {
        throw new Error(`Missing CSS rule for selector: ${selector}`);
      }
      const openBrace = css.indexOf("{", index);
      const closeBrace = css.indexOf("}", openBrace);
      if (openBrace === -1 || closeBrace === -1) {
        throw new Error(`Malformed CSS block for selector: ${selector}`);
      }
      return css.slice(openBrace + 1, closeBrace);
    }

    // Explicitly verify global roots do NOT use overflow-x clipping or max-width masking
    const htmlRule = cssRule(styles, "html");
    expect(htmlRule).not.toContain("overflow");
    expect(htmlRule).not.toContain("max-width");
    expect(htmlRule).toContain("scroll-behavior: smooth");

    const bodyRule = cssRule(styles, "body");
    expect(bodyRule).not.toContain("overflow");
    expect(bodyRule).not.toContain("max-width");
    expect(bodyRule).toContain("min-width: 320px");

    const siteFrameRule = cssRule(styles, ".site-frame");
    expect(siteFrameRule).not.toContain("overflow");
    expect(siteFrameRule).not.toContain("max-width");
    expect(siteFrameRule).toContain("min-height: 100vh");

    const publicShellRule = cssRule(
      styles,
      ".site-frame:not(.site-frame--learner)",
    );
    expect(publicShellRule).not.toContain("overflow");
    expect(publicShellRule).not.toContain("max-width");

    const learnerShellRule = cssRule(clarityStyles, ".site-frame--learner");
    expect(learnerShellRule).not.toContain("overflow");
    expect(learnerShellRule).not.toContain("max-width");
    expect(clarityStyles).not.toContain(".site-frame--learner :is(h1, h2");

    // Scoped decorative containment is limited to smallest elements
    const heroVisualRule = cssRule(styles, ".ac-public-hero__visual");
    expect(heroVisualRule).toContain("overflow: hidden");
    expect(heroVisualRule).toContain("min-width: 0");

    const cardRule = cssRule(styles, ".ac-public-program-card");
    expect(cardRule).toContain("overflow: hidden");
    expect(cardRule).toContain("min-width: 0");

    const cardImageRule = cssRule(styles, ".ac-public-program-card__image");
    expect(cardImageRule).toContain("overflow: hidden");
    expect(cardImageRule).toContain("min-width: 0");

    // Intrinsic sizing and word breaking on content
    const cardBodyH3 = cssRule(styles, ".ac-public-program-card__body h3");
    expect(cardBodyH3).toContain("overflow-wrap: anywhere");
    expect(cardBodyH3).toContain("word-break: break-word");
    expect(cardBodyH3).toContain("min-width: 0");
    expect(cardBodyH3).toContain("max-width: 100%");

    const cardBody = cssRule(styles, ".ac-public-program-card__body");
    expect(cardBody).toContain("min-width: 0");
    expect(cardBody).toContain("max-width: 100%");
    expect(cardBody).toContain("overflow-wrap: anywhere");

    const heroH1 = cssRule(styles, ".ac-public-hero h1");
    expect(heroH1).toContain("overflow-wrap: anywhere");
    expect(heroH1).toContain("word-break: break-word");
    expect(heroH1).toContain("min-width: 0");

    const sectionH2 = cssRule(styles, ".ac-public-section-heading h2");
    expect(sectionH2).toContain("overflow-wrap: anywhere");
    expect(sectionH2).toContain("word-break: break-word");
    expect(sectionH2).toContain("min-width: 0");
  });
});
