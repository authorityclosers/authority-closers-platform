// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { usePracticeNavigationAvailability } from "./practice-availability";
import { loadPracticeNavigationAvailability } from "../lib/practice-navigation";
import { LearnerShell } from "./site-shell";

vi.mock("../lib/practice-navigation", () => ({
  loadPracticeNavigationAvailability: vi.fn(),
}));
vi.mock("../lib/learner-api", () => ({
  createLearnerApi: () => ({
    me: async () => {
      throw new Error("Identity unavailable in navigation test");
    },
    profileAvatar: async () => {
      throw new Error("Avatar unavailable in navigation test");
    },
  }),
}));
const load = vi.mocked(loadPracticeNavigationAvailability);
(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
let unmounted = false;
function Probe({ scope = "home" }: { scope?: string }) {
  const available = usePracticeNavigationAvailability(scope);
  return (
    <nav>{available ? <a href="/practice">Practice Arcade</a> : null}</nav>
  );
}
beforeEach(() => {
  load.mockReset().mockResolvedValue(false);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  unmounted = false;
});
afterEach(async () => {
  if (!unmounted) await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});
it("does not render a speculative server-side link", () => {
  expect(renderToStaticMarkup(<Probe />)).not.toContain("/practice");
  expect(load).not.toHaveBeenCalled();
});
it("reveals only confirmed availability, and removes it after fresh focus denial", async () => {
  load.mockResolvedValueOnce(true).mockResolvedValue(false);
  await act(async () => root.render(<Probe />));
  expect(container.querySelector("a")?.textContent).toBe("Practice Arcade");
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(container.querySelector("a")).toBeNull();
  expect(load).toHaveBeenCalledTimes(2);
});
it("uses the same fresh admission for the mounted desktop and mobile shell", async () => {
  load.mockResolvedValueOnce(true).mockResolvedValue(false);
  await act(async () => root.render(<LearnerShell current="practice" />));
  expect(
    container.querySelector('.learner-sidebar a[href="/practice"]'),
  ).not.toBeNull();
  const mobile = container.querySelector(
    '.learner-bottom-nav a[href="/practice"]',
  );
  expect(mobile?.getAttribute("aria-label")).toBe("Practice Arcade");
  expect(mobile?.getAttribute("aria-current")).toBe("page");
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(container.querySelector('a[href="/practice"]')).toBeNull();
  expect(
    container.querySelector('.learner-bottom-nav a[href="/discover"]'),
  ).not.toBeNull();
});
it("cancels old scope reads and ignores late results", async () => {
  let finishOld: ((value: boolean) => void) | undefined;
  load
    .mockImplementationOnce(
      () =>
        new Promise<boolean>((resolve) => {
          finishOld = resolve;
        }),
    )
    .mockResolvedValue(false);
  await act(async () => root.render(<Probe scope="old" />));
  const oldSignal = load.mock.calls[0][0];
  await act(async () => root.render(<Probe scope="new" />));
  expect(oldSignal.aborted).toBe(true);
  await act(async () => finishOld?.(true));
  expect(container.querySelector("a")).toBeNull();
});
it("aborts pending admission and removes refresh listeners on unmount", async () => {
  load.mockImplementation(() => new Promise<boolean>(() => undefined));
  await act(async () => root.render(<Probe />));
  const signal = load.mock.calls[0][0];
  await act(async () => root.unmount());
  unmounted = true;
  expect(signal.aborted).toBe(true);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(load).toHaveBeenCalledOnce();
});
