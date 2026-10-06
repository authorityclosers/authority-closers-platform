import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AnimatedCountUp } from "./animated-count-up";

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let frame: FrameRequestCallback;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(
    (callback) => {
      frame = callback;
      return 1;
    },
  );
  vi.spyOn(globalThis, "cancelAnimationFrame");
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it.each([
  [0, "0", ""],
  [59, "59", ""],
  [60, "60", ""],
  [61, "61", " (1 h 1 min)"],
  [120, "120", " (2 h)"],
  [800, "800", " (13 h 20 min)"],
  [10_000, "10,000", " (166 h 40 min)"],
])(
  "agrees on the final visible and announced %i minutes",
  async (value, count, hours) => {
    await act(async () =>
      root.render(<AnimatedCountUp targetMinutes={value} />),
    );
    const announcement = host.querySelector('[aria-live="polite"]')!;
    const visible = host.querySelector('div[aria-hidden="true"]')!;
    expect(announcement.textContent).toBe(`+${count} analysis minutes${hours}`);
    expect(announcement.getAttribute("aria-atomic")).toBe("true");
    await act(async () => frame(100));
    await act(async () => frame(1300));
    expect(visible.querySelector("span")?.textContent).toBe(`+${count}`);
    expect(visible.textContent).toContain(`Analysis minutes${hours}`);
    expect(announcement.textContent).toBe(`+${count} analysis minutes${hours}`);
    expect(host.textContent).not.toMatch(/credits/i);
    expect(globalThis.requestAnimationFrame).toHaveBeenCalledTimes(2);
  },
);

it("announces only the final quantity through intermediate frames and cancels on unmount", async () => {
  await act(async () => root.render(<AnimatedCountUp targetMinutes={800} />));
  const announcement = host.querySelector('[aria-live="polite"]')!;
  const visible = host.querySelector('div[aria-hidden="true"]')!;
  await act(async () => frame(100));
  await act(async () => frame(700));
  expect(visible.textContent).toContain("+700");
  expect(visible.textContent).toContain("Analysis minutes (11 h 40 min)");
  expect(announcement.textContent).toBe("+800 analysis minutes (13 h 20 min)");
  await act(async () => root.render(null));
  expect(globalThis.cancelAnimationFrame).toHaveBeenCalledWith(1);
});
