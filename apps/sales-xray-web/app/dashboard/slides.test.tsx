// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SLIDE_EVERY_MS, Slides } from "./slides";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// Calls analysed and Reports ready as a widget that slides by itself, with page
// dots (owner, 25 Oct 2026).
let host: HTMLDivElement;
let root: Root;
const scrollTo = vi.fn();
const own = (name: string) =>
  Object.getOwnPropertyDescriptor(HTMLElement.prototype, name);
const before = {
  clientWidth: own("clientWidth"),
  scrollWidth: own("scrollWidth"),
};

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  scrollTo.mockReset();
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get: () => 320,
  });
  Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
    configurable: true,
    get: () => 640,
  });
  HTMLElement.prototype.scrollTo =
    scrollTo as typeof HTMLElement.prototype.scrollTo;
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  for (const [name, descriptor] of Object.entries(before))
    if (descriptor)
      Object.defineProperty(HTMLElement.prototype, name, descriptor);
    else
      delete (HTMLElement.prototype as unknown as Record<string, unknown>)[
        name
      ];
});

const render = () =>
  act(async () =>
    root.render(
      <Slides
        label="Dashboard figures"
        names={["Calls analysed", "Reports ready"]}
      >
        <p>Calls analysed 12</p>
        <p>Reports ready 9</p>
      </Slides>,
    ),
  );

it("shows a dot per slide and moves to the one tapped", async () => {
  await render();
  const slides = host.querySelectorAll('[aria-roledescription="slide"]');
  expect([...slides].map((slide) => slide.getAttribute("aria-label"))).toEqual([
    "1 of 2: Calls analysed",
    "2 of 2: Reports ready",
  ]);
  const dots = [...host.querySelectorAll<HTMLButtonElement>("button")];
  expect(dots.map((dot) => dot.getAttribute("aria-label"))).toEqual([
    "Show Calls analysed",
    "Show Reports ready",
  ]);
  expect(dots[0].getAttribute("aria-current")).toBe("true");
  await act(async () => dots[1].click());
  expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ left: 320 }));
  expect(dots[1].getAttribute("aria-current")).toBe("true");
});

it("moves on by itself, and holds while a finger is on it", async () => {
  vi.useFakeTimers();
  await render();
  await act(async () => vi.advanceTimersByTime(SLIDE_EVERY_MS));
  expect(scrollTo).toHaveBeenCalledTimes(1);
  const widget = host.firstElementChild as HTMLElement;
  await act(async () =>
    widget.dispatchEvent(new Event("touchstart", { bubbles: true })),
  );
  await act(async () => vi.advanceTimersByTime(SLIDE_EVERY_MS * 2));
  expect(scrollTo).toHaveBeenCalledTimes(1);
});
