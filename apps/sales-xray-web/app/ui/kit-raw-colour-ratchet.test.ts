import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

import baseline from "../../../../packages/typescript/ui/src/kit/raw-colour-baseline.json";

/** Shared kit: palette only; every other stylesheet is capped at its move baseline. */
const APP = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../packages/typescript/ui/src/kit",
);
const RAW = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(/g;
const TOKENS = "tokens/palette.css";

function stylesheets(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory())
      return name === "node_modules" ? [] : stylesheets(path);
    return name.endsWith(".css") ? [path] : [];
  });
}

it("adds no raw colour outside the token file", () => {
  const allowed = baseline as Record<string, number>;
  const grew = stylesheets(APP)
    .map((path) => relative(APP, path).split(sep).join("/"))
    .filter((file) => file !== TOKENS)
    .map((file) => ({
      file,
      count: (readFileSync(join(APP, file), "utf8").match(RAW) ?? []).length,
      allowed: allowed[file] ?? 0,
    }))
    .filter(({ count, allowed }) => count > allowed)
    .map(
      ({ file, count, allowed }) =>
        `${file}: ${count} raw colours (allowed ${allowed}); use the --sx-* tokens`,
    );
  expect(grew).toEqual([]);
});
