import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * A call's title keeps room on a phone: beside it sit only Transcript and the
 * menu, and the lead opens from its name in the facts row (simplify pass,
 * owner approved 2 Nov 2026; before, Prospect's Information pushed the
 * actions onto a row of their own).
 */
const css = readFileSync(
  join(process.cwd(), "app", "acquisition-studio.module.css"),
  "utf8",
);

it("keeps the call's title and its two actions on one row on a phone", () => {
  const row = css.search(
    /\.reportHeader\s*\{\s*grid-template-columns: minmax\(0, 1fr\) auto;\s*grid-template-areas:\s*"title actions"\s*"meta meta";/,
  );
  const phone = css.lastIndexOf("@media (max-width: 760px) {", row);
  expect(row).toBeGreaterThan(-1);
  expect(phone).toBeGreaterThan(-1);
  // Inside the phone layout's own block: the next block starts after it.
  expect(css.indexOf("\n}\n", phone)).toBeGreaterThan(row);
  // Nothing stacks the actions under the title any more.
  expect(css).not.toContain("data-report-lead-action");
});
