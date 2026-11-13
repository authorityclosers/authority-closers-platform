import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// ux-audit, the Redmi pass (10 Nov 2026): on Calls, "Log work calls by
// themselves" ran straight into "Only calls with your leads...", one line of
// words. The title has its own line and what it does goes under it, on Leads'
// compact stack too.
const css = readFileSync(
  join(process.cwd(), "app/leads/leads.module.css"),
  "utf8",
);

it("puts the work-calls card's title on its own line", () => {
  const span = css.match(/\n\.phoneLogCard > span\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(span).toMatch(/display:\s*grid/);
  const compact =
    css.match(/\.compactStack \.phoneLogCard > span\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(compact).not.toMatch(/display/);
});

// Redmi QA (13 Nov 2026): on Calls the title came out smaller than its line.
it("sets the work-calls card's title a step above its line", () => {
  const title =
    css.match(/\n\.phoneLogCard > span > strong\s*\{([^}]*)\}/)?.[1] ?? "";
  const line =
    css.match(/\n\.phoneLogCard > span > small\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(title).toMatch(/font-size:\s*var\(--sx-text-sm\)/);
  expect(line).toMatch(/font-size:\s*var\(--sx-text-xs\)/);
});
