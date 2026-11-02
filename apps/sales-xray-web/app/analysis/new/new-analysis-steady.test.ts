import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

// New analysis fits and holds still (the test robot, 1 Nov 2026): 42137527,
// at 200 % text an auto column grew to 400 px in a 328 px page and pushed the
// heading past its edge; 3c6e780e, on 3G the page moved as the phone header's
// bell came in and as the wave's light moved by left.
const app = join(dirname(fileURLToPath(import.meta.url)), "../..");
const css = (path: string) => readFileSync(join(app, path), "utf8");

function rule(source: string, selector: string): string {
  const escaped = selector.replace(/[.[\]"=]/g, (c) => `\\${c}`);
  const found = source.match(
    new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`),
  );
  expect(found, selector).not.toBeNull();
  return found![1];
}

it("keeps the upload column as wide as its box, and wraps the steps under it", () => {
  expect(rule(css("acquisition-studio.module.css"), ".primaryColumn")).toMatch(
    /grid-template-columns:\s*minmax\(0,\s*1fr\);/,
  );
  expect(rule(css("new-analysis-hero.module.css"), ".trail")).toMatch(
    /flex-wrap:\s*wrap;/,
  );
});

it("moves the wave's light by transform, never by left", () => {
  const wave = css("analysis-wave.module.css");
  expect(rule(wave, ".beamRail")).toMatch(/container-type:\s*inline-size;/);
  expect(rule(wave, ".beam")).toMatch(/transform:\s*translateX\(/);
  const frames = wave.match(/@keyframes beam-[\w-]+ \{[\s\S]*?\n\}/g) ?? [];
  expect(frames).toHaveLength(3);
  for (const frame of frames) {
    expect(frame).toMatch(/transform:\s*translateX\(/);
    expect(frame).not.toMatch(/(^|\s)left:/);
  }
});

it("draws the phone header's loaded lines from the first paint", () => {
  const shell = css("shell/lightbox-shell.module.css");
  // The workspace button keeps the span's line height: font resets it.
  const reset = [...shell.matchAll(/\n\.mobilePlace\s*\{([^}]*)\}/g)]
    .map((found) => found[1])
    .find((body) => body.includes("font: inherit"));
  expect(reset).toBeDefined();
  expect(reset!.indexOf("line-height: 1.15")).toBeGreaterThan(
    reset!.indexOf("font: inherit"),
  );
  expect(rule(shell, ".mobileWorkspace .contextRow")).toMatch(
    /min-height:\s*18px;/,
  );
  // The bell's place is kept while the session settles.
  const slot = rule(shell, ".barSlot");
  expect(slot).toMatch(/width:\s*44px;/);
  expect(slot).toMatch(/height:\s*44px;/);
});
