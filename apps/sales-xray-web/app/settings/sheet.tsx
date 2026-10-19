"use client";

/**
 * A panel over the page for an app's details and longer forms (owner, 20 Oct:
 * "no long forms on the page; details open in a sheet"): from the right on a
 * computer, from the bottom on a phone. Escape, the close button and a press
 * on the dimmed page close it.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";
import { X } from "lucide-react";

import { onBackdrop } from "../ui/kit";
import styles from "./sheet.module.css";

export function Sheet({
  open,
  title,
  lead,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  /** Beside the title: the app's logo and status. */
  lead?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const pressedOutside = useRef(false);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal?.();
    if (!open && dialog.open) dialog.close?.();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={styles.sheet}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onPointerDown={(event) => {
        pressedOutside.current = onBackdrop(event);
      }}
      onClick={(event) => {
        const started = pressedOutside.current;
        pressedOutside.current = false;
        if (started && onBackdrop(event)) onClose();
      }}
    >
      {open ? (
        <>
          <header className={styles.head}>
            {lead}
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
            <button
              type="button"
              className={styles.close}
              aria-label="Close"
              title="Close"
              onClick={onClose}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </header>
          <div className={styles.body}>{children}</div>
          {footer ? <footer className={styles.foot}>{footer}</footer> : null}
        </>
      ) : null}
    </dialog>
  );
}
