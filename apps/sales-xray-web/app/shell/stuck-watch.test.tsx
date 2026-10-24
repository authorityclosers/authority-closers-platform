// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notices: [] as Array<{
    id: string;
    title: string;
    action?: { label: string };
  }>,
  dismissed: [] as string[],
}));
vi.mock("../notice-center", () => ({
  notify: (notice: { id: string; title: string }) => mocks.notices.push(notice),
  dismissNotice: (id: string) => mocks.dismissed.push(id),
}));

const { StuckWatch, STUCK_NOTICE } = await import("./stuck-watch");

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root;
let host: HTMLDivElement;
let outline: HTMLDivElement;

beforeEach(() => {
  vi.useFakeTimers();
  mocks.notices.length = 0;
  mocks.dismissed.length = 0;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  outline = document.createElement("div");
  outline.setAttribute("aria-busy", "true");
  // A loading outline covering the whole screen.
  outline.getBoundingClientRect = () =>
    ({
      left: 0,
      top: 0,
      right: window.innerWidth,
      bottom: window.innerHeight,
    }) as DOMRect;
  document.body.append(outline);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  outline.remove();
  vi.useRealTimers();
});

it("offers Reload when a screen has been loading for 15 seconds, and leaves once it loads", async () => {
  await act(async () => root.render(<StuckWatch />));
  await act(async () => vi.advanceTimersByTime(12_000));
  expect(mocks.notices).toEqual([]);
  await act(async () => vi.advanceTimersByTime(6_000));
  expect(mocks.notices).toEqual([
    expect.objectContaining({
      id: STUCK_NOTICE,
      title: "This is taking longer than usual",
      action: expect.objectContaining({ label: "Reload" }),
    }),
  ]);
  outline.removeAttribute("aria-busy");
  await act(async () => vi.advanceTimersByTime(2_000));
  expect(mocks.dismissed).toContain(STUCK_NOTICE);
});

it("says nothing about a small part of the screen that is still loading", async () => {
  outline.getBoundingClientRect = () =>
    ({ left: 0, top: 0, right: 100, bottom: 80 }) as DOMRect;
  await act(async () => root.render(<StuckWatch />));
  await act(async () => vi.advanceTimersByTime(60_000));
  expect(mocks.notices).toEqual([]);
});
