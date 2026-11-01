"use client";

/**
 * Home rows you act on in place (competitor teardown #1, 1 Nov 2026: Pipedrive
 * Focus, Close Inbox): swipe right does it, swipe left moves it to one of the
 * after-call's times. Hold or right-click opens the same times, so a mouse
 * reaches them too. The gestures are the Leads lists' (leads/gestures.ts).
 */

import { CalendarClock, Check } from "lucide-react";
import type { ReactNode } from "react";

import { ActionSheet } from "../leads/action-sheet";
import { useRowGestures } from "../leads/gestures";
import styles from "./seller-home.module.css";

export type Later = "hour" | "evening" | "morning" | "week";

/** The after-call's times, in its words. */
export const LATER: { key: Later; label: string }[] = [
  { key: "hour", label: "In 1 hour" },
  { key: "evening", label: "This evening" },
  { key: "morning", label: "Tomorrow morning" },
  { key: "week", label: "Next week" },
];

export function SwipeRow({
  className,
  done,
  onDone,
  onLater,
  late = false,
  children,
}: {
  className: string;
  /** What a right swipe says it does: "Done", "Call". */
  done: string;
  onDone?: () => void;
  onLater?: () => void;
  /** Past its time: first, and in red. */
  late?: boolean;
  children: ReactNode;
}) {
  const { row, face, bind } = useRowGestures({
    onSwipeRight: onDone,
    onSwipeLeft: onLater,
    onHold: onLater,
  });
  return (
    <li
      ref={row}
      className={`${styles.swipeRow} ${className}`}
      data-late={late || undefined}
      {...bind}
    >
      <span className={styles.swipeBack} aria-hidden="true">
        <span data-side="right">
          <Check size={18} />
          {done}
        </span>
        <span data-side="left">
          <CalendarClock size={18} />
          Later
        </span>
      </span>
      <div ref={face} className={styles.swipeFace}>
        {children}
      </div>
    </li>
  );
}

/** When to do it instead: the after-call's four times. */
export function LaterSheet({
  title,
  open,
  onPick,
  onClose,
}: {
  title: string;
  open: boolean;
  onPick: (when: Later) => void;
  onClose: () => void;
}) {
  return (
    <ActionSheet
      open={open}
      title="When instead?"
      sub={title}
      onClose={onClose}
    >
      <div className={styles.laterTimes}>
        {LATER.map((time) => (
          <button
            key={time.key}
            type="button"
            className={styles.laterTime}
            onClick={() => onPick(time.key)}
          >
            {time.label}
          </button>
        ))}
      </div>
    </ActionSheet>
  );
}
