"use client";

import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import styles from "./review-dialog.module.css";

type Props = {
  open: boolean;
  eyebrow: string;
  title: string;
  position: string;
  onClose: () => void;
  onPrevious: () => void;
  onNext: () => void;
  previousDisabled?: boolean;
  nextDisabled?: boolean;
  previousLabel?: string;
  nextLabel?: string;
  closeLabel?: string;
  children: ReactNode;
};

/** A bounded review sheet that preserves the report body and its source actions. */
export function ReviewDialog({
  open,
  eyebrow,
  title,
  position,
  onClose,
  onPrevious,
  onNext,
  previousDisabled = false,
  nextDisabled = false,
  previousLabel = "Previous point",
  nextLabel = "Next point",
  closeLabel = "Close review point",
  children,
}: Props) {
  const prefix = useId();
  const closeButton = useRef<HTMLButtonElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const previousPosition = useRef<string | null>(null);

  useEffect(() => {
    if (
      open &&
      previousPosition.current !== null &&
      previousPosition.current !== position
    )
      heading.current?.focus();
    previousPosition.current = open ? position : null;
  }, [open, position]);

  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement | null;
    const frame = window.setTimeout(() => {
      const dialog = closeButton.current?.closest('[role="dialog"]');
      if (!dialog?.contains(document.activeElement))
        closeButton.current?.focus();
    }, 20);
    return () => {
      window.clearTimeout(frame);
      previousFocus.current?.focus?.();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose, open]);

  function trapFocus(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") return;
    const dialog = event.currentTarget;
    const focusable = [
      ...dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      ),
    ];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (
      event.shiftKey &&
      (document.activeElement === first ||
        document.activeElement === heading.current)
    ) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const body = (
    <div
      className={open ? styles.backdrop : undefined}
      data-review-backdrop={open ? "open" : undefined}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {open ? (
        <div
          className={styles.dialog}
          role="dialog"
          aria-modal="true"
          aria-labelledby={`${prefix}-title`}
          aria-describedby={`${prefix}-position`}
          onKeyDown={trapFocus}
        >
          <header className={styles.header}>
            <div className={styles.heading}>
              <span className={styles.eyebrow}>{position}</span>
              <h2 ref={heading} tabIndex={-1} id={`${prefix}-title`}>
                {title}
              </h2>
              <p id={`${prefix}-position`}>{eyebrow}</p>
            </div>
            <button
              ref={closeButton}
              className={styles.close}
              type="button"
              aria-label={closeLabel}
              onClick={onClose}
            >
              ×
            </button>
          </header>
          <div className={styles.body}>{children}</div>
          <footer className={styles.footer}>
            <button
              className={styles.secondaryAction}
              type="button"
              data-review-previous
              onClick={onPrevious}
              disabled={previousDisabled}
            >
              <span aria-hidden="true">←</span> {previousLabel}
            </button>
            <button
              className={styles.primaryAction}
              type="button"
              data-review-next
              onClick={onNext}
              disabled={nextDisabled}
            >
              {nextLabel} <span aria-hidden="true">→</span>
            </button>
          </footer>
        </div>
      ) : (
        children
      )}
    </div>
  );
  return body;
}
