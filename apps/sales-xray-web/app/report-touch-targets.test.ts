import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

/**
 * The call report's small controls reach a finger on touch screens (the test
 * robot, c9091f68, 2 Nov 2026: at 390 px the lead's name was 20 px tall and
 * the Report / Prospect / Coaching buttons 40 px). Each gets an invisible
 * area under (pointer: coarse) that makes it 44 px or more.
 */
const read = (name: string) =>
  readFileSync(join(process.cwd(), "app", name), "utf8");

const reach = (css: string, selector: string) => {
  const touch = css.indexOf("@media (pointer: coarse) {");
  const rule = css.indexOf(`${selector}::after {`, touch);
  expect(touch).toBeGreaterThan(-1);
  expect(rule).toBeGreaterThan(touch);
  const inset = /inset: -(\d+)px 0;/.exec(
    css.slice(rule, css.indexOf("}", rule)),
  );
  return Number(inset?.[1] ?? 0);
};

it("gives the lead's name a 44 px target on touch screens", () => {
  expect(
    20 + 2 * reach(read("report-header.module.css"), ".lead"),
  ).toBeGreaterThanOrEqual(44);
  // The facts row scrolls sideways and clips: it reaches 8 px out, unmoved.
  expect(read("acquisition-studio.module.css")).toMatch(
    /@media \(max-width: 760px\) and \(pointer: coarse\) \{\s*\.app\.app\[data-stage="report"\] \.reportMetadata \{\s*padding-block: 8px;\s*margin-block: -8px;/,
  );
});

it("gives the Report / Prospect / Coaching buttons a 44 px target on touch screens", () => {
  expect(
    40 + 2 * reach(read("report-modes.module.css"), ".toolbar > button"),
  ).toBeGreaterThanOrEqual(44);
});
