// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

// The test robot, 1 Nov 2026 (8842757b, 2f318af4, 57124892, 30acc24f, a2271ba1,
// 89c9fb11): a hook placed below LeadsRoute's early returns made React warn of
// "a change in the order of Hooks" on /leads, ?view=all and ?tab=tasks while
// the desk loaded, and showed "This screen hit a snag". Whatever the page
// renders, loading or loaded, it calls every hook first.
it("calls every hook of the Leads page above its first early return", () => {
  const source = readFileSync(
    fileURLToPath(new URL("./leads-page.tsx", import.meta.url)),
    "utf8",
  ).split("\n");
  const start = source.findIndex((line) =>
    line.startsWith("export function LeadsRoute("),
  );
  expect(start).toBeGreaterThan(0);
  const rest = source.slice(start + 1);
  const body = rest.slice(0, rest.indexOf("}"));
  // An early return: a top-level return, or a top-level `if` whose own block
  // (or single statement) returns.
  const returns = (at: number) => {
    if (/\breturn\b/.test(body[at])) return true;
    const braced = body[at].trimEnd().endsWith("{");
    for (let line = at + 1; line < body.length; line++) {
      if (braced ? body[line] === "  }" : /^ {0,2}\S/.test(body[line])) break;
      if (/^ {4}return\b/.test(body[line])) return true;
    }
    return false;
  };
  const firstReturn = body.findIndex(
    (line, at) =>
      /^ {2}return\b/.test(line) || (/^ {2}if \(/.test(line) && returns(at)),
  );
  const hooks = body.flatMap((line, at) =>
    /^ {2}(?:const [^=]+= )?use[A-Z]\w*[(<]/.test(line) ? [at] : [],
  );
  expect(firstReturn).toBeGreaterThan(0);
  expect(hooks.length).toBeGreaterThan(10);
  expect(Math.max(...hooks)).toBeLessThan(firstReturn);
});
