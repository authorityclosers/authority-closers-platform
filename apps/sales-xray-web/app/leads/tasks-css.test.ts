import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Redmi QA (10 Nov 2026, 363 px at 130 %): Tasks' switch broke its names
// inside their words, "Overdue / 5", "Toda / y", "Upcomin / g". Each name
// stays whole on one line.
const css = readFileSync(
  join(process.cwd(), "app/leads/tasks.module.css"),
  "utf8",
);

it("keeps each Tasks list's name whole on one line", () => {
  const rule =
    css.match(/\n\.head > :first-child > button\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(rule).toMatch(/white-space:\s*nowrap/);
  expect(rule).not.toMatch(/overflow-wrap:\s*anywhere/);
});
