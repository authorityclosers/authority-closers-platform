/**
 * A button that acts on the first touch, even while the screen is still
 * gliding (27 Oct 2026, the company phone's Call: on 1.0.44 a third of its
 * Call presses did nothing).
 *
 * On a phone, a tap made while a list or sheet is still gliding after a flick
 * only stops the glide. The browser sends pointerdown and pointerup but no
 * click, so a click handler never runs and the seller taps again. Measured on
 * a Redmi: 8 of 8 such taps lost their click, and 4 of 4 after the glide ended
 * kept it. So a clean touch acts on its own pointerup:
 * - touch only;
 * - the finger moved at most TAP_SLOP_PX;
 * - it was lifted within TAP_MAX_MS.
 * The click that usually follows within CLICK_AFTER_MS is ignored, so nothing
 * acts twice.
 *
 * A scroll that starts on the button ends in pointercancel, so it never acts.
 * A mouse, a keyboard (Enter, Space) and screen readers (TalkBack's double tap)
 * send a click with no touch pointer events, and keep acting on that click.
 *
 * Plain handlers with their state per element (no hook), so a list row can use
 * them too: `<button {...firstTap(act)} />`.
 */
import type {
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";

export const TAP_SLOP_PX = 10;
export const TAP_MAX_MS = 700;
export const CLICK_AFTER_MS = 800;
/** A touch that acted and got no click within this long: a glide took it. */
export const RESCUE_MS = 500;

/**
 * How a press went:
 * - touch / click: it acted;
 * - rescued: it acted on a touch whose click never came (a glide would have
 *   lost it);
 * - drag / moved / long: a touch that didn't act.
 */
export type FirstTapOutcome =
  | "touch"
  | "click"
  | "rescued"
  | "drag"
  | "moved"
  | "long";

type Press = { id: number; x: number; y: number; at: number };
type State = { press: Press | null; actedAt: number; clicked: boolean };

const states = new WeakMap<Element, State>();

function stateOf(element: Element): State {
  let state = states.get(element);
  if (!state) {
    state = { press: null, actedAt: -Infinity, clicked: false };
    states.set(element, state);
  }
  return state;
}

export type FirstTapEvent<T extends Element> =
  | ReactMouseEvent<T>
  | ReactPointerEvent<T>;

export function firstTap<T extends Element>(
  act: (event: FirstTapEvent<T>) => void,
  report?: (outcome: FirstTapOutcome) => void,
) {
  return {
    onPointerDown(event: ReactPointerEvent<T>) {
      if (event.pointerType !== "touch" || !event.isPrimary) return;
      stateOf(event.currentTarget).press = {
        id: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        at: performance.now(),
      };
    },
    onPointerCancel(event: ReactPointerEvent<T>) {
      const state = stateOf(event.currentTarget);
      if (!state.press || state.press.id !== event.pointerId) return;
      state.press = null;
      report?.("drag");
    },
    onPointerUp(event: ReactPointerEvent<T>) {
      if (event.pointerType !== "touch") return;
      const state = stateOf(event.currentTarget);
      const press = state.press;
      state.press = null;
      if (!press || press.id !== event.pointerId) return;
      const now = performance.now();
      if (
        Math.hypot(event.clientX - press.x, event.clientY - press.y) >
        TAP_SLOP_PX
      ) {
        report?.("moved");
        return;
      }
      if (now - press.at > TAP_MAX_MS) {
        report?.("long");
        return;
      }
      state.actedAt = now;
      state.clicked = false;
      act(event);
      report?.("touch");
      if (report)
        window.setTimeout(() => {
          if (!state.clicked && state.actedAt === now) report("rescued");
        }, RESCUE_MS);
    },
    onClick(event: ReactMouseEvent<T>) {
      const state = stateOf(event.currentTarget);
      if (performance.now() - state.actedAt < CLICK_AFTER_MS) {
        // The touch already acted: this is its own click.
        state.clicked = true;
        event.preventDefault();
        return;
      }
      act(event);
      report?.("click");
    },
  };
}
