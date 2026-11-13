import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const css = readFileSync(
  join(process.cwd(), "app/leads/leads.module.css"),
  "utf8",
);
const rule = (selector: RegExp) =>
  css.match(new RegExp(`\\n${selector.source}\\s*\\{([^}]*)\\}`))?.[1] ?? "";

// Redmi QA batch 8 (13 Nov 2026): in Filter Leads, "Show as" was smaller and
// greyer than the rows around it, with no line under it. It is a row like them.
it("sets Show as as one of the sheet's rows", () => {
  const row = rule(/\.sheetLayout/);
  expect(row).toMatch(/min-height:\s*52px/);
  expect(row).toMatch(/padding:\s*0 4px/);
  expect(row).toMatch(/border-bottom:\s*1px solid var\(--sx-line\)/);
  expect(row).toMatch(/color:\s*var\(--sx-ink\)/);
  expect(row).toMatch(/font-size:\s*var\(--sx-text-md\)/);
  expect(row).toMatch(/font-weight:\s*600/);
});

// ...and an open list (Sort) outweighed its heading: its choices were the
// heading's size, the one picked marked by a thin check only.
it("keeps an open list's choices under their heading", () => {
  const option = rule(/\.filterForm \[data-mode="inline"\] \[role="option"\]/);
  expect(option).toMatch(/font-size:\s*var\(--sx-text-sm\)/);
  expect(option).toMatch(/font-weight:\s*400/);
  const picked = rule(
    /\.filterForm \[data-mode="inline"\] \[role="option"\]\[aria-selected="true"\]/,
  );
  expect(picked).toMatch(/font-weight:\s*600/);
  expect(picked).toMatch(/background:\s*var\(--sx-fill-soft\)/);
});
