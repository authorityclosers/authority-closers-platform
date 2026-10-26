// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { ThemeProvider } from "../lightbox/theme-provider";
import { ThemeToggle } from "./theme-toggle";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
const button = () => host.querySelector("button");

async function render(controlEnabled: boolean) {
  await act(async () =>
    root.render(
      <ThemeProvider controlEnabled={controlEnabled}>
        <ThemeToggle />
      </ThemeProvider>,
    ),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  window.localStorage.clear();
});

it("switches between Light and Dark, starting Light", async () => {
  await render(true);
  expect(button()?.getAttribute("aria-label")).toBe(
    "Theme: Light. Switch to Dark.",
  );
  await act(async () => button()?.click());
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  expect(button()?.getAttribute("aria-label")).toBe(
    "Theme: Dark. Switch to Light.",
  );
  await act(async () => button()?.click());
  expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  expect(button()?.getAttribute("aria-label")).toBe(
    "Theme: Light. Switch to Dark.",
  );
});

it("renders nothing where the theme control is disabled", async () => {
  await render(false);
  expect(button()).toBeNull();
});
