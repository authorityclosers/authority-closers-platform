import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

import baseline from "./raw-colour-baseline.json";

/**
 * Pulse's colour ratchet (AUT-1663): raw colours (hex, rgb(), hsl()) live only
 * in lightbox/tokens.css. Every other stylesheet may keep the raw colours it
 * had on 10 Oct and never gain one: use the --sx-* tokens (ui/sx-tokens.css).
 * When a file loses raw colours, lower its number here so it can't regress.
 */
const APP = join(dirname(fileURLToPath(import.meta.url)), "..");
const RAW = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(/g;
const TOKENS = "lightbox/tokens.css";

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
