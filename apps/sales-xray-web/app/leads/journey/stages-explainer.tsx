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
          <strong>Your steps, your words.</strong> Stages are the steps a lead
          goes through, from first enquiry to sale. Name them the way your team
          talks, like &ldquo;Site visit booked&rdquo;.
        </li>
        <li>
          <strong>Each stage has a kind.</strong> There are six:{" "}
          {Object.values(KIND_WORDS).join(", ")}. The kind puts the stage under
          the right tab on Leads and tells the desk who to call next.
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
