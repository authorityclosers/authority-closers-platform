import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * Home stays calm (Dipak's 3-day list, 3 Nov 2026: "it shouldn't look this
 * coloured"): flat, neutral surfaces, one accent colour, no glass.
 */
const css = readFileSync(
  join(process.cwd(), "app/dashboard/seller-home.module.css"),
  "utf8",
);

it("has no gradient, glass, blur or layered shadows", () => {
  expect(css).not.toMatch(/gradient/);
  expect(css).not.toMatch(/backdrop-filter/);
  expect(css).not.toMatch(/box-shadow:\s*\n\s*inset/);
});

it("fills with colour only the big button, a done tick and the swipe actions", () => {
  const coloured = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, , body]) =>
      /background:[^;]*--(sx|lx)-(accent|teal|closing|success|bad|good|warm)/.test(
        body,
      ),
    )
    .map(([, selector]) => selector.trim());
  expect(coloured.length).toBeGreaterThan(0);
  for (const selector of coloured)
    expect(selector).toMatch(/\.callNow|:checked|\.swipeBack/);
});
