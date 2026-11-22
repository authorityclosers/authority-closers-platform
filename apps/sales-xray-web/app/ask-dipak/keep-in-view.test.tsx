// @vitest-environment happy-dom
import { act, useRef } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

import { inViewShift, useKeepInView } from "./keep-in-view";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Issue 215 (14 Nov 2026): Ask Dipak's search box hid behind the keyboard.
it("scrolls just enough for a field to clear the keyboard, or the top", () => {
  const keyboardUp = { offsetTop: 0, height: 420 };
  // In sight: nothing moves.
  expect(inViewShift({ top: 200, bottom: 254 }, keyboardUp)).toBe(0);
  // Under the keyboard: up by what it hides, plus room.
  expect(inViewShift({ top: 600, bottom: 654 }, keyboardUp)).toBe(250);
  // Above what is seen (the visual viewport scrolled down): back down.
  expect(
    inViewShift({ top: 40, bottom: 94 }, { offsetTop: 100, height: 420 }),
  ).toBe(-76);
});

function Field() {
  const ref = useRef<HTMLInputElement>(null);
  useKeepInView(ref);
  return <input ref={ref} aria-label="Search" />;
}

it("moves the page when the keyboard opens over the focused field", async () => {
  const view = new EventTarget() as EventTarget & {
    offsetTop: number;
    height: number;
  };
  view.offsetTop = 0;
  view.height = 844;
  vi.stubGlobal("visualViewport", view);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<Field />));
  const input = host.querySelector("input")!;
  input.getBoundingClientRect = () =>
    ({ top: 600, bottom: 654, left: 0, right: 300 }) as DOMRect;
  const scroller = document.scrollingElement ?? document.documentElement;
  const scrollBy = vi.fn();
  scroller.scrollBy = scrollBy;
  input.focus();
  // No keyboard yet: in sight.
  expect(scrollBy).not.toHaveBeenCalled();
  view.height = 420;
  await act(async () => view.dispatchEvent(new Event("resize")));
  expect(scrollBy).toHaveBeenCalledWith({ top: 250 });
  // Without focus nothing moves.
  scrollBy.mockClear();
  input.blur();
  await act(async () => view.dispatchEvent(new Event("resize")));
  expect(scrollBy).not.toHaveBeenCalled();
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
