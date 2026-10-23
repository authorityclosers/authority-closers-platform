// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  PRESS_DELAY_MS,
  PRESS_SHOW_MS,
  PRESSED,
  watchPresses,
} from "./press-feedback";

let stop: () => void;
let host: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement("div");
  host.innerHTML = `
    <ul><li data-lead-row=""><span class="name">Asha Fictional</span>
      <button type="button" class="call">Call</button></li></ul>
    <button type="button" class="off" disabled>Off</button>
    <p class="text">Words</p>`;
  document.body.append(host);
  stop = watchPresses(document);
});

afterEach(() => {
  stop();
  host.remove();
  vi.useRealTimers();
});

const at = (selector: string) => host.querySelector(selector) as HTMLElement;
const pointer = (type: string, target: Element, x = 10, y = 10): void => {
  target.dispatchEvent(
    new PointerEvent(type, {
      bubbles: true,
      isPrimary: true,
      button: 0,
      clientX: x,
      clientY: y,
    }),
  );
};
const pressed = (selector: string) => at(selector).hasAttribute(PRESSED);

it("dims what is pressed within the press delay, and the innermost one only", () => {
  pointer("pointerdown", at(".call"));
  expect(pressed(".call")).toBe(false);
  vi.advanceTimersByTime(PRESS_DELAY_MS);
  expect(pressed(".call")).toBe(true);
  expect(pressed("[data-lead-row]")).toBe(false);
  expect(PRESS_DELAY_MS).toBeLessThanOrEqual(100);
  pointer("pointerup", at(".call"));
  vi.advanceTimersByTime(PRESS_SHOW_MS);
  expect(pressed(".call")).toBe(false);
});

it("still shows a quick tap, briefly", () => {
  pointer("pointerdown", at(".name"));
  vi.advanceTimersByTime(20);
  pointer("pointerup", at(".name"));
  expect(pressed("[data-lead-row]")).toBe(true);
  vi.advanceTimersByTime(PRESS_SHOW_MS - 1);
  expect(pressed("[data-lead-row]")).toBe(true);
  vi.advanceTimersByTime(1);
  expect(pressed("[data-lead-row]")).toBe(false);
});

it("lets a scroll go by without dimming the rows it starts on", () => {
  pointer("pointerdown", at(".name"));
  pointer("pointermove", at(".name"), 10, 40);
  vi.advanceTimersByTime(PRESS_DELAY_MS);
  expect(pressed("[data-lead-row]")).toBe(false);

  pointer("pointerdown", at(".name"));
  vi.advanceTimersByTime(PRESS_DELAY_MS);
  expect(pressed("[data-lead-row]")).toBe(true);
  pointer("pointercancel", at(".name"));
  expect(pressed("[data-lead-row]")).toBe(false);
});

it("leaves disabled buttons and plain text alone", () => {
  pointer("pointerdown", at(".off"));
  pointer("pointerdown", at(".text"));
  vi.advanceTimersByTime(PRESS_DELAY_MS);
  expect(host.querySelectorAll(`[${PRESSED}]`)).toHaveLength(0);
});
