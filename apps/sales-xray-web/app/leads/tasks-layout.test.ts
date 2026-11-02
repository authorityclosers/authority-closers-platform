import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * A task's title is never cut on a phone (the test robot, a95ec3bf and
 * d1aa3a23, 1 Nov 2026): beside its due time and Later and Done it had 77 px.
 * A narrow list puts the due time under the title.
 */
const css = readFileSync(
  join(process.cwd(), "app", "leads", "tasks.module.css"),
  "utf8",
);

it("measures the list the rows sit in", () => {
  expect(css).toMatch(/\.list \{[^}]*container: tasks-list \/ inline-size;/);
});

it("puts the due time under the title in a narrow list", () => {
  const at = css.indexOf("@container tasks-list (max-width: 30em) {");
  expect(at).toBeGreaterThan(-1);
  const narrow = css.slice(at, css.indexOf("\n}\n", at));
  expect(narrow).toMatch(
    /\.row \{[^}]*grid-template-columns: 32px minmax\(0, 1fr\);/,
  );
  expect(narrow).toMatch(/\.row time \{[^}]*grid-column: 2;/);
});
