// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { revealAboveTabBar } from "./reveal";

const rect = (top: number, height: number) =>
  ({ top, bottom: top + height, height }) as DOMRect;

function element(top: number, height: number, position = "static") {
  const node = document.createElement("div");
  node.style.position = position;
  node.getBoundingClientRect = () => rect(top, height);
  document.body.append(node);
  return node;
}

let scrollBy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.stubGlobal("innerHeight", 851);
  vi.stubGlobal("innerWidth", 393);
  scrollBy = vi.fn();
  window.scrollBy = scrollBy as unknown as typeof window.scrollBy;
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

it("lifts what opened under the tab bar just above it", () => {
  const bar = element(773, 62, "fixed");
  const backdrop = element(0, 851, "fixed");
  const box = element(632, 143);
  document.elementsFromPoint = () => [bar, box, backdrop, document.body];
  revealAboveTabBar(box);
  // The box ends at 775; the bar starts at 773, less 12 px of room.
  expect(scrollBy).toHaveBeenCalledWith({ top: 14, behavior: "smooth" });
});

it("leaves the page alone when it is already clear", () => {
  const bar = element(773, 62, "fixed");
  const box = element(400, 120);
  document.elementsFromPoint = () => [bar, document.body];
  revealAboveTabBar(box);
  expect(scrollBy).not.toHaveBeenCalled();
});

it("uses the screen's bottom where there is no bar", () => {
  const box = element(780, 100);
  document.elementsFromPoint = () => [box, document.body];
  revealAboveTabBar(box);
  expect(scrollBy).toHaveBeenCalledWith({ top: 41, behavior: "smooth" });
});
