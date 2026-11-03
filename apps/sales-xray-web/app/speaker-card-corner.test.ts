import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * The test robot, 855ed149 (3 Nov 2026): on a computer the floating "Did we
 * get the speakers right?" card sat on Report a problem and the report's
 * rail. It keeps left of both: 72 px from the right at least (Report a
 * problem is 40 px wide, 20 px from the corner) and the rail's own room.
 */
const css = (path: string) =>
  readFileSync(join(process.cwd(), "app", path), "utf8");

it("keeps the speakers card left of Report a problem and the rail", () => {
  const speaker = css("speaker.module.css");
  const at = speaker.indexOf(".detected {");
  const card = speaker.slice(at, speaker.indexOf("}", at));
  expect(card).toContain("position: fixed;");
  expect(card).toMatch(
    /right: max\(\s*72px,\s*env\(safe-area-inset-right, 0px\),\s*var\(--sx-rail-room, 0px\)\s*\);/,
  );
  const corner = css("bug-report/bug-report.module.css");
  expect(corner).toMatch(
    /\.corner \{\s*position: fixed;\s*z-index: 40;\s*right: 20px;\s*bottom: 20px;/,
  );
  expect(corner).toMatch(/\.cornerButton \{[^}]*width: 40px;/);
});
