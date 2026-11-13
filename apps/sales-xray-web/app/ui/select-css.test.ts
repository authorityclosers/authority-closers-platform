import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

// Owner, 10 Nov 2026 (bug 196, Leads): a long press selected the app's own
// words, "not an app behaviour". On touch screens UI text isn't selectable;
// notes, messages, a report's text and fields still are. Sales X-Ray only:
// its root, and the phone app's whole page (styles.integration keeps the
// learner app's body untouched).
const css = readFileSync(join(process.cwd(), "app/styles.css"), "utf8");
const touch =
  css.match(
    /@media \(hover: none\) and \(pointer: coarse\) \{\s*\.xray-app,[\s\S]*?\n\}/,
  )?.[0] ?? "";

it("keeps UI words unselectable on touch screens, and people's words selectable", () => {
  expect(touch).toMatch(
    /\.xray-app,\s*html\[data-sx-app\] body \{[^}]*-webkit-user-select: none/,
  );
  expect(touch).toMatch(/:is\(p, blockquote, pre, q\)/);
  expect(touch).toMatch(/:is\(input, textarea\)/);
  expect(touch).toMatch(/\[data-selectable\]/);
  expect(touch).toMatch(/user-select: text/);
  // A paragraph inside a control is its label.
  expect(touch).toMatch(
    /:is\(\s*button,\s*a,\s*label,[\s\S]*?\)\s*:is\(p, blockquote, pre, q\)/,
  );
  // Never the learner app's body.
  expect(css.replace(/\/\*[\s\S]*?\*\//g, "")).not.toMatch(
    /(?:^|\n)\s*body\s*[,{]/,
  );
});
