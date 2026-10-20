"use client";

/**
 * The one sheet (design system v2). Owner, 20 Oct: "this does not go away
 * when swiped down it should react on mobile".
 *
 * Phones: the sheet rises from the bottom as frosted glass, with a grabber,
 * and follows the finger. A drag down past a third of its height, or a
 * quick flick, closes it; a shorter drag springs back. Dragging works from
 * the grabber and the head, and from the body once its content is at the
 * top, so scrolling a long sheet never closes it by mistake.
 * Computers: the sheet slides in from the right (details, forms) or appears
 * in the middle (short tasks).
 *
 * It is a native <dialog>: focus stays inside, Escape closes it, and so
 * does a tap on the dimmed page. Reduce motion: fades only.
 */
import { X } from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { tick } from "./haptics";
import styles from "./sheet.module.css";

export const SHEET_PHONE_QUERY = "(max-width: 899px)";
/** Let go past this share of the sheet's height and it closes. */
export const SHEET_DISMISS_SHARE = 0.32;
const DISMISS_MIN_PX = 96;
/** A flick down faster than this (px per ms) closes it from anywhere. */
export const SHEET_FLICK = 0.55;
/**
 * Pointer clicks this soon after opening are ignored: the second half of a
 * double tap, or a ghost click, on the control that opened the sheet would
 * otherwise land on whatever row has just risen under the finger (the More
 * tab opened Settings that way in the orchestrator's pane, 20 Oct).
 */
export const SHEET_SETTLE_MS = 350;

const matches = (query: string) =>
  typeof window !== "undefined" && window.matchMedia?.(query).matches === true;
const reducedMotion = () => matches("(prefers-reduced-motion: reduce)");

type Wide = "right" | "center";

function easing(panel: HTMLElement, token: string, fallback: string) {
  const value = getComputedStyle(panel).getPropertyValue(token).trim();
  return value || fallback;
}

/** WAAPI with the token's spring where the browser takes linear() curves. */
function play(
  element: HTMLElement,
  frames: Keyframe[],
  options: KeyframeAnimationOptions,
): Animation | null {
  if (typeof element.animate !== "function") return null;
  let animation: Animation;
  try {
    animation = element.animate(frames, options);
  } catch {
    animation = element.animate(frames, {
      ...options,
      easing: "cubic-bezier(0.32, 0.72, 0, 1)",
    });
  }
  // Settling or closing early cancels the motion on purpose; its finished
  // promise then rejects (AbortError), which is not an error here.
  animation.finished?.catch(() => undefined);
  return animation;
}

function restingFrom(wide: Wide): Keyframe {
  if (reducedMotion()) return { opacity: 0 };
  if (matches(SHEET_PHONE_QUERY))
    return { transform: "translate3d(0, 100%, 0)" };
  return wide === "right"
    ? { transform: "translate3d(calc(100% + 24px), 0, 0)" }
    : { transform: "scale(0.96)", opacity: 0 };
}

function enter(panel: HTMLElement, scrim: HTMLElement, wide: Wide) {
  const phone = matches(SHEET_PHONE_QUERY);
  const reduce = reducedMotion();
  play(panel, [restingFrom(wide), { transform: "none", opacity: 1 }], {
    duration: reduce ? 160 : phone ? 460 : 320,
    easing: reduce
      ? "linear"
      : easing(panel, "--sx-spring-calm", "cubic-bezier(0.32, 0.72, 0, 1)"),
  });
  play(scrim, [{ opacity: 0 }, { opacity: 1 }], {
    duration: reduce ? 160 : 260,
    easing: "linear",
  });
}

async function leave(panel: HTMLElement, scrim: HTMLElement, wide: Wide) {
  const reduce = reducedMotion();
  const duration = reduce ? 140 : matches(SHEET_PHONE_QUERY) ? 260 : 200;
  const from = panel.style.transform || "none";
  const fade = scrim.style.opacity || "1";
  const motion = play(
    panel,
    [{ transform: from, opacity: 1 }, restingFrom(wide)],
    { duration, easing: "cubic-bezier(0.4, 0, 1, 1)", fill: "forwards" },
  );
  play(scrim, [{ opacity: fade }, { opacity: 0 }], {
    duration,
    easing: "linear",
    fill: "forwards",
  });
  // Never wait on an animation that doesn't report its end.
  await Promise.race([
    motion?.finished.catch(() => undefined),
    new Promise((resolve) => window.setTimeout(resolve, duration + 80)),
  ]);
}

function settle(panel: HTMLElement, scrim: HTMLElement) {
  for (const element of [panel, scrim])
    for (const animation of element.getAnimations?.() ?? []) animation.cancel();
  panel.style.transform = "";
  scrim.style.opacity = "";
}

/** The nearest scrolled box between the touch and the sheet, if any. */
function scrollerFor(target: Element | null, panel: HTMLElement) {
  for (let node = target; node && node !== panel; node = node.parentElement) {
    if (!(node instanceof HTMLElement)) continue;
    const overflow = getComputedStyle(node).overflowY;
    if (
      (overflow === "auto" || overflow === "scroll") &&
      node.scrollHeight > node.clientHeight + 1
    )
      return node;
  }
  return null;
}

type Drag = {
  y: number;
  scroller: HTMLElement | null;
  dragging: boolean | null;
  offset: number;
  past: boolean;
  samples: { y: number; t: number }[];
};

export type SheetProps = {
  open: boolean;
  onClose: () => void;
  /** Always named for screen readers; drawn unless hideTitle. */
  title: string;
  hideTitle?: boolean;
  description?: ReactNode;
  /** Beside the title: an app's logo, a status. */
  lead?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  /** Computers only: from the right (default) or in the middle. */
  wide?: Wide;
  /** The round close button in the head (default on). */
  closeButton?: boolean;
  className?: string;
};

export function Sheet({
  open,
  onClose,
  title,
  hideTitle = false,
  description,
  lead,
  footer,
  children,
  wide = "right",
  closeButton = true,
  className,
}: SheetProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const scrimRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // When it last opened: pointer clicks right after are not meant for it.
  const openedAt = useRef(-Infinity);
  // The content stays while the sheet slides away.
  const [shown, setShown] = useState(open);
  if (open && !shown) setShown(true);
  const latest = useRef({ open, onClose });
  useEffect(() => {
    latest.current = { open, onClose };
  });

  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    const panel = panelRef.current;
    const scrim = scrimRef.current;
    if (!dialog || !panel || !scrim) return;
    if (open) {
      if (dialog.open) {
        settle(panel, scrim);
        return;
      }
      dialog.showModal?.();
      if (!dialog.open) dialog.setAttribute("open", "");
      openedAt.current = performance.now();
      enter(panel, scrim, wide);
      return;
    }
    if (!dialog.open) return;
    let cancelled = false;
    void leave(panel, scrim, wide).then(() => {
      if (cancelled) return;
      settle(panel, scrim);
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      setShown(false);
    });
    return () => {
      cancelled = true;
    };
  }, [open, shown, wide]);

  // Phones: the sheet follows the finger, a mouse or a pen. A finger drags
  // from anywhere (the body only once it is scrolled to the top); a mouse or
  // a pen drags from the grabber and the head, as a finger would.
  useEffect(() => {
    const panel = panelRef.current;
    const scrim = scrimRef.current;
    if (!shown || !panel || !scrim) return;
    let drag: Drag | null = null;
    const limit = () =>
      Math.max(
        DISMISS_MIN_PX,
        panel.getBoundingClientRect().height * SHEET_DISMISS_SHARE,
      );
    const begin = (y: number, at: number, target: Element | null) => {
      drag = null;
      if (!matches(SHEET_PHONE_QUERY)) return false;
      if (
        target?.closest?.(
          "input, textarea, select, [contenteditable], [data-sheet-no-drag]",
        )
      )
        return false;
      drag = {
        y,
        scroller: scrollerFor(target, panel),
        dragging: null,
        offset: 0,
        past: false,
        samples: [{ y, t: at }],
      };
      return true;
    };
    const follow = (y: number, at: number) => {
      if (!drag) return false;
      const dy = y - drag.y;
      if (drag.dragging === null) {
        if (Math.abs(dy) < 6) return false;
        drag.dragging = dy > 0 && (drag.scroller?.scrollTop ?? 0) <= 0;
        if (!drag.dragging) {
          drag = null;
          return false;
        }
        settle(panel, scrim);
      }
      // Down follows the pointer; up gives a little, like a rubber band.
      drag.offset = dy > 0 ? dy : dy / 6;
      panel.style.transform = `translate3d(0, ${drag.offset}px, 0)`;
      const height = panel.getBoundingClientRect().height || 1;
      scrim.style.opacity = String(
        Math.max(0, 1 - Math.max(0, drag.offset) / height),
      );
      drag.samples = [...drag.samples, { y, t: at }].filter(
        (sample, index, all) =>
          index === all.length - 1 || at - sample.t <= 100,
      );
      const past = drag.offset > limit();
      if (past !== drag.past) {
        drag.past = past;
        if (past) tick();
      }
      return true;
    };
    const springBack = () => {
      const from = panel.style.transform;
      const fade = scrim.style.opacity;
      settle(panel, scrim);
      if (!from) return;
      play(panel, [{ transform: from }, { transform: "none" }], {
        duration: reducedMotion() ? 120 : 420,
        easing: reducedMotion()
          ? "linear"
          : easing(panel, "--sx-spring", "cubic-bezier(0.32, 0.72, 0, 1)"),
      });
      play(scrim, [{ opacity: fade || "1" }, { opacity: 1 }], {
        duration: 200,
        easing: "linear",
      });
    };
    const finish = () => {
      const done = drag;
      drag = null;
      if (!done?.dragging) return;
      // Speed over the last moments; a single big jump counts by distance.
      const [first, last] = [done.samples[0], done.samples.at(-1)];
      const speed =
        first && last && last.t > first.t
          ? (last.y - first.y) / (last.t - first.t)
          : 0;
      if (done.offset > limit() || speed > SHEET_FLICK) {
        if (done.offset <= limit()) tick();
        latest.current.onClose();
        // Kept open by its owner (unsaved changes): back it comes.
        requestAnimationFrame(() => {
          if (latest.current.open) springBack();
        });
        return;
      }
      springBack();
    };

    const touchStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) {
        drag = null;
        return;
      }
      begin(
        event.touches[0].clientY,
        event.timeStamp,
        event.target as Element | null,
      );
    };
    const touchMove = (event: TouchEvent) => {
      if (!drag) return;
      if (follow(event.touches[0].clientY, event.timeStamp) && event.cancelable)
        event.preventDefault();
    };

    let pointer: number | null = null;
    const pointerDown = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.button !== 0) return;
      const target = event.target as Element | null;
      // A mouse or a pen holds the sheet by its grabber or its head.
      if (
        !target?.closest?.("[data-sheet-grip]") ||
        target.closest("button, a, input, select, textarea")
      )
        return;
      if (!begin(event.clientY, event.timeStamp, target)) return;
      pointer = event.pointerId;
      // No text selection while dragging.
      event.preventDefault();
      try {
        panel.setPointerCapture(event.pointerId);
      } catch {
        // Capture is a nicety; the move events still arrive.
      }
    };
    const pointerMove = (event: PointerEvent) => {
      if (event.pointerId !== pointer) return;
      follow(event.clientY, event.timeStamp);
    };
    const pointerUp = (event: PointerEvent) => {
      if (event.pointerId !== pointer) return;
      pointer = null;
      // A fast mouse can jump far between its last move and the release.
      follow(event.clientY, event.timeStamp);
      finish();
    };

    panel.addEventListener("touchstart", touchStart, { passive: true });
    panel.addEventListener("touchmove", touchMove, { passive: false });
    panel.addEventListener("touchend", finish);
    panel.addEventListener("touchcancel", finish);
    panel.addEventListener("pointerdown", pointerDown);
    panel.addEventListener("pointermove", pointerMove);
    panel.addEventListener("pointerup", pointerUp);
    panel.addEventListener("pointercancel", pointerUp);
    return () => {
      panel.removeEventListener("touchstart", touchStart);
      panel.removeEventListener("touchmove", touchMove);
      panel.removeEventListener("touchend", finish);
      panel.removeEventListener("touchcancel", finish);
      panel.removeEventListener("pointerdown", pointerDown);
      panel.removeEventListener("pointermove", pointerMove);
      panel.removeEventListener("pointerup", pointerUp);
      panel.removeEventListener("pointercancel", pointerUp);
    };
  }, [shown]);

  const head = !hideTitle || lead || closeButton;
  return (
    <dialog
      ref={dialogRef}
      className={`${styles.sheet}${className ? ` ${className}` : ""}`}
      data-wide={wide}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClickCapture={(event) => {
        // Pointer clicks only (detail counts the presses): a keyboard's
        // Enter or Space is always meant.
        if (
          event.detail > 0 &&
          performance.now() - openedAt.current < SHEET_SETTLE_MS
        ) {
          event.preventDefault();
          event.stopPropagation();
        }
      }}
    >
      <div
        ref={scrimRef}
        className={styles.scrim}
        aria-hidden="true"
        onClick={onClose}
      />
      <div ref={panelRef} className={styles.panel}>
        <span
          className={styles.grabber}
          data-sheet-grip=""
          aria-hidden="true"
        />
        {shown ? (
          <>
            {head ? (
              <header className={styles.head} data-sheet-grip="">
                {lead ? <span className={styles.lead}>{lead}</span> : null}
                <span className={styles.titles}>
                  <h2
                    id={titleId}
                    className={hideTitle ? styles.hidden : styles.title}
                  >
                    {title}
                  </h2>
                  {description && !hideTitle ? (
                    <p className={styles.description}>{description}</p>
                  ) : null}
                </span>
                {closeButton ? (
                  <button
                    type="button"
                    className={styles.close}
                    aria-label="Close"
                    title="Close"
                    onClick={onClose}
                  >
                    <X size={18} aria-hidden="true" />
                  </button>
                ) : null}
              </header>
            ) : (
              <h2 id={titleId} className={styles.hidden}>
                {title}
              </h2>
            )}
            <div className={styles.body}>{children}</div>
            {footer ? (
              <footer className={styles.footer}>{footer}</footer>
            ) : null}
          </>
        ) : null}
      </div>
    </dialog>
  );
}
