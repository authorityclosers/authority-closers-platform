// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";

import { chipsOverflow } from "./calls-chip-row";

/** A toolbar laid out by hand: happy-dom has no layout engine. */
function toolbar(width: number, chips: number[], others: number[]) {
  const bar = document.createElement("div");
  const sized = (element: HTMLElement, value: number) =>
    Object.defineProperty(element, "offsetWidth", { value });
  const search = document.createElement("label");
  search.setAttribute("data-shrinks", "");
  search.style.minWidth = "160px";
  sized(search, 280);
  const group = document.createElement("div");
  group.setAttribute("data-chips", "");
  group.style.columnGap = "4px";
  // Squeezed into a short box: only the chips themselves give its length.
  sized(group, 120);
  for (const chip of chips) {
    const button = document.createElement("button");
    sized(button, chip);
    group.append(button);
  }
  bar.append(search, group);
  for (const other of others) {
    const control = document.createElement("label");
    sized(control, other);
    bar.append(control);
  }
  bar.style.display = "flex";
  bar.style.columnGap = "8px";
  Object.defineProperty(bar, "clientWidth", { value: width });
  document.body.append(bar);
  return bar;
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

it("keeps one row while search (at its smallest), chips, rep and sort fit", () => {
  // 160 + (70 + 130 + 115 + 2 × 4) + 150 + 140 + 3 × 8 = 797
  expect(chipsOverflow(toolbar(797, [70, 130, 115], [150, 140]))).toBe(false);
});

it("gives the chips their own row when the full set does not fit", () => {
  expect(chipsOverflow(toolbar(796, [70, 130, 115], [150, 140]))).toBe(true);
  // The 1280 px Calls page of 11 Oct: four chips beside rep and sort.
  expect(chipsOverflow(toolbar(872, [72, 132, 118, 150], [148, 140]))).toBe(
    true,
  );
});

it("leaves the phone grid alone (the chips scroll in their own row there)", () => {
  const bar = toolbar(358, [72, 132, 118, 150], [44]);
  bar.style.display = "grid";
  expect(chipsOverflow(bar)).toBe(false);
});
