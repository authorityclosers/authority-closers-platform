import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Orchestrator (10 Nov 2026): on a seller's Home at 130 % text, "Talk ·
// recordings" and "Follow-ups done" still wrapped beside their rings. Each
// label runs the cell's whole width over its ring and number.
const css = readFileSync(
  join(process.cwd(), "app/dashboard/smart-home.module.css"),
  "utf8",
);

it("lays each Done today label over its ring and number", () => {
  const cell = css.match(/\n\.done a\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(cell).toMatch(/"label label"\s*"ring value"/);
  expect(css).toMatch(/\.doneLabel\s*\{[^}]*grid-area:\s*label/);
  expect(css).toMatch(/\.doneValue\s*\{[^}]*grid-area:\s*value/);
});
