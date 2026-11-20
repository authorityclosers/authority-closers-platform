import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

const css = readFileSync(
  join(process.cwd(), "app/dashboard/team-floor.module.css"),
  "utf8",
);
// The OnePlus block: phones up to 375 px.
const phone = css.slice(css.lastIndexOf("@media (max-width: 375px)"));
const rule = (selector: RegExp) =>
  phone.match(new RegExp(`\\n\\s*${selector.source}\\s*\\{([^}]*)\\}`))?.[1] ??
  "";

// Report 220 (the owner's OnePlus, 363 px, 15 Nov 2026): with the phone's
// large text the team chips' words ran out of their third of the row, over
// the next chip and past the card. The pill keeps them and grows with the
// text; the word ends in "…".
it("keeps a team chip's words inside its pill at 363 px with large text", () => {
  const chip = rule(/\.workLine \.chip/);
  expect(chip).toMatch(/overflow:\s*hidden/);
  expect(chip).toMatch(/min-height:\s*26px/);
  expect(chip).toMatch(/height:\s*auto/);
  expect(rule(/\.workLine \.chip > svg/)).toMatch(/flex:\s*none/);
  const word = rule(/\.workLine \.chipWord/);
  expect(word).toMatch(/min-width:\s*0/);
  expect(word).toMatch(/text-overflow:\s*ellipsis/);
});
