// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";

import { installFocusMode } from "./focus-mode";

let stop = () => {};

afterEach(() => {
  stop();
  document.documentElement.removeAttribute("data-sx-input");
});

// Owner, 25 Oct 2026: no glowing ring after a click; keyboards keep it.
it("fades rings after a tap or click and shows them again for keys", () => {
  stop = installFocusMode();
  const root = document.documentElement;
  expect(root.getAttribute("data-sx-input")).toBe("pointer");
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab" }));
  expect(root.getAttribute("data-sx-input")).toBe("keyboard");
  document.dispatchEvent(new Event("pointerdown"));
  expect(root.getAttribute("data-sx-input")).toBe("pointer");
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Shift" }));
  expect(root.getAttribute("data-sx-input")).toBe("pointer");
});
