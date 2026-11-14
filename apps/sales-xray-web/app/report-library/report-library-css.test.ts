/**
 * Reports V4 on a phone (Dipak's spec, sections 20-22 and 25, "Mobile
 * usability"): every control can be tapped (44 px or more), text is in rem so
 * it grows with the phone's font size, the calendar's seven columns shrink to
 * fit a narrow screen, long names wrap instead of widening the page, and the
 * sheet's two buttons stay in reach while it scrolls.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "report-library.module.css"), "utf8");

/** The declarations of one rule, by its exact selector. */
function rule(selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`).exec(css);
  if (!match) throw new Error(`no rule for ${selector}`);
  return Object.fromEntries(
    match[1]
      .split(";")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [property, ...value] = line.split(":");
        return [property.trim(), value.join(":").trim()];
      }),
  );
}

const px = (value: string | undefined) =>
  Number(/^(\d+)px$/.exec(value ?? "")?.[1] ?? NaN);

describe("touch targets (section 21)", () => {
  for (const [selector, property] of [
    [".tab", "min-height"],
    [".primary,\n.secondary", "min-height"],
    [".textButton", "min-height"],
    [".search", "min-height"],
    [".filters", "min-height"],
    [".chip", "min-height"],
    [".chip button", "height"],
    [".chip button", "width"],
    [".save", "height"],
    [".save", "width"],
    [".calendarMove", "height"],
    [".calendarMove", "width"],
    [".day", "height"],
    [".slot", "min-height"],
    [".quiet", "min-height"],
    [".back", "min-height"],
    [".callLog", "min-height"],
  ] as const)
    it(`${selector.replace("\n", " ")} ${property} is at least 44 px`, () => {
      expect(px(rule(selector)[property])).toBeGreaterThanOrEqual(44);
    });
});

describe("text and layout", () => {
  it("sizes every text in rem tokens, never fixed pixels", () => {
    const sizes = [...css.matchAll(/font-size:\s*([^;]+);/g)].map((m) => m[1]);
    expect(sizes.length).toBeGreaterThan(10);
    for (const size of sizes)
      expect(size).toMatch(/^var\(--sx-text-[a-z0-9]+\)$/);
  });

  it("fits the calendar's seven days in any width", () => {
    expect(rule(".calendarRow")["grid-template-columns"]).toBe(
      "repeat(7, minmax(0, 1fr))",
    );
    expect(rule(".day").width).toBe("100%");
    expect(rule(".day")["min-width"]).toBe("0");
  });

  it("wraps long names and summaries instead of widening the page", () => {
    expect(rule(".cardTitle h3")["overflow-wrap"]).toBe("anywhere");
    expect(rule(".summary")["overflow-wrap"]).toBe("anywhere");
    expect(rule(".cardTitle")["grid-template-columns"]).toBe(
      "minmax(0, 1fr) 44px",
    );
    // No clipped labels: nothing in the list hides its overflow.
    expect(css).not.toMatch(/text-overflow:\s*ellipsis/);
    expect(css).not.toMatch(/-webkit-line-clamp/);
  });

  it("keeps the sheet's buttons in reach while it scrolls", () => {
    expect(rule(".sheetActions").position).toBe("sticky");
    expect(rule(".sheetActions").bottom).toBe("0");
  });

  it("respects reduced motion", () => {
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
