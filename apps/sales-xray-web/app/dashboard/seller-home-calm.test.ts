import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * Home stays calm (Dipak's 3-day list, 3 Nov 2026: "it shouldn't look this
 * coloured") in his own design (owner, 4 Nov 2026: "this is what he is
 * expecting"): white tiles and cards with a 1 px line, no shadows, medium
 * weights, one solid teal (the Call).
 */
const read = (path: string) => readFileSync(join(process.cwd(), path), "utf8");
const css = read("app/dashboard/seller-home.module.css");

const rule = (source: string, selector: string) => {
  const at = source.indexOf(`\n${selector} {`);
  return at < 0 ? "" : source.slice(at, source.indexOf("}", at));
};

it("has no gradient, glass, blur or shadows on its blocks", () => {
  expect(css).not.toMatch(/gradient/);
  expect(css).not.toMatch(/backdrop-filter/);
  for (const selector of [".card", ".next", ".pending", ".taskList .taskRow"])
    expect(rule(css, selector)).not.toMatch(/box-shadow/);
});

it("draws the tiles and the next card as Dipak does: white, a 1 px line", () => {
  for (const selector of [".card", ".next"]) {
    expect(rule(css, selector)).toMatch(/border: 1px solid var\(--sx-line\)/);
    expect(rule(css, selector)).toMatch(/background: var\(--sx-surface\)/);
  }
});

it("fills with solid colour only a done tick and the swipe actions; the Call is the Call pill", () => {
  const coloured = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter(([, , body]) =>
      /background:\s*var\(--(sx|lx)-(accent|teal|closing|success|bad|good|warm)\)/.test(
        body,
      ),
    )
    .map(([, selector]) => selector.trim());
  for (const selector of coloured)
    expect(selector).toMatch(/:checked|\.swipeBack/);
  const lens = read("app/ui/call-lens/call-lens.module.css");
  expect(rule(lens, ".capsule")).toMatch(/background: var\(--sx-call-fill\)/);
});

it("keeps Dipak's 32 px figures at medium weight in full ink, and lets the words wrap rather than cut", () => {
  expect(rule(css, ".card strong")).toMatch(/font-size: var\(--sx-text-3xl\)/);
  expect(rule(css, ".card strong")).toMatch(/font-weight: 500/);
  expect(rule(css, ".card strong")).not.toMatch(/color/);
  // Judges, 4 Nov 2026: "Follow-ups t…" at 130 % and 200 % text lost its meaning.
  for (const words of [".cardLabel", ".cardNote"]) {
    expect(rule(css, words)).not.toMatch(/nowrap|ellipsis/);
    expect(rule(css, words)).toMatch(/overflow-wrap: anywhere/);
  }
});

it("keeps extreme data inside its card and row, and the calm side's keyboard focus ring", () => {
  // The test robot, 3 Nov 2026: a 13-digit number over the next tile, a long name cut
  // off by its row, and no focus ring on the chosen side.
  expect(rule(css, ".card strong")).toMatch(/overflow-wrap: anywhere/);
  expect(rule(css, ".rowText")).toMatch(
    /grid-template-columns: minmax\(0, 1fr\)/,
  );
  const selector = read("app/ui/side-selector.module.css");
  expect(selector).toMatch(
    /\[data-tone="calm"\] \.option\[aria-checked="true"\]:focus-visible \{\s*box-shadow: var\(--sx-focus-ring\)/,
  );
});

it("keeps the Call's 56 px pill and Home's compact rhythm", () => {
  expect(read("app/ui/slots/slot-layout.module.css")).toMatch(
    /\.slots\[data-rhythm="compact"\] \{\s*gap: 8px;/,
  );
  const lens = read("app/ui/call-lens/call-lens.module.css");
  expect(rule(lens, ".capsule")).toMatch(/min-height: 56px/);
  expect(lens).not.toMatch(/::before/);
});

it("writes every label in sentence case, never in capitals", () => {
  // ux-audit, 3 Nov 2026: Dipak's picture says "Next action", not "NEXT".
  expect(css).not.toMatch(/uppercase/);
});
