import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, it } from "vitest";

import baseline from "./type-scale-baseline.json";

/**
 * One type scale, kept (owner, 3 Nov 2026: the 25 sizes and 44 line heights were to be solved so
 * they can't come back; docs/product/native-feel-spec-20261103.md, framework L9). Every font size,
 * weight and line height in the app's and the kit's CSS is the scale's: sizes are --sx-text-* steps
 * (the ds scale aliases them; a cap or floor around a step; an avatar's initials sized to the
 * avatar), weights 400 and 500, line heights --sx-leading-* (1 for a box that hugs its glyphs, and
 * the Devanagari lift). The tokens themselves live in kit/tokens and are not scanned.
 *
 * A ratchet, like the colour one: a file may keep the off-scale values it had on 3 Nov 2026
 * (type-scale-baseline.json: line heights in rules that never set their own size) and never gain
 * one. When a file loses some, lower its number so it can't regress.
 */

const APP = join(process.cwd(), "app");
const KIT = join(process.cwd(), "../../packages/typescript/ui/src");

/** Named exceptions, each with its reason; they never count. */
const ALLOWED = new Set([
  // Dipak's 2 Nov 2026 target for the Today tiles: a 24 px number (orchestrator, 3 Nov 2026).
  "app/dashboard/seller-home.module.css | font-size: 24px",
  // The page header and footer a printed Report carries.
  "app/report-modes.module.css | font: 8pt sans-serif",
  // A phone bar's page name: its step, capped to fit its room on one line by its length
  // (Redmi QA, 10 Nov 2026: "New analysis" took two lines at 130 % text).
  "app/shell/lightbox-shell.module.css | font-size: min(var(--sx-text-xl), 22px, var(--sx-bar-fit))",
  "app/shell/lightbox-shell.module.css | font-size: min(var(--sx-text-md), var(--sx-bar-fit))",
]);
/** The call Report's printable document keeps its own document scale (owner, 3 Nov 2026). */
const ALLOWED_FILES = new Set(["app/report-document.module.css"]);

const STEP = String.raw`var\(--(?:sx-text|ds-text)-[\w-]+(?:, [^()]+)?\)`;
const LEAD = String.raw`(?:var\(--sx-leading-(?:16|20|24|28|36)\)|1)`;
// 400 to 890: v1.37's weights are back, its odd ones (650, 720, 790) included (owner, 4 Nov 2026).
const WEIGHT = String.raw`(?:[4-8]\d0|var\(--ds-weight-[\w-]+\))`;
// The Report reader's own text-size control (A- / A+) sets these two.
const READER = String.raw`var\(--(?:report|document)-font-size\)`;
const SIZE = new RegExp(
  String.raw`^(?:${STEP}|${READER}|0|inherit|(?:min|max)\((?:${STEP}, [\d.]+(?:px|cqi)|[\d.]+px, ${STEP})\)|(?:max\(\d+px, )?calc\(var\(--size(?:, \d+px)?\) \* [\d.]+\)\)?)$`,
);
const RULES: Record<string, RegExp> = {
  "font-size": SIZE,
  "font-weight": new RegExp(String.raw`^(?:${WEIGHT}|inherit|normal)$`),
  "line-height": new RegExp(
    String.raw`^(?:${LEAD}|0|normal|inherit|min\(${LEAD}, \d+px\)|var\(--lx-leading-devanagari(?:, [\d.]+)?\))$`,
  ),
  font: new RegExp(
    String.raw`^(?:inherit|var\(--(?:sx|lx)-text-[\w-]+\)|(?:italic )?(?:${WEIGHT} )?(?:${STEP}|calc\(var\(--size(?:, \d+px)?\) \* [\d.]+\))(?: / (?:${LEAD}|var\(--ds-[\w-]+\)))? .+)$`,
  ),
};

function cssFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory())
      return entry.name === "node_modules" || entry.name === "tokens"
        ? []
        : cssFiles(path);
    return entry.name.endsWith(".css") ? [path] : [];
  });
}

/** Each file's off-scale declarations, named exceptions left out. */
function offScale(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of [...cssFiles(APP), ...cssFiles(KIT)]) {
    const name = relative(process.cwd(), file).split("\\").join("/");
    if (ALLOWED_FILES.has(name)) continue;
    const css = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const [, prop, raw] of css.matchAll(
      /(?<![\w-])(font-size|font-weight|line-height|font)\s*:\s*([^;{}]+);/g,
    )) {
      const value = raw
        .replace(/\s*!important$/, "")
        .replace(/\s+/g, " ")
        .trim();
      if (RULES[prop].test(value)) continue;
      const line = `${prop}: ${value}`;
      if (ALLOWED.has(`${name} | ${line}`)) continue;
      found.set(name, [...(found.get(name) ?? []), line]);
    }
  }
  return found;
}

it("adds no font size, weight or line height off the one scale", () => {
  const allowed = baseline as Record<string, number>;
  const grew = [...offScale()]
    .filter(([file, lines]) => lines.length > (allowed[file] ?? 0))
    .map(
      ([file, lines]) =>
        `${file}: ${lines.length} off the scale (allowed ${allowed[file] ?? 0}): ${lines.join("; ")}. Use the --sx-text-* steps and roles, weights 400/500 and the --sx-leading-* steps.`,
    );
  expect(grew).toEqual([]);
});

it("finds the scale's breaches it is meant to stop", () => {
  for (const [prop, value] of [
    ["font-size", "13px"],
    ["font-size", "0.8125rem"],
    ["font-weight", "300"],
    ["line-height", "1.45"],
    ["font", "600 13px/1.3 var(--lx-font-ui)"],
  ])
    expect(RULES[prop].test(value), `${prop}: ${value}`).toBe(false);
  for (const [prop, value] of [
    ["font-size", "var(--sx-text-sm)"],
    ["font-weight", "500"],
    ["line-height", "var(--sx-leading-20)"],
    ["font", "500 var(--sx-text-sm) / var(--sx-leading-20) var(--lx-font-ui)"],
  ])
    expect(RULES[prop].test(value), `${prop}: ${value}`).toBe(true);
});
