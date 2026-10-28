import { readFileSync, readdirSync } from "node:fs";
import { expect, it } from "vitest";
import manifest from "../manifest";
const read = (path: string) =>
  readFileSync(new URL(path, import.meta.url), "utf8");
it("names the app Reflex in titles, install metadata and public presentation", () => {
  expect(manifest().name).toBe("Reflex: Sales Training");
  expect(manifest().short_name).toBe("Reflex");
  expect(manifest().description).toBe("Sales training by Authority Closers");
  const layout = read("../layout.tsx");
  expect(layout).toContain(
    'title: { default: "Reflex", template: "%s · Reflex" }',
  );
  expect(layout).toContain('media: "(prefers-color-scheme: light)"');
  expect(layout).toContain('media: "(prefers-color-scheme: dark)"');
  expect(read("../components/public-shell.tsx")).toContain(
    "Sales training by Authority Closers",
  );
});
it("imports shared palette then screen then Reflex overrides and retains all nine legacy sheets", () => {
  const layout = read("../layout.tsx");
  expect(layout.indexOf("kit/tokens/palette.css")).toBeLessThan(
    layout.indexOf("kit/tokens/screen.css"),
  );
  expect(layout.indexOf("kit/tokens/screen.css")).toBeLessThan(
    layout.indexOf("reflex-tokens.css"),
  );
  for (const sheet of [
    "styles",
    "auth-clarity",
    "onboarding-clarity",
    "learner-clarity",
    "learning-loop-runtime",
    "course-surfaces",
    "theme",
    "learner-next-slice",
    "progress-momentum",
  ])
    expect(layout).toContain(`import "./${sheet}.css"`);
});
it("uses palette tokens only in the Reflex theme and shell and fixes the public canvas", () => {
  const tokens = read("../reflex-tokens.css");
  for (const css of [tokens, read("./reflex-shell.module.css")])
    expect(css).not.toMatch(
      /#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|oklch)\s*\(|\b(?:white|black|navy|orange)\s*[;)]/i,
    );
  expect(tokens).toContain("--sx-accent: var(--lx-focus)");
  expect(tokens).toContain("--sx-accent-ink: var(--lx-on-teal)");
  expect(tokens).toContain("color-mix(");
  expect(tokens).toContain("html:root body");
  expect(tokens).toContain(".site-frame:not(.site-frame--learner)");
  expect(tokens).toContain("background: var(--sx-paper)");
});
it("pairs the coaching accent with text above 4.5:1 in both palette themes", () => {
  const palette = read(
    "../../../../packages/typescript/ui/src/kit/tokens/palette.css",
  );
  const luminance = (hex: string) => {
    const channels = hex
      .match(/\w\w/g)!
      .map((pair) => parseInt(pair, 16) / 255)
      .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  for (const block of [
    palette.split(':root[data-theme="dark"]')[0],
    palette.split(':root[data-theme="dark"]')[1],
  ]) {
    const accent = block.match(/--lx-focus:\s*#([0-9a-f]{6})/)![1];
    const ink = block.match(/--lx-on-teal:\s*#([0-9a-f]{6})/)![1];
    const a = luminance(accent),
      b = luminance(ink);
    expect(
      (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
    ).toBeGreaterThanOrEqual(4.5);
  }
});
it("mounts one persistent shell, keeps the route URLs and declares each signed-in page title", () => {
  expect(read("../(app)/layout.tsx")).toContain("<ReflexShell");
  for (const entry of readdirSync(new URL("../(app)/", import.meta.url), {
    recursive: true,
    withFileTypes: true,
  })) {
    if (!entry.isFile() || entry.name !== "page.tsx") continue;
    const source = readFileSync(`${entry.parentPath}/${entry.name}`, "utf8");
    expect(source).not.toContain("LearnerShell");
    expect(source).toContain("<ScreenTitle");
    expect(source).toContain("export const metadata");
  }
  const css = read("./reflex-shell.module.css");
  expect(css).toContain("112px + env(safe-area-inset-bottom)");
  expect(css).toContain("899.98px");
  expect(
    read("./reflex-shell.tsx") + read("./screen-transition.ts"),
  ).not.toContain("startViewTransition");
});
