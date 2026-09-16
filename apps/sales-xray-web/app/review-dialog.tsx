"use client";

import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { ArrowLeft, ArrowRight, X } from "lucide-react";
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
  icon?: ReactNode;
  tone?: "mint" | "orange" | "blue" | "violet";
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
  icon,
  tone = "mint",
  children,
}: Props) {
  const prefix = useId();
  const closeButton = useRef<HTMLButtonElement>(null);
  const modal = useRef<HTMLDialogElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const previousPosition = useRef<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (
      open &&
      previousPosition.current !== null &&
      previousPosition.current !== position
    ) {
      if (bodyRef.current) bodyRef.current.scrollTop = 0;
      heading.current?.focus({ preventScroll: true });
    }
    previousPosition.current = open ? position : null;
  }, [open, position]);

  useEffect(() => {
    if (!open) return;
    previousFocus.current = document.activeElement as HTMLElement | null;
    const element = modal.current;
    // Native top-layer modality escapes transformed/scrolling report panels
    // while retaining their inherited styles and the report's print content.
    if (element && !element.open) element.showModal();
    const frame = window.setTimeout(() => {
      const dialog = closeButton.current?.closest('[role="dialog"]');
      if (!dialog?.contains(document.activeElement))
        closeButton.current?.focus();
    }, 20);
    return () => {
      window.clearTimeout(frame);
      element?.close();
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

  function trapFocus(event: ReactKeyboardEvent<HTMLDialogElement>) {
    if (event.key !== "Tab") return;
    const dialog = event.currentTarget;
    const focusable = [
      ...dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [href], [tabindex]:not([tabindex="-1"])',
      ),
    ].filter((element) => {
      if (element.closest("[hidden], [inert]")) return false;
      const closed = element.closest("details:not([open])");
      if (closed && !closed.querySelector("summary")?.contains(element))
        return false;
      for (
        let node: HTMLElement | null = element;
        node && node !== dialog;
        node = node.parentElement
      ) {
        const style = getComputedStyle(node);
        if (style.display === "none" || style.visibility === "hidden")
          return false;
      }
      return true;
    });
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
    <dialog
      ref={modal}
      className={styles.backdrop}
      data-review-backdrop={open ? "open" : undefined}
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${prefix}-title`}
      aria-describedby={`${prefix}-position`}
      onKeyDown={trapFocus}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {open ? (
        <div className={styles.dialog} data-tone={tone}>
          <header className={styles.header}>
            {icon && (
              <span className={styles.icon} aria-hidden="true">
                {icon}
              </span>
            )}
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
              <X size={22} aria-hidden="true" />
            </button>
          </header>
          <div ref={bodyRef} className={styles.body}>
            {children}
          </div>
          <footer className={styles.footer}>
            <button
              className={styles.secondaryAction}
              type="button"
              data-review-previous
              onClick={onPrevious}
              disabled={previousDisabled}
            >
              <ArrowLeft size={18} aria-hidden="true" /> {previousLabel}
            </button>
            <button
              className={styles.primaryAction}
              type="button"
              data-review-next
              onClick={onNext}
              disabled={nextDisabled}
            >
              {nextLabel} <ArrowRight size={18} aria-hidden="true" />
            </button>
          </footer>
        </div>
      ) : (
        children
      )}
    </dialog>
  );
  return open ? body : children;
}
