// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const phone = vi.hoisted(() => ({ app: false, buzz: vi.fn() }));
vi.mock("../leads/native-phone", () => ({
  buzz: phone.buzz,
  inPhoneApp: () => phone.app,
}));

const { PullMark, pullDistance, usePullToRefresh, PULL_READY } = await import(
  "./pull-refresh"
);

(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let finish: () => void = () => undefined;
const refresh = vi.fn<() => Promise<void>>();

function Page() {
  const { area, spinner } = usePullToRefresh(refresh);
  return (
    <div ref={area} data-testid="area">
      <PullMark mark={spinner} />
      <p>Leads</p>
    </div>
  );
}

beforeEach(async () => {
  phone.buzz.mockClear();
  phone.app = false;
  refresh.mockReset();
  refresh.mockImplementation(
    () => new Promise<void>((resolve) => (finish = resolve)),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Page />));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const area = () => host.querySelector("[data-testid=area]") as HTMLElement;
const mark = () => host.querySelector("[aria-hidden=true]") as HTMLElement;
const touch = (type: string, y: number) => {
  const event = new Event(type, { bubbles: true }) as Event & {
    touches: { clientX: number; clientY: number }[];
  };
  event.touches = type === "touchend" ? [] : [{ clientX: 100, clientY: y }];
  area().dispatchEvent(event);
};

it("draws the brand's five bars, the middle one an i", () => {
  const bars = mark().querySelectorAll("i");
  expect(bars).toHaveLength(5);
  expect(bars[2].hasAttribute("data-dot")).toBe(true);
  expect(mark().dataset.mode).toBe("idle");
});

it("rises with the pull, refreshes past the line with one tick, then folds away", async () => {
  touch("touchstart", 100);
  touch("touchmove", 140);
  expect(mark().dataset.mode).toBe("pull");
  expect(Number(mark().style.getPropertyValue("--pull"))).toBeCloseTo(
    20 / PULL_READY,
  );
  touch("touchmove", 100 + PULL_READY * 2);
  // In a browser the tick comes on letting go (a buzz needs a finished touch there).
  expect(phone.buzz).not.toHaveBeenCalled();
  touch("touchend", 0);
  expect(phone.buzz).toHaveBeenCalledTimes(1);
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(mark().dataset.mode).toBe("busy");
  await act(async () => finish());
  expect(mark().dataset.mode).toBe("idle");
  expect(mark().style.opacity).toBe("0");
});

it("ticks as the line is crossed inside the phone app, once", () => {
  phone.app = true;
  touch("touchstart", 100);
  touch("touchmove", 100 + PULL_READY * 2);
  touch("touchmove", 100 + PULL_READY * 2 + 10);
  expect(phone.buzz).toHaveBeenCalledTimes(1);
  touch("touchend", 0);
  expect(phone.buzz).toHaveBeenCalledTimes(1);
});

it("lets a short pull go without refreshing", () => {
  touch("touchstart", 100);
  touch("touchmove", 140);
  touch("touchend", 0);
  expect(refresh).not.toHaveBeenCalled();
  expect(mark().dataset.mode).toBe("idle");
});

it("pulls at half speed, capped", () => {
  expect(pullDistance(-20)).toBe(0);
  expect(pullDistance(100)).toBe(50);
  expect(pullDistance(1000)).toBe(96);
});
