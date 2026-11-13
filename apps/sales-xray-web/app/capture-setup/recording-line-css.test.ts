import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Redmi QA on the owner's production build, 13 Nov 2026 (363 px at 130 %):
// on Calls, "Fix" dropped onto a line of its own under "1 call today has no
// recording ·". The words wrap in their own column beside Fix.
const css = readFileSync(
  join(process.cwd(), "app/capture-setup/capture-setup.module.css"),
  "utf8",
);

it("keeps Fix at the end of the no-recording line, the words wrapping beside it", () => {
  const line = css.match(/\n\.missingLine p\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(line).toMatch(/display:\s*grid/);
  expect(line).toMatch(/grid-template-columns:\s*8px minmax\(0, 1fr\) auto/);
  expect(css).toMatch(
    /\.missingLine p > span\[aria-hidden="true"\]\s*\{\s*display:\s*none/,
  );
});
