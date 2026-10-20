import { act, useRef } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import {
  moveScreen,
  placeOf,
  pressScreen,
  releasePress,
  SCREEN_GIVE_UP_MS,
  SCREEN_PRESS_HOLD_MS,
  screenMove,
  takePress,
  useScreenMotion,
} from "./screen-transition";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true;

afterEach(() => {
  delete (document as { startViewTransition?: unknown }).startViewTransition;
  delete document.documentElement.dataset.sxMove;
  delete (HTMLElement.prototype as { animate?: unknown }).animate;
  window.history.replaceState(null, "", "/");
  vi.useRealTimers();
});

const CALL = "/analysis/calls/0b6e7c52-3f0e-4a8e-9a55-2d4f1c9e8b10";

it("orders the places as the tabs do, with pages under them a step deeper", () => {
  expect(placeOf("/dashboard")).toEqual({ index: 0, depth: 0 });
  expect(placeOf("/")).toEqual({ index: 0, depth: 0 });
  expect(placeOf("/leads/")).toEqual({ index: 1, depth: 0 });
  expect(placeOf(CALL)).toEqual({ index: 4, depth: 1 });
  expect(placeOf("/calls")).toEqual(placeOf("/analysis/calls"));
  expect(placeOf("/organisation/insights")?.index).not.toBe(
    placeOf("/organisation")?.index,
  );
  // Settings' sections are one place: moving between them is not a move.
  expect(placeOf("/settings/team")).toEqual(placeOf("/settings"));
  expect(placeOf("/login")).toBeNull();
});

it("moves forward along the tabs and into a page, back the other way", () => {
  expect(screenMove("/dashboard", "/leads")).toBe("forward");
  expect(screenMove("/analysis/calls", "/leads")).toBe("back");
  expect(screenMove("/analysis/calls", CALL)).toBe("forward");
  expect(screenMove(CALL, "/analysis/calls")).toBe("back");
  expect(screenMove("/leads", "/leads")).toBeNull();
  expect(screenMove("/settings/team", "/settings/apps")).toBeNull();
  expect(screenMove("/login", "/dashboard")).toBeNull();
});

it("leaves moves without a direction to the router", () => {
  const navigate = vi.fn();
  expect(moveScreen(navigate, "/leads", "/leads")).toBe(false);
  expect(moveScreen(navigate, "/dashboard", "/login")).toBe(false);
  expect(navigate).not.toHaveBeenCalled();
});

function Frame({ pathname }: { pathname: string }) {
  const ref = useRef<HTMLElement | null>(null);
  const standing = useScreenMotion(ref, pathname);
  return <main ref={ref}>{standing ?? "page"}</main>;
}

async function mount(pathname: string) {
  window.history.replaceState(null, "", pathname);
  const host = document.createElement("div");
  const root = createRoot(host);
  await act(async () => root.render(<Frame pathname={pathname} />));
  return {
    host,
    render: (next: string) =>
      act(async () => {
        window.history.replaceState(null, "", next);
        root.render(<Frame pathname={next} />);
      }),
    unmount: () => act(async () => root.unmount()),
  };
}

it("shows the tapped place's outline at once, until the router arrives", async () => {
  const frame = await mount("/dashboard");
  const navigate = vi.fn();
  await act(async () => {
    expect(moveScreen(navigate, "/dashboard", "/leads")).toBe(true);
  });
  expect(navigate).toHaveBeenCalledOnce();
  expect(frame.host.textContent).toBe("/leads");
  await frame.render("/leads");
  expect(frame.host.textContent).toBe("page");
  // Coming back later shows the page, not the old outline.
  await frame.render("/dashboard");
  expect(frame.host.textContent).toBe("page");
  await frame.unmount();
});

it("draws the outline inside a view transition, which slides the page area", async () => {
  let update: (() => void) | null = null;
  let finish: () => void = () => {};
  Object.assign(document, {
    startViewTransition: (callback: () => void) => {
      update = callback;
      return { finished: new Promise<void>((resolve) => (finish = resolve)) };
    },
  });
  const frame = await mount("/analysis/calls");
  const navigate = vi.fn();
  moveScreen(navigate, "/analysis/calls", "/leads");
  expect(document.documentElement.dataset.sxMove).toBe("back");
  expect(navigate).not.toHaveBeenCalled();
  await act(async () => update!());
  // The outline is drawn synchronously, before the "after" picture.
  expect(frame.host.textContent).toBe("/leads");
  expect(navigate).toHaveBeenCalledOnce();
  finish();
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(document.documentElement.dataset.sxMove).toBeUndefined();
  await frame.unmount();
});

it("gives the page back when the router never arrives", async () => {
  vi.useFakeTimers();
  const frame = await mount("/dashboard");
  await act(async () => {
    moveScreen(() => {}, "/dashboard", "/prospects");
  });
  expect(frame.host.textContent).toBe("/prospects");
  await act(async () => {
    vi.advanceTimersByTime(SCREEN_GIVE_UP_MS);
  });
  expect(frame.host.textContent).toBe("page");
  await frame.unmount();
});

it("fades the page area for a move no tap started", async () => {
  const animate = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true,
    value: animate,
  });
  const frame = await mount("/leads");
  expect(animate).not.toHaveBeenCalled();
  await frame.render("/analysis/calls");
  expect(animate).toHaveBeenCalledOnce();
  // Opacity only: the page's fixed bars must not move with it.
  const [frames] = animate.mock.calls[0] as [Keyframe[]];
  expect(frames.every((frame) => !("transform" in frame))).toBe(true);
  // A tapped move doesn't fade a second time when the page arrives.
  await act(async () => {
    moveScreen(() => {}, "/analysis/calls", "/dashboard");
  });
  await frame.render("/dashboard");
  expect(animate).toHaveBeenCalledOnce();
  await frame.unmount();
});

it("shows the outline on the press, and the click only navigates", async () => {
  const frame = await mount("/dashboard");
  await act(async () => {
    expect(pressScreen("/dashboard", "/leads")).toBe(true);
  });
  // On the press itself, before any click or router.
  expect(frame.host.textContent).toBe("/leads");
  expect(takePress("/leads")).toBe(true);
  // Taken once: a second click would run its own move.
  expect(takePress("/leads")).toBe(false);
  await frame.render("/leads");
  expect(frame.host.textContent).toBe("page");
  await frame.unmount();
});

it("gives the page back when a press ends without a click", async () => {
  const frame = await mount("/dashboard");
  await act(async () => {
    pressScreen("/dashboard", "/prospects");
  });
  expect(frame.host.textContent).toBe("/prospects");
  await act(async () => releasePress("/prospects"));
  expect(frame.host.textContent).toBe("page");
  // A press held past the hold time lets go by itself.
  vi.useFakeTimers();
  await act(async () => {
    pressScreen("/dashboard", "/prospects");
  });
  expect(frame.host.textContent).toBe("/prospects");
  await act(async () => {
    vi.advanceTimersByTime(SCREEN_PRESS_HOLD_MS);
  });
  expect(frame.host.textContent).toBe("page");
  expect(takePress("/prospects")).toBe(false);
  await frame.unmount();
});

it("never presses towards the place on screen", async () => {
  expect(pressScreen("/leads", "/leads")).toBe(false);
  expect(takePress("/leads")).toBe(false);
});
