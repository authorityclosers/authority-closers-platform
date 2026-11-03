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

const rule = (selector: string) => {
  const at = css.indexOf(`\n${selector} {`);
  return at < 0 ? "" : css.slice(at, css.indexOf("}", at));
};

it("keeps the Today tiles at Dipak's height: one-line words and a 24 px number", () => {
  // ux-audit, 3 Nov 2026: 130 px tiles put the next call under the tab bar.
  expect(rule(".card")).not.toMatch(/min-height/);
  expect(rule(".card strong")).toMatch(/font-size: 24px/);
  for (const words of [".cardLabel", ".cardNote"])
    expect(rule(words)).toMatch(/white-space: nowrap/);
});

it("keeps extreme data inside its tile and row, and the calm side's keyboard focus ring", () => {
  // The test robot, 3 Nov 2026: a 13-digit number over the next tile, a long name cut
  // off by its row, and no focus ring on the chosen side.
  expect(rule(".card strong")).toMatch(/overflow-wrap: anywhere/);
  expect(rule(".rowText")).toMatch(/grid-template-columns: minmax\(0, 1fr\)/);
  const selector = readFileSync(
    join(process.cwd(), "app/ui/side-selector.module.css"),
    "utf8",
  );
  expect(selector).toMatch(
    /\[data-tone="calm"\] \.option\[aria-checked="true"\]:focus-visible \{\s*box-shadow: var\(--sx-focus-ring\)/,
  );
});

it("keeps the next call above the fold beside an owner's revenue bar and a waiting answer", () => {
  // v1.36 phone QA on the Redmi 13, 3 Nov 2026: the Call button 70 px under the tab bar.
  expect(rule(".me")).toMatch(/gap: 12px/);
  expect(rule(".head")).toMatch(/min-height: 24px/);
  expect(rule(".callNow")).toMatch(/min-height: 48px/);
  expect(rule(".card")).toMatch(/padding: 6px 12px/);
  expect(css).toMatch(
    /\.next \{\s*align-items: center;\s*gap: 10px;\s*padding: 12px;/,
  );
  const home = readFileSync(
    join(process.cwd(), "app/dashboard/sales-home.module.css"),
    "utf8",
  );
  expect(home).toMatch(
    /@media \(max-width: 1023px\) \{\s*\.home:has\(> \[data-mode="mine"\]\) \{\s*gap: 12px;/,
  );
});

it("writes the next card's label in sentence case, never in capitals", () => {
  // ux-audit, 3 Nov 2026: Dipak's picture says "Next cold call".
  expect(rule(".kicker")).not.toMatch(/text-transform/);
  expect(css).not.toMatch(/uppercase/);
});
