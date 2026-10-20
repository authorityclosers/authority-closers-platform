import { act, useRef } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  moveScreen,
  placeOf,
  pressScreen,
  releasePress,
  SCREEN_GIVE_UP_MS,
  SCREEN_PRESS_HOLD_MS,
  screenMove,
  takePress,
  useGlide,
  useScreenMotion,
} from "./screen-transition";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true;

const animate = vi.fn(() => ({ finished: Promise.resolve() }));
beforeEach(() => {
  animate.mockClear();
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true,
    value: animate,
  });
});
afterEach(() => {
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

it("shows the tapped place's outline at once, sliding in, until the router arrives", async () => {
  // A phone: the page area slides sideways (wide screens rise instead).
  const realMatchMedia = window.matchMedia;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({ matches: false }),
  });
  const frame = await mount("/dashboard");
  const navigate = vi.fn();
  await act(async () => {
    expect(moveScreen(navigate, "/dashboard", "/leads")).toBe(true);
  });
  expect(navigate).toHaveBeenCalledOnce();
  expect(frame.host.textContent).toBe("/leads");
  // Slid in from the side it moves towards (a phone), never a view
  // transition, whose overlay would take the click.
  const [frames] = animate.mock.calls[0] as unknown as [Keyframe[]];
  expect(frames[0]).toMatchObject({ opacity: 0, transform: "translateX(28px)" });
  await frame.render("/leads");
  expect(frame.host.textContent).toBe("page");
  // The page taking the outline's place doesn't move again.
  expect(animate).toHaveBeenCalledOnce();
  // Coming back later shows the page, not the old outline.
  await frame.render("/dashboard");
  expect(frame.host.textContent).toBe("page");
  await frame.unmount();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: realMatchMedia,
  });
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

it("fades the page area, opacity only, for a move no tap started", async () => {
  const frame = await mount("/leads");
  expect(animate).not.toHaveBeenCalled();
  await frame.render("/analysis/calls");
  expect(animate).toHaveBeenCalledOnce();
  // Opacity only: the page's fixed bars must not move with it.
  const [frames] = animate.mock.calls[0] as unknown as [Keyframe[]];
  expect(frames.every((frame) => !("transform" in frame))).toBe(true);
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

it("never presses towards the place on screen", () => {
  expect(pressScreen("/leads", "/leads")).toBe(false);
  expect(takePress("/leads")).toBe(false);
});

function Tabs({ selected }: { selected: number }) {
  const ref = useRef<HTMLElement | null>(null);
  useGlide(ref, "[aria-current] i", selected);
  return (
    <nav ref={ref}>
      {[0, 1, 2].map((tab) => (
        <a key={tab} aria-current={tab === selected ? "page" : undefined}>
          <i data-tab={tab} />
        </a>
      ))}
    </nav>
  );
}

it("glides the selected tab's capsule from where it was", async () => {
  const rect = (left: number) =>
    ({ left, top: 0, width: 60, height: 40 }) as DOMRect;
  const spy = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      return rect(Number(this.dataset.tab ?? 0) * 70);
    });
  const host = document.createElement("div");
  const root = createRoot(host);
  await act(async () => root.render(<Tabs selected={0} />));
  expect(animate).not.toHaveBeenCalled();
  await act(async () => root.render(<Tabs selected={2} />));
  expect(animate).toHaveBeenCalledOnce();
  const [frames] = animate.mock.calls[0] as unknown as [Keyframe[]];
  // From tab 0 (left 0) to tab 2 (left 140): it starts 140 px back.
  expect(frames[0].transform).toBe("translate(-140px, 0px) scale(1, 1)");
  expect(frames[1].transform).toBe("none");
  spy.mockRestore();
  await act(async () => root.unmount());
});
