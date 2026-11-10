import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Redmi QA G3 (10 Nov 2026): in the phone app, Remind me's grab line was a big
// grey block. Its colour was clipped to the grip's content box, which the
// phone's view didn't do, so the whole 124 x 21 px grip was grey. The line is
// now drawn on its own, 44 x 5, inside the same grip.
const css = readFileSync(
  join(process.cwd(), "app/leads/leads.module.css"),
  "utf8",
);

it("draws the sheet's grab line on its own, never by clipping the grip's colour", () => {
  const grip = css.match(/\n\.grabber\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(grip).not.toMatch(/background/);
  expect(grip).toMatch(/padding:\s*8px 40px/);
  const line = css.match(/\n\.grabber::before\s*\{([^}]*)\}/)?.[1] ?? "";
  expect(line).toMatch(/width:\s*44px/);
  expect(line).toMatch(/height:\s*5px/);
  expect(line).toMatch(/background:\s*var\(--sx-line-strong\)/);
  expect(css).not.toMatch(/background:[^;]*content-box/);
});
