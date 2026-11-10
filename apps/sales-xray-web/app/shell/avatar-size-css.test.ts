import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// The owner (10 Nov 2026, his OnePlus): the top-left profile picture "looks too
// small". It fills most of its 44 px box, 40 px, so the bar around it never moves.
const css = readFileSync(
  join(process.cwd(), "app/shell/lightbox-shell.module.css"),
  "utf8",
);

it("draws the phone header's profile picture at 40 px in its 44 px box", () => {
  expect(css).toMatch(/\.mobileAvatar \{[^}]*width: 44px;[^}]*height: 44px;/);
  expect(css).toMatch(
    /\.mobileAvatar > span \{\s*display: grid;\s*width: 40px;\s*height: 40px;/,
  );
});
