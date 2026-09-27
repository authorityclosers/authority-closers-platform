"use client";

import { useRef, type KeyboardEvent } from "react";

import styles from "./help-menu.module.css";

/** The former "Need help?" card and footer links, behind one compact control. */
export function HelpMenu() {
  const details = useRef<HTMLDetailsElement>(null);
  function closeOnEscape(event: KeyboardEvent<HTMLDetailsElement>) {
    if (event.key !== "Escape" || !details.current?.open) return;
    event.preventDefault();
    details.current.open = false;
    details.current.querySelector("summary")?.focus();
  }
  return (
    <details
      ref={details}
      className={styles.help}
      data-help-menu
      onKeyDown={closeOnEscape}
    >
      <summary className={styles.trigger} aria-label="Help">
        <span aria-hidden="true">?</span>
      </summary>
      <div className={styles.popover}>
        <p className={styles.title}>Help</p>
        <ul className={styles.tips}>
          <li>Choose a supported audio file up to 32 MB.</li>
          <li>Review the language and privacy details before analysis.</li>
          <li>Open saved calls to revisit completed reports.</li>
        </ul>
        <nav className={styles.links} aria-label="Legal and support">
          <a href="https://app.authorityclosers.com/privacy">Privacy</a>
          <a href="https://app.authorityclosers.com/terms">Terms</a>
          <a href="mailto:admin@authorityclosers.com?subject=Sales%20Xray%20help">
            Email the AC team
          </a>
        </nav>
      </div>
    </details>
  );
}
