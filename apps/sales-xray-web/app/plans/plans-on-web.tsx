"use client";

import Link from "next/link";

import { PLANS_ON_WEB } from "../purchase-policy";
import { PurchaseShell } from "./purchase-shell";
import styles from "./plans.module.css";

/** What the Google Play app shows instead of plans or prices: no buying in the app. */
export function PlansOnWeb() {
  return (
    <PurchaseShell backHref="/">
      <div className={styles.page}>
        <section className={styles.panel} role="status">
          <h2>Your plan</h2>
          <p className={styles.hint}>{PLANS_ON_WEB}</p>
          <div className={styles.actions}>
            <Link className={styles.primary} href="/settings/plan">
              See your minutes
            </Link>
          </div>
        </section>
      </div>
    </PurchaseShell>
  );
}
