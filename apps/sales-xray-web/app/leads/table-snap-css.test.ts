import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const css = readFileSync(
  join(process.cwd(), "app/leads/leads-table.module.css"),
  "utf8",
);

// Redmi QA batch 8 (13 Nov 2026): on a phone the table's columns stopped half
// under the pinned name ("ast call", "ot called"). They snap at its edge.
it("snaps a phone's sideways table to whole columns at the pinned name", () => {
  const wrap =
    css.match(/\n\.wrap\[data-scroll\]\[data-snap\]\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(wrap).toMatch(/scroll-snap-type:\s*x mandatory/);
  expect(wrap).toMatch(/scroll-padding-inline-start:\s*var\(--pinned-w, 0px\)/);
  expect(css).toMatch(
    /\.wrap\[data-scroll\] \.table thead th\[data-column\]:not\(\[data-column="name"\]\)\s*\{\s*scroll-snap-align:\s*start;/,
  );
});
