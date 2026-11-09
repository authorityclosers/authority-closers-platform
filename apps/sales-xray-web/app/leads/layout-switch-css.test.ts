import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Owner bug 194 (9 Nov 2026, his OnePlus): in the Filter sheet, List | Table
// "does not work at all". A phone rule from when the switch also had words hid
// its icons, so on a phone both buttons were empty pills 16 px wide. The icons
// stay on every screen, and in the sheet each button is a whole 44 px tap.
const css = readFileSync(
  join(process.cwd(), "app/leads/leads.module.css"),
  "utf8",
);

it("never hides the List | Table switch's icons", () => {
  expect(css).not.toMatch(/\.layoutSwitch svg\s*\{\s*display:\s*none/);
});

it("gives the Filter sheet's List and Table each a 44 px tap", () => {
  const rule = css.match(/\.sheetLayout \.layoutSwitch button\s*\{([^}]*)\}/);
  expect(rule?.[1]).toMatch(/min-width:\s*44px/);
});
