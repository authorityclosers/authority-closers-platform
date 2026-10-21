"use client";

/**
 * How lead stages work, in three plain steps (owner, 22 Oct 2026: how a
 * business owner defines lead stages, and how stages pair with Meta, "is
 * confusing. Make it plain"). Open until read once; then one line that
 * opens again.
 */

import { HelpCircle } from "lucide-react";
import { useState } from "react";

import { KIND_WORDS } from "../stage-tabs";
import styles from "../leads.module.css";

const SEEN_KEY = "sx-leads-stages-explained";

export function StagesExplainer() {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(SEEN_KEY) !== "seen";
    } catch {
      return true;
    }
  });
  return (
    <details
      className={styles.explainer}
      open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        setOpen(next);
        if (!next)
          try {
            localStorage.setItem(SEEN_KEY, "seen");
          } catch {
            // Storage blocked: it opens again next visit.
          }
      }}
    >
      <summary>
        <HelpCircle size={16} aria-hidden="true" />
        How lead stages work
      </summary>
      <ol className={styles.explainerSteps}>
        <li>
          <strong>Pick your kind of business.</strong> It gives you stages that
          fit how you sell, from first enquiry to sale. Change it any time with
          Change above; your leads stay where they are.
        </li>
        <li>
          <strong>Make them yours.</strong> Rename, add or move stages so they
          say what your team says, like &ldquo;Site visit booked&rdquo;. Each
          stage is one of six kinds ({Object.values(KIND_WORDS).join(", ")}),
          which puts it under the right tab on Leads and tells the desk who to
          call next.
        </li>
        <li>
          <strong>Your ads learn from them (optional).</strong> Connect
          Facebook, Instagram or Google under Ad platforms and confirm which
          stages they hear about. When a lead reaches one, the ad platform finds
          more people like that lead. Names, notes and calls never leave Sales
          Xray.
        </li>
      </ol>
    </details>
  );
}
