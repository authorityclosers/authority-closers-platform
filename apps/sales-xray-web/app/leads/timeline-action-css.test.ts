import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Tester report 211 (production 1.58, 14 Nov 2026): on a 363 px phone a call's
// "View report" sat in its own column beside the entry, squeezing the words
// into a narrow column five lines tall. On a phone it now goes under them.
const css = readFileSync(
  join(process.cwd(), "app/leads/lead-page.module.css"),
  "utf8",
);

it("puts a history row's action under its words on a phone, never beside them", () => {
  const phone =
    css.match(
      /@media \(max-width: 899\.98px\) \{\s*\.tlRow \{([^}]*)\}\s*\.tlAction \{([^}]*)\}/,
    ) ?? [];
  expect(phone[1]).toMatch(/grid-template-columns:\s*40px minmax\(0, 1fr\);/);
  expect(phone[2]).toMatch(/grid-column:\s*2;/);
  expect(phone[2]).toMatch(/justify-self:\s*start;/);
  // A computer keeps it beside the words, level with the disc.
  const row = css.match(/\n\.tlRow \{([^}]*)\}/)?.[1] ?? "";
  expect(row).toMatch(/grid-template-columns:\s*40px minmax\(0, 1fr\) auto;/);
});
