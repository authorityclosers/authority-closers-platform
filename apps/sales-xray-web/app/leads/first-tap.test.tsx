// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import {
  CLICK_AFTER_MS,
  firstTap,
  RESCUE_MS,
  TAP_MAX_MS,
  type FirstTapOutcome,
} from "./first-tap";

(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

// 27 Oct 2026, the company phone's Call: a tap while the sheet still glides
// sends pointerdown and pointerup but no click (8 of 8 on a Redmi).
let now = 0;
let root: Root;
let host: HTMLDivElement;
let acted: string[];
let outcomes: FirstTapOutcome[];

beforeEach(async () => {
  now = 1_000;
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  vi.spyOn(performance, "now").mockImplementation(() => now);
  acted = [];
  outcomes = [];
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <a
        id="call"
        href="tel:+910000000000"
        {...firstTap(
          (event) => {
            // As Call does: the page places the call, never the link itself.
            event.preventDefault();
            acted.push(event.type);
          },
          (outcome) => outcomes.push(outcome),
        )}
      >
        Call
      </a>,
    ),
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const call = () => host.querySelector<HTMLAnchorElement>("#call")!;

function pointer(
  type: "pointerdown" | "pointerup" | "pointercancel",
  init: { pointerType?: string; x?: number; y?: number; id?: number } = {},
) {
  call().dispatchEvent(
    new PointerEvent(type, {
      bubbles: true,
      cancelable: true,
      pointerType: init.pointerType ?? "touch",
      isPrimary: true,
      pointerId: init.id ?? 1,
      clientX: init.x ?? 20,
      clientY: init.y ?? 20,
    }),
  );
}

/** The click a browser sends after a tap; true when nothing stopped it. */
function click(): boolean {
  return call().dispatchEvent(
    new MouseEvent("click", { bubbles: true, cancelable: true }),
  );
}

it("acts on a touch as the finger lifts, and the click after it does nothing more", async () => {
  await act(async () => pointer("pointerdown"));
  now += 80;
  await act(async () => pointer("pointerup"));
  expect(acted).toEqual(["pointerup"]);
  // The tel: link's own click is stopped: no second call, no second dialler.
  let followed = true;
  await act(async () => {
    followed = click();
  });
  expect(followed).toBe(false);
  expect(acted).toEqual(["pointerup"]);
  await act(async () => vi.advanceTimersByTime(RESCUE_MS + 10));
  expect(outcomes).toEqual(["touch"]);
});

it("still acts when a glide takes the click, and says so", async () => {
  await act(async () => pointer("pointerdown"));
  now += 60;
  await act(async () => pointer("pointerup"));
  // No click comes: the tap only stopped the glide.
  await act(async () => vi.advanceTimersByTime(RESCUE_MS + 10));
  expect(acted).toEqual(["pointerup"]);
  expect(outcomes).toEqual(["touch", "rescued"]);
});

it("keeps the click for a mouse, a keyboard and a screen reader", async () => {
  // A mouse: its pointer events are not touch; the click acts.
  await act(async () => pointer("pointerdown", { pointerType: "mouse" }));
  await act(async () => pointer("pointerup", { pointerType: "mouse" }));
  expect(acted).toEqual([]);
  await act(async () => {
    click();
  });
  expect(acted).toEqual(["click"]);
  // Enter on a focused link, or TalkBack's double tap: a click with no pointer events.
  now += CLICK_AFTER_MS + 1;
  await act(async () => {
    call().focus();
    call().click();
  });
  now += CLICK_AFTER_MS + 1;
  await act(async () => {
    call().click();
  });
  expect(acted).toEqual(["click", "click", "click"]);
  expect(outcomes).toEqual(["click", "click", "click"]);
});

it("never acts on a swipe, a finger that moved or a long press", async () => {
  // A scroll that starts on Call: the browser cancels the pointer.
  await act(async () => pointer("pointerdown"));
  await act(async () => pointer("pointercancel"));
  // A finger that moved more than the slop.
  await act(async () => pointer("pointerdown", { x: 20, y: 20 }));
  now += 100;
  await act(async () => pointer("pointerup", { x: 20, y: 45 }));
  // A long press.
  await act(async () => pointer("pointerdown"));
  now += TAP_MAX_MS + 50;
  await act(async () => pointer("pointerup"));
  expect(acted).toEqual([]);
  expect(outcomes).toEqual(["drag", "moved", "long"]);
});

it("treats a later tap as a new press, and ignores another finger's lift", async () => {
  await act(async () => pointer("pointerdown"));
  await act(async () => pointer("pointerup"));
  now += CLICK_AFTER_MS + 1;
  // A click long after the touch is a press of its own.
  await act(async () => {
    click();
  });
  // A lift from a finger that never went down here does nothing.
  await act(async () => pointer("pointerup", { id: 7 }));
  expect(acted).toEqual(["pointerup", "click"]);
});
