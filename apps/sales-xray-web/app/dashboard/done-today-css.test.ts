import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// The owner on a Redmi 13 (13 Nov 2026): the figures lacked symmetry. Each is
// one shape, its ring then its number with its name under it, all from the
// top, so a row's rings and numbers line up whichever name wraps (a name over
// the ring, 10 Nov, pushed a two-line name's ring and number down).
const css = readFileSync(
  join(process.cwd(), "app/dashboard/smart-home.module.css"),
  "utf8",
);

it("lays each Done today figure as its ring beside its number over its name", () => {
  const cell = css.match(/\n\.done a\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(cell).toMatch(/"ring value"\s*"ring label"/);
  expect(cell).toMatch(/align-items:\s*start/);
  expect(css).toMatch(/\.doneLabel\s*\{[^}]*grid-area:\s*label/);
  expect(css).toMatch(/\.doneValue\s*\{[^}]*grid-area:\s*value/);
});
