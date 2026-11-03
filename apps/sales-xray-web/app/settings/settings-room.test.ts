import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const css = (file: string) =>
  readFileSync(join(process.cwd(), "app", "settings", file), "utf8");

// The test robot, 3 Nov 2026: a 300-letter name ran out of "AI on your
// calls" (ef22ba6b, 52a335cd, 65a432d7).
it("lets a settings row's words break inside its card", () => {
  const rule = css("sections.module.css").match(/\.noteText \{[^}]*\}/)?.[0];
  expect(rule).toContain("overflow-wrap: anywhere");
});

// The test robot, 3 Nov 2026: Profile moved 0.13 as the profile arrived
// (b7b700e0), because its loading card was two rows tall.
it("holds the profile's room while it loads, on phones and computers", () => {
  const file = css("profile-details.module.css");
  expect(file).toMatch(/\.loading \{\s*min-height: 45em;/);
  expect(file).toMatch(
    /@media \(min-width: 761px\) \{\s*\.loading \{\s*min-height: 24\.5em;/,
  );
});
