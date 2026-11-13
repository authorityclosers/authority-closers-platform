import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const css = readFileSync(
  join(process.cwd(), "app/dashboard/smart-home.module.css"),
  "utf8",
);
const rule = (selector: RegExp) =>
  css.match(new RegExp(`\\n${selector.source}\\s*\\{([^}]*)\\}`))?.[1] ?? "";

// Seller Flow 1, F3 (13 Nov 2026): a row in Today's list opened its lead only
// from its words. The words' link covers the row; the tick and call mark sit
// above it, still their own taps.
it("opens the lead from anywhere on a Today's list row", () => {
  expect(rule(/\.row/)).toMatch(/position:\s*relative/);
  const cover = rule(/\.row \.title a::after/);
  expect(cover).toMatch(/position:\s*absolute/);
  expect(cover).toMatch(/inset:\s*0/);
  const mark = rule(/\.mark/);
  expect(mark).toMatch(/position:\s*relative/);
  expect(mark).toMatch(/z-index:\s*1/);
});
