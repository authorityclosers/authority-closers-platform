"use client";

import { ArrowLeftRight, ShieldOff } from "lucide-react";

import { OPEN_SWITCHER_EVENT } from "./shell/shell-store";
import styles from "./workspace-no-access.module.css";

/**
 * Shown when the selected workspace has no Sales Xray access (the server
 * answers 403). It explains why nothing loads and offers the account switch.
 */
export function WorkspaceNoAccess({ workspace }: { workspace: string | null }) {
  return (
    <section className={styles.panel} aria-labelledby="no-access-title">
      <span className={styles.icon} aria-hidden="true">
        <ShieldOff size={24} />
      </span>
      <h2 id="no-access-title">
        Sales Xray isn&apos;t on for this workspace yet
      </h2>
      <p>
        {workspace ? `${workspace}. ` : ""}
        Your calls are in your personal account. An owner can switch Sales Xray
        on for this organisation, and then its calls and numbers show here.
      </p>
      <button
        type="button"
        className={styles.switch}
        onClick={() => window.dispatchEvent(new Event(OPEN_SWITCHER_EVENT))}
      >
        <ArrowLeftRight size={15} aria-hidden="true" />
        Switch account
      </button>
    </section>
  );
}
