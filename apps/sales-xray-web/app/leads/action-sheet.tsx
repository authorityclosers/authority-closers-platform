"use client";

/**
 * A sheet that rises from the bottom on a phone (a small card in the middle on
 * a computer): the long-press menu and the message composer. Native <dialog>,
 * so it sits above an open lead, keeps focus inside and closes on Escape, a
 * tap outside, a swipe down on its grabber or Back.
 */

import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

import { useBackClose } from "../ui/back-close";
import styles from "./leads.module.css";

export function ActionSheet({
  open,
  title,
  sub,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  sub?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const drag = useRef<{ y: number; moved: number } | null>(null);
  // The tap that ends a long-press can land on the new backdrop: ignore it.
  const openedAt = useRef(0);
  useBackClose(open, onClose);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      openedAt.current = Date.now();
      dialog.showModal();
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={styles.actionSheet}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (
          event.target === event.currentTarget &&
          Date.now() - openedAt.current > 500
        )
          onClose();
      }}
    >
      {open ? (
        <div className={styles.actionSheetBody}>
          <div
            className={styles.grabber}
            aria-hidden="true"
            onTouchStart={(event) => {
              drag.current = { y: event.touches[0].clientY, moved: 0 };
            }}
            onTouchMove={(event) => {
              const start = drag.current;
              const body = event.currentTarget.parentElement;
              if (!start || !body) return;
              start.moved = Math.max(0, event.touches[0].clientY - start.y);
              body.style.transform = `translateY(${start.moved}px)`;
            }}
            onTouchEnd={(event) => {
              const body = event.currentTarget.parentElement;
              const moved = drag.current?.moved ?? 0;
              drag.current = null;
              if (body) body.style.transform = "";
              if (moved > 80) onClose();
            }}
          />
          <header className={styles.actionSheetHead}>
            <span>
              <h2 id={titleId}>{title}</h2>
              {sub ? <p>{sub}</p> : null}
            </span>
            <button
              type="button"
              className={styles.actionSheetClose}
              onClick={onClose}
              aria-label="Close"
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>
          {children}
        </div>
      ) : null}
    </dialog>
  );
}
