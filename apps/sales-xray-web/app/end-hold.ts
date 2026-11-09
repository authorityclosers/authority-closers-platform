/**
 * The page keeps room at its end for the corner cards (--sx-corner-h, which
 * the shell's .main adds after the page). When that room shrinks with the
 * page scrolled to its end, the browser pulls the page down to fill it and
 * everything on screen drops (orchestrator, 9 Nov 2026: at 1440 a focused
 * quick add at the end of the Cold list fell 160 px as a card left). So the
 * end keeps what reaches the screen (--sx-end-hold, in the shell's .main)
 * and lets the rest go as the page scrolls up, out of sight.
 */

const HOLD = "--sx-end-hold";

type End = { box: HTMLElement; scroller: Element; target: EventTarget };

let easing: { end: End; stop: () => void } | null = null;

/** The app's content area, and what scrolls it: itself, or the page. */
function endOf(): End | null {
  const box = document.getElementById("main-content");
  if (!box) return null;
  const flow = getComputedStyle(box).overflowY;
  if (flow === "auto" || flow === "scroll")
    return { box, scroller: box, target: box };
  return {
    box,
    scroller: document.scrollingElement ?? document.documentElement,
    target: window,
  };
}

const padOf = (box: HTMLElement) =>
  parseFloat(getComputedStyle(box).paddingBottom) || 0;

/** How far the page can still scroll past the screen's bottom. */
const slackOf = (scroller: Element) =>
  scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;

function letGo() {
  easing?.stop();
  easing = null;
  document.documentElement.style.removeProperty(HOLD);
}

/** The end's padding it needs for what's in view to stay: the padding now, less the scroll left below the screen. */
function hold(end: End, least: number) {
  const root = document.documentElement;
  root.style.setProperty(HOLD, `${Math.ceil(least)}px`);
  if (easing?.end.box === end.box && easing.end.target === end.target) return;
  easing?.stop();
  let frame = 0;
  const ease = () => {
    frame = 0;
    if (!end.box.isConnected) return letGo();
    const held = parseFloat(root.style.getPropertyValue(HOLD)) || 0;
    const least = Math.min(
      held,
      Math.ceil(padOf(end.box) - slackOf(end.scroller)),
    );
    if (least <= 0) return letGo();
    if (least < held) root.style.setProperty(HOLD, `${least}px`);
  };
  const ask = () => {
    if (!frame) frame = window.requestAnimationFrame(ease);
  };
  end.target.addEventListener("scroll", ask, { passive: true });
  easing = {
    end,
    stop: () => {
      window.cancelAnimationFrame(frame);
      end.target.removeEventListener("scroll", ask);
    },
  };
}

/**
 * Runs `shrink`, a change that takes room from the page's end, so that what
 * is on screen stays where it is.
 */
export function keepEndInView(shrink: () => void) {
  const end = endOf();
  if (end) {
    const least = padOf(end.box) - slackOf(end.scroller);
    if (least > 0) hold(end, least);
  }
  shrink();
}
