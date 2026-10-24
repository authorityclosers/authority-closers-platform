"use client";

import { useState } from "react";

import styles from "./loop.module.css";

/**
 * Copies a finding as a task card's text (title, evidence, screen, suggested owner and its
 * key) for the bug board or AC Pulse. Where the browser refuses the clipboard, the text is
 * selected in place to copy by hand.
 */
export function CopyTask({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "manual">("idle");
  if (!text) return null;
  return (
    <span className={styles.copy}>
      <button
        type="button"
        className={styles.copyButton}
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setState("copied");
          } catch {
            setState("manual");
          }
        }}
      >
        {state === "copied" ? "Copied" : "Copy task"}
      </button>
      {state === "manual" ? (
        <textarea
          className={styles.copyText}
          readOnly
          value={text}
          aria-label="Task text"
          ref={(node) => node?.select()}
        />
      ) : null}
      <span className={styles.srOnly} role="status">
        {state === "copied" ? "Task text copied" : ""}
      </span>
    </span>
  );
}
