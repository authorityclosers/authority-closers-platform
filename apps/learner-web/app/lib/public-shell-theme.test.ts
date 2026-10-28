import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("public shell appearance cascade", () => {
  it("uses the shared graphite canvas and glass surfaces throughout the public entry", () => {
    const tokens = readFileSync(
      new URL("../reflex-tokens.css", import.meta.url),
      "utf8",
    );
    expect(tokens).toContain(
      "html:root .site-frame:not(.site-frame--learner) {",
    );
    expect(tokens).toContain("background: var(--sx-paper)");
    expect(tokens).toContain("color: var(--sx-ink)");
    expect(tokens).toContain(":is(.site-header, .site-footer)");
    expect(tokens).toContain("background: var(--sx-glass-thick)");
    expect(tokens).toContain("background: var(--sx-surface)");
    expect(tokens).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});
