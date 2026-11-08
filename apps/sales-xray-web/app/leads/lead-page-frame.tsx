"use client";

/**
 * A lead as a page, not a sheet (lead page P5, the owner's pick, 8 Nov 2026:
 * "Build P5"; docs/design/screens/lead/spec.md §2): from the top of the screen
 * to the tab bar, its own bar with Back and ⋯, one scroll. The list stays
 * where it was under it, kept out of reach, so Back (the phone's or this one)
 * comes back to the same row and scroll (#172: two scrollbars). The tab bar
 * stays in reach. It sits outside the page's scroller, which slides in on a
 * transform that would hold a fixed box inside it. Back on the list, the
 * lead's row is lit for a second (spec §3).
 */

import { ArrowLeft } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useBackClose } from "../ui/back-close";
import styles from "./lead-page.module.css";

/** The row the lead was opened from, lit for a second once the page has
 *  closed: only a row that is itself positioned, so the light covers it alone. */
export function lightRow(from: Element | null) {
  const row = from?.closest<HTMLElement>("[data-lead-row]");
  if (!row || getComputedStyle(row).position === "static") return;
  row.scrollIntoView?.({ block: "nearest" });
  row.classList.add(styles.backLit);
  window.setTimeout(() => row.classList.remove(styles.backLit), 1000);
}

export function LeadPageFrame({
  open,
  label,
  onClose,
  footer,
  menuSlot,
  children,
}: {
  open: boolean;
  label: string;
  onClose: () => void;
  /** Its foot above the tab bar: the one Call. */
  footer?: ReactNode;
  /** The bar's end, where the lead puts its ⋯ menu. */
  menuSlot?: (node: HTMLElement | null) => void;
  children: ReactNode;
}) {
  useBackClose(open, onClose);
  const back = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const page = document.getElementById("main-content");
    const before =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    page?.setAttribute("inert", "");
    back.current?.focus({ preventScroll: true });
    return () => {
      page?.removeAttribute("inert");
      if (before?.isConnected) {
        before.focus({ preventScroll: true });
        lightRow(before);
      }
    };
  }, [open]);
  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <section className={styles.page} aria-label={label} data-lead-page="">
      <div className={styles.bar}>
        <button
          ref={back}
          type="button"
          className={styles.barButton}
          aria-label="Back to Leads"
          onClick={onClose}
        >
          <ArrowLeft size={24} aria-hidden="true" />
        </button>
        <span ref={menuSlot} className={styles.barEnd} />
      </div>
      <div className={styles.body}>{children}</div>
      {footer ? <div className={styles.dock}>{footer}</div> : null}
    </section>,
    document.body,
  );
}
