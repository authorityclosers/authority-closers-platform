import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";

import GlobalError from "./global-error";

// The test robot, 31 Oct 2026: offline, axe found Next's bare error document
// with no title and no language. The app's own has both, and a retry.
it("is a whole page with a title, its language and a retry", () => {
  const html = renderToString(
    <GlobalError error={new Error("fictional")} reset={() => {}} />,
  );
  expect(html).toMatch(/<html[^>]* lang="en"/);
  expect(html).toContain("<title>Sales X-Ray · Authority Closers</title>");
  expect(html).toContain("This screen didn’t load");
  expect(html).toContain("Try again");
});

it("draws its one filled action in the family deep green, white words in both themes", () => {
  // The QA robot, 8 Nov 2026: Go to Home was ink on surface, a white pill in
  // dark. v1.98: the teal turned a light mint with dark words in dark, so it
  // takes the family's deep-green pill, as every other main button.
  const css = readFileSync(
    join(process.cwd(), "app/error-page.module.css"),
    "utf8",
  );
  const primary = css.match(/\n\.primary \{([^}]*)\}/)?.[1] ?? "";
  expect(primary).toContain("background: var(--sx-gloss);");
  expect(primary).toContain("color: var(--sx-gloss-ink);");
  expect(primary).not.toContain("--lx-ink");
});
