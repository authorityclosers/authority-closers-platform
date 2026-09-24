"use client";

import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Lens, type LensState } from "./lens";
import styles from "./toast.module.css";

/**
 * A polite announcement. The live region stays mounted so screen readers hear
 * the message once when it appears; nothing is announced while closed.
 */
export function Toast({
  open,
  title,
  children,
  lens,
  onDismiss,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  lens?: LensState;
  onDismiss?: () => void;
}) {
  return (
    <div
      className={styles.region}
      role="status"
      aria-live="polite"
      aria-atomic="true"
      data-toast-open={open}
    >
      {open ? (
        <div className={styles.toast}>
          {lens ? <Lens state={lens} size={40} /> : null}
          <div className={styles.copy}>
            <strong>{title}</strong>
            {children ? <div className={styles.body}>{children}</div> : null}
          </div>
          {onDismiss ? (
            <button
              type="button"
              className={styles.dismiss}
              aria-label={`Dismiss: ${title}`}
              onClick={onDismiss}
            >
              <X size={18} aria-hidden="true" />
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
