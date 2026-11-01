import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

// The sidebar's lit rows sit on the lit fill (.placePill, --sx-accent-soft),
// where the bare accent reads under 4.5:1 in light: 4.49:1 for a place row
// (axe on Leads, 31 Oct 2026) and 4.48:1 for New analysis, 3.91:1 under the
// pointer (the test robot, 125aed9b, 1 Nov 2026). Every lit row's name takes
// the same deeper accent, which reads 6.1:1 there.
const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "lightbox-shell.module.css"), "utf8");

function litColour(selector: string): string {
  const escaped = selector.replace(/[.[\]"=]/g, (c) => `\\${c}`);
  const rule = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  expect(rule, selector).not.toBeNull();
  const colour = rule![1].match(/(?:^|;|\s)color:\s*([^;]+);/);
  expect(colour, selector).not.toBeNull();
  return colour![1].trim();
}

it("gives New analysis, lit, the lit place rows' deeper accent", () => {
  const place = litColour('.place[aria-current="page"]');
  expect(place).toBe(
    "color-mix(in oklab, var(--sx-accent) 80%, var(--lx-ink))",
  );
  expect(litColour('.panelNew[aria-current="page"]')).toBe(place);
});
