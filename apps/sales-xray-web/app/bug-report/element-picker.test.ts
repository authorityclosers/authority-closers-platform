import { afterEach, expect, it } from "vitest";

import {
  describe as describePart,
  markScroll,
  shortName,
} from "./element-picker";

afterEach(() => {
  document.body.innerHTML = "";
});

it("names a part by the React components round it and a short path to it", () => {
  document.body.innerHTML =
    '<main id="main-content"><ul class="rows"><li class="row">One</li>' +
    '<li class="row"><button aria-label="Call Asha">Call</button></li></ul></main>';
  const button = document.querySelector("button")!;
  // The fiber chain React leaves on a node; Suspense names no screen.
  Object.assign(button, {
    __reactFiber$test: {
      type: "button",
      return: {
        type: function LeadRow() {},
        return: {
          type: { displayName: "Suspense" },
          return: { type: function LeadList() {} },
        },
      },
    },
  });
  const picked = describePart(button, null);
  expect(picked.selector).toBe(
    "#main-content > ul.rows > li.row:nth-of-type(2) > button",
  );
  expect(picked.components).toEqual(["LeadRow", "LeadList"]);
  expect(picked.tag).toBe("button");
  // Labels can carry a name: never kept.
  expect(JSON.stringify(picked)).not.toContain("Asha");
  // No picture to compare with: not placed on it.
  expect(picked.moved).toBe(true);
  expect(shortName(picked)).toBe("LeadRow · button");
});

it("stops at a test id and skips generated ids", () => {
  document.body.innerHTML =
    '<section data-testid="lead-sheet"><div id=":r5:"><span>Stage</span></div></section>';
  const picked = describePart(document.querySelector("span")!, null);
  expect(picked.selector).toBe('[data-testid="lead-sheet"] > div > span');
  expect(picked.testid).toBe("lead-sheet");
  expect(shortName(picked)).toBe("lead-sheet");
});

it("knows when a panel round the part scrolled since the picture", () => {
  document.body.innerHTML =
    '<div class="panel"><div class="inner"><span>Row</span></div></div>';
  const mark = markScroll();
  const span = document.querySelector("span")!;
  expect(describePart(span, mark).moved).toBe(false);
  Object.defineProperty(document.querySelector(".panel")!, "scrollTop", {
    configurable: true,
    value: 40,
  });
  expect(describePart(span, mark).moved).toBe(true);
});
