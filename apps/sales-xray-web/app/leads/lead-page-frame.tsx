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
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { useBackClose } from "../ui/back-close";
import styles from "./lead-page.module.css";

/** The row the lead was opened from, lit for a second once the page has
 *  closed: the row holding what had focus, else the lead's own row by its key
 *  (a tap on a phone may focus nothing: Note 8 Pro, 9 Nov 2026). Only a row
 *  that is itself positioned, so the light covers it alone. */
export function lightRow(
  from: Element | null,
  key: string | null = null,
): HTMLElement | null {
  const row =
    from?.closest<HTMLElement>("[data-lead-row]") ??
    (key
      ? document.querySelector<HTMLElement>(
          `[data-lead-row][data-row-key="${key}"]`,
        )
      : null);
  if (!row || getComputedStyle(row).position === "static") return null;
  row.scrollIntoView?.({ block: "nearest" });
  row.classList.add(styles.backLit);
  window.setTimeout(() => row.classList.remove(styles.backLit), 1000);
  return row;
}

export function LeadPageFrame({
  open,
  label,
  onClose,
  footer,
  menuSlot,
  rowKey = null,
  children,
}: {
  open: boolean;
  label: string;
  onClose: () => void;
  /** The lead's row key in the list (its id), lit on Back. */
  rowKey?: string | null;
  /** Its foot above the tab bar: the one Call. */
  footer?: ReactNode;
  /** The bar's end, where the lead puts its ⋯ menu. */
  menuSlot?: (node: HTMLElement | null) => void;
  children: ReactNode;
}) {
  useBackClose(open, onClose);
  const back = useRef<HTMLButtonElement>(null);
  // The last lead shown (the key goes as the page closes).
  const lastKey = useRef<string | null>(null);
  useEffect(() => {
    if (rowKey) lastKey.current = rowKey;
  }, [rowKey]);
  // What the page covers isn't drawn while it covers it (QA robot aeb37673,
  // 9 Nov 2026): the list under it can still move (a lead arriving, the list
  // filling in), and the browser counts that as the page jumping (0.08 for one
  // row) though nobody sees it. A layout effect, so the list is drawn again in
  // the same frame the page goes, never a blank one.
  useLayoutEffect(() => {
    if (!open) return;
    const covered = document.querySelector<HTMLElement>("[data-shell-content]");
    if (!covered) return;
    const was = covered.style.visibility;
    covered.style.visibility = "hidden";
    return () => {
      covered.style.visibility = was;
    };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    // Everything under the page is out of reach, the app's top bars too (QA
    // robot 8a93e05c, 9 Nov 2026: Tab reached Account, Chats and Search behind
    // it); the tab bar, outside the shell's content, stays in reach.
    const page =
      document.querySelector<HTMLElement>("[data-shell-content]") ??
      document.getElementById("main-content");
    const before =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    page?.setAttribute("inert", "");
    back.current?.focus({ preventScroll: true });
    return () => {
      page?.removeAttribute("inert");
      const kept = before?.isConnected && before !== document.body;
      if (kept) before.focus({ preventScroll: true });
      const row = lightRow(kept ? before : null, lastKey.current);
      // Nothing had focus: it goes back to the lead's row.
      if (!kept && row && row.tabIndex >= 0) row.focus({ preventScroll: true });
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
