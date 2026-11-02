// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { Avatar, initials } from "./kit";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

// Phone personas ph1-34 (1 Nov 2026): सुरेश पाटील read "सप", मीरा जोशी "मज",
// and a name with a flower in it got the flower for an initial.
it("takes each word's first letter as a reader sees it, never an emoji", () => {
  expect(initials("सुरेश पाटील")).toBe("सुपा");
  expect(initials("मीरा जोशी")).toBe("मीजो");
  expect(initials("Priya 🌸")).toBe("P");
  expect(initials("🌸 Priya Shah")).toBe("PS");
  expect(initials("Dr. Asha Rao")).toBe("AR");
  expect(initials("asha (Pune)")).toBe("AP");
  expect(initials("🌸🌸")).toBe("?");
});

// The slowest tester's Leads (2 Nov 2026): a new segmenter per word per avatar,
// 100+ on each render of her 50 lead rows. One serves every name.
it("makes one segmenter for every name", () => {
  const Real = Intl.Segmenter;
  let made = 0;
  class Counted extends Real {
    constructor(...args: ConstructorParameters<typeof Real>) {
      super(...args);
      made += 1;
    }
  }
  const swap = (value: typeof Real) =>
    Object.defineProperty(Intl, "Segmenter", {
      value,
      configurable: true,
      writable: true,
    });
  swap(Counted);
  try {
    for (let row = 0; row < 50; row++)
      expect(initials(`Fictional Prospect ${row} Rao`)).toBe("FP");
  } finally {
    swap(Real);
  }
  expect(made).toBeLessThanOrEqual(1);
});

it("draws a person, not a question mark, for a name with no letter", async () => {
  await act(async () => root.render(<Avatar name="🌸" size={40} />));
  expect(host.querySelector("svg")).not.toBeNull();
  expect(host.textContent).toBe("");
  await act(async () => root.render(<Avatar name="सुरेश पाटील" size={16} />));
  // A small avatar keeps one whole letter, its vowel sign with it.
  expect(host.textContent).toBe("सु");
});
