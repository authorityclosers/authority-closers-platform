import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * A call's title keeps room on a phone (the test robot, 2 Nov 2026: at 390 px
 * Prospect's Information, Transcript and the menu left the title about 25 px,
 * a letter a line). With the lead's action, the title takes its own row and
 * the actions sit under it.
 */
const css = readFileSync(
  join(process.cwd(), "app", "acquisition-studio.module.css"),
  "utf8",
);

it("gives the call's title its own row on a phone when the lead's action joins", () => {
  const stacked = css.search(
    /\.reportHeader:has\(\s*\[data-report-lead-action\]\s*\)\s*\{\s*grid-template-columns: minmax\(0, 1fr\);\s*grid-template-areas:\s*"title"\s*"actions"\s*"meta";/,
  );
  const phone = css.lastIndexOf("@media (max-width: 760px) {", stacked);
  expect(stacked).toBeGreaterThan(-1);
  expect(phone).toBeGreaterThan(-1);
  // Inside the phone layout's own block: the next block starts after it.
  expect(css.indexOf("\n}\n", phone)).toBeGreaterThan(stacked);
});
