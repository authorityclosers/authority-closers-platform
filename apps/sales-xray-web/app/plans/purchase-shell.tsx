"use client";

import { ArrowLeft, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import styles from "./plans.module.css";

export type PurchaseShellProps = {
  children: ReactNode;
  onClose?: () => void;
  backHref?: string;
};

/**
 * Dedicated purchase shell for /plans.
 * Stripped of app chrome: no app sidebar, no navigation header, no account menu.
 * Just a clean back/close control, minimal brand lockup, and billing receipt link.
 */
export function PurchaseShell({
  children,
  onClose,
  backHref = "/",
}: PurchaseShellProps) {
  const router = useRouter();

  const handleClose = () => {
    if (onClose) {
      onClose();
    } else {
      router.push(backHref);
    }
  };

  return (
    <div className={styles.purchaseShell} data-purchase-shell>
      <header className={styles.shellHeader}>
        <div className={styles.shellHeaderLeft}>
          <button
            type="button"
            className={styles.shellBackBtn}
            onClick={handleClose}
            aria-label="Back to Sales Xray"
          >
            <ArrowLeft size={16} aria-hidden="true" />
            <span>Back</span>
          </button>
        </div>
        <div className={styles.shellBrand}>
          <Sparkles
            size={16}
            className={styles.shellSparkle}
            aria-hidden="true"
          />
          <span className={styles.shellBrandName}>Sales Xray</span>
        </div>
        <div className={styles.shellHeaderRight}>
          <Link className={styles.shellReceiptLink} href="/account#billing">
            Billing &amp; receipts
          </Link>
          <button
            type="button"
            className={styles.shellCloseBtn}
            onClick={handleClose}
            aria-label="Close"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>
      </header>
      <main className={styles.shellBody}>{children}</main>
    </div>
  );
}
