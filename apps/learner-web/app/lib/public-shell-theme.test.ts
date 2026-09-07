import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("public shell appearance cascade", () => {
  it("pairs dark header text with a background that outranks the public base selector", () => {
    const theme = readFileSync(
      new URL("../theme.css", import.meta.url),
      "utf8",
    );
    const base = readFileSync(
      new URL("../styles.css", import.meta.url),
      "utf8",
    );
    expect(base).toContain(
      ".site-frame:not(.site-frame--learner) .site-header {",
    );
    // (0,3,1) outranks the base's (0,3,0); runtime contrast is browser-tested too.
    expect(theme).toMatch(
      /html\[data-theme="dark"\] \.site-frame :is\(\.site-header, \.site-footer\)\s*\{[^}]*background:\s*rgba\(16, 26, 43, 0\.96\)/,
    );
    expect(theme).toMatch(
      /\.site-header \.brand,[\s\S]*?color: var\(--theme-text\)/,
    );
  });
});
