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

const matches = (query: string) =>
  typeof window !== "undefined" &&
  window.matchMedia?.(query).matches === true;
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
  try {
    return element.animate(frames, options);
  } catch {
    return element.animate(frames, {
      ...options,
      easing: "cubic-bezier(0.32, 0.72, 0, 1)",
    });
  }
}

function restingFrom(wide: Wide): Keyframe {
  if (reducedMotion()) return { opacity: 0 };
  if (matches(SHEET_PHONE_QUERY)) return { transform: "translate3d(0, 100%, 0)" };
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

  // Phones: the sheet follows the finger.
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
    const start = (event: TouchEvent) => {
      drag = null;
      if (!matches(SHEET_PHONE_QUERY) || event.touches.length !== 1) return;
      const target = event.target as Element | null;
      if (
        target?.closest?.(
          "input, textarea, select, [contenteditable], [data-sheet-no-drag]",
        )
      )
        return;
      drag = {
        y: event.touches[0].clientY,
        scroller: scrollerFor(target, panel),
        dragging: null,
        offset: 0,
        past: false,
        samples: [],
      };
    };
    const move = (event: TouchEvent) => {
      if (!drag) return;
      const y = event.touches[0].clientY;
      const dy = y - drag.y;
      if (drag.dragging === null) {
        if (Math.abs(dy) < 6) return;
        drag.dragging = dy > 0 && (drag.scroller?.scrollTop ?? 0) <= 0;
        if (!drag.dragging) {
          drag = null;
          return;
        }
        settle(panel, scrim);
      }
      if (event.cancelable) event.preventDefault();
      // Down follows the finger; up gives a little, like a rubber band.
      drag.offset = dy > 0 ? dy : dy / 6;
      panel.style.transform = `translate3d(0, ${drag.offset}px, 0)`;
      const height = panel.getBoundingClientRect().height || 1;
      scrim.style.opacity = String(
        Math.max(0, 1 - Math.max(0, drag.offset) / height),
      );
      const now = event.timeStamp;
      drag.samples = [...drag.samples, { y, t: now }].filter(
        (sample) => now - sample.t <= 100,
      );
      const past = drag.offset > limit();
      if (past !== drag.past) {
        drag.past = past;
        if (past) tick();
      }
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
    const end = () => {
      const done = drag;
      drag = null;
      if (!done?.dragging) return;
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
    panel.addEventListener("touchstart", start, { passive: true });
    panel.addEventListener("touchmove", move, { passive: false });
    panel.addEventListener("touchend", end);
    panel.addEventListener("touchcancel", end);
    return () => {
      panel.removeEventListener("touchstart", start);
      panel.removeEventListener("touchmove", move);
      panel.removeEventListener("touchend", end);
      panel.removeEventListener("touchcancel", end);
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
    >
      <div
        ref={scrimRef}
        className={styles.scrim}
        aria-hidden="true"
        onClick={onClose}
      />
      <div ref={panelRef} className={styles.panel}>
        <span className={styles.grabber} aria-hidden="true" />
        {shown ? (
          <>
            {head ? (
              <header className={styles.head}>
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
            {footer ? <footer className={styles.footer}>{footer}</footer> : null}
          </>
        ) : null}
      </div>
    </dialog>
  );
}
