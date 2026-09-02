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
    expect(styles).toContain("env(safe-area-inset-bottom)");
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
