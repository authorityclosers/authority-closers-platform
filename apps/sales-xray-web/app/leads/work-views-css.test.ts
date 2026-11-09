import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Owner bug 165 (3 Nov 2026, his OnePlus): at large text, Leads' view tabs ran
// past their row on a phone. There they step down to fit the row, which is
// their measure; at a phone's own text size they are as before.
const css = readFileSync(
  join(process.cwd(), "app/leads/work-views.module.css"),
  "utf8",
);

it("keeps the view tabs within their row on a phone, at any text size", () => {
  expect(css).toMatch(
    /\[aria-label="Work views"\] \[role="tab"\] \{\s*font-size: min\(var\(--sx-text-sm\), 4\.5cqi\);/,
  );
  expect(css).toMatch(
    /:has\(> \[role="tablist"\]\[aria-label="Work views"\]\) \{\s*container-type: inline-size;/,
  );
});
