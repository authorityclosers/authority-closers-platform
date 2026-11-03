import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// The test robot, 3 Nov 2026 (e8f1aa1b, d96d9818): at 360 px with text at
// 200 %, "Share with your admins" stayed on one line, 386 px wide, and held
// its card wider than the screen.
it("lets Coaching's action buttons wrap inside their card", () => {
  const css = readFileSync(
    join(process.cwd(), "app", "coaching", "coaching.module.css"),
    "utf8",
  );
  const rule = css.match(/\.actions > button,\s*\.actions > a \{[^}]*\}/)?.[0];
  expect(rule).toContain("max-width: 100%");
  expect(rule).toContain("white-space: normal");
});
