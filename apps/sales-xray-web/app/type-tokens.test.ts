import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, it } from "vitest";

/**
 * Proper fonts and type across all screens (owner, 25 Oct 2026): the app's
 * own faces only, and one page title.
 */

const APP = join(process.cwd(), "app");

function cssFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory())
      return entry.name === "node_modules" || entry.name === "review-fixture"
        ? []
        : cssFiles(path);
    return entry.name.endsWith(".css") ? [path] : [];
  });
}

it("uses the app's own faces: no Georgia or Cascadia", () => {
  const off = cssFiles(APP).flatMap((file) =>
    readFileSync(file, "utf8")
      .split("\n")
      .flatMap((line, index) =>
        /font-family:\s*(Georgia|"Cascadia Code")/.test(line)
          ? [`${relative(APP, file)}:${index + 1}`]
          : [],
      ),
  );
  expect(off).toEqual([]);
});

it("draws every page title with the one title style", () => {
  const titles: [string, string][] = [
    ["ui/kit.module.css", ".title {"],
    ["shell/lightbox-shell.module.css", ".pageHeading h1 {"],
    ["calls-library.module.css", ".headerCopy h1 {"],
    ["organisation/organisation.module.css", ".headerCopy h1 {"],
    ["account-view.module.css", ".header h1 {"],
    ["error-page.module.css", ".card h1 {"],
  ];
  for (const [file, rule] of titles) {
    const text = readFileSync(join(APP, file), "utf8");
    const start = text.indexOf(`\n${rule}`);
    expect(start, `${file} ${rule}`).toBeGreaterThan(-1);
    const body = text.slice(start, text.indexOf("}", start));
    expect(body, `${file} ${rule}`).toContain("font: var(--sx-text-title)");
    expect(body, `${file} ${rule}`).toContain(
      "letter-spacing: var(--sx-tracking-title)",
    );
  }
});
