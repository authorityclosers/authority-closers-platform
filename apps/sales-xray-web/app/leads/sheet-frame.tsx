"use client";

/**
 * Every Leads sheet is the kit Sheet (design system v2): phones swipe it away
 * from the top, computers get the floating panel on the right. The label names
 * the dialog; the content brings its own heading. A module of its own, so a
 * card that opens a sheet doesn't load the whole lead sheet with it (route
 * splitting, 23 Oct 2026).
 */

import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Sheet as KitSheet } from "../ui/sheet";
import styles from "./leads.module.css";

export function Sheet({
  open,
  label,
  onClose,
  children,
  footer,
  className,
}: {
  open: boolean;
  label: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  /** The frame's own room, beside the sheet look (the lead sheet's, ph2-35). */
  className?: string;
}) {
  return (
    <KitSheet
      open={open}
      onClose={onClose}
      title={label}
      hideTitle
      closeButton={false}
      className={className ? `${styles.sheet} ${className}` : styles.sheet}
      footer={footer}
    >
      <div className={styles.sheetBody}>
        <button
          type="button"
          className={styles.sheetClose}
          onClick={onClose}
          aria-label="Close"
        >
          <X size={18} aria-hidden="true" />
        </button>
        {children}
      </div>
    </KitSheet>
  );
}
