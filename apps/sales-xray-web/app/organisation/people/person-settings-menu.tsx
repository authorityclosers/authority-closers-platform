"use client";

import { MoreHorizontal } from "lucide-react";
import type { ReactNode } from "react";
import { Sheet } from "../../ui/sheet";
import styles from "./person.module.css";

/** Reusable person settings entry point; pickers and confirmations are steps in one sheet. */
export function PersonSettingsMenu({
  name,
  open,
  onOpen,
  onClose,
  title = "Person settings",
  children,
  footer,
}: {
  name: string;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  title?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <>
      <button
        type="button"
        className={styles.iconButton}
        aria-label={`Settings for ${name}`}
        aria-haspopup="dialog"
        onClick={onOpen}
      >
        <MoreHorizontal size={21} aria-hidden />
      </button>
      <Sheet open={open} onClose={onClose} title={title} footer={footer}>
        {children}
      </Sheet>
    </>
  );
}
