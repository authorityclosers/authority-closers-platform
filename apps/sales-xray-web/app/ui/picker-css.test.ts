import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Owner bug 195 (9 Nov 2026, his OnePlus): "a little bit separation of heading
// and things under the drop-down". Open in a sheet, the choices sit in their
// own card under their heading.
const css = readFileSync(
  join(process.cwd(), "app/ui/picker.module.css"),
  "utf8",
);

it("sets an open list's choices apart from their heading in a sheet", () => {
  const rule = css.match(/\.root\[data-mode="inline"\] \.list \{([^}]*)\}/);
  expect(rule?.[1]).toMatch(/border: 1px solid var\(--sx-line\);/);
  expect(rule?.[1]).toMatch(/margin: 8px 0 12px;/);
});
