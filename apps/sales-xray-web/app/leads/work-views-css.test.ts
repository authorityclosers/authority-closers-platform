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

// Owner bug 197 (10 Nov 2026): in Select, the Call band covered the ticked
// leads' bar and its buttons. While the bar is up, the band steps aside.
it("puts the Call band aside while leads are being selected", () => {
  expect(css).toMatch(
    /\.splitList:has\(\[data-select-bar\]\) \.callBand \{\s*display: none;/,
  );
  const bar = readFileSync(
    join(process.cwd(), "app/leads/delete-leads.tsx"),
    "utf8",
  );
  expect(bar).toMatch(/aria-label="Selected leads"\s*data-select-bar=""/);
});
