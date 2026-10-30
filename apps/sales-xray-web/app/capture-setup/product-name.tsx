import type { ReactNode } from "react";

import styles from "./capture-setup.module.css";

const NAME = "Sales X-Ray";

/** The product's name never splits at its hyphen (orchestrator, 29 Oct 2026). */
export function named(text: string): ReactNode {
  if (!text.includes(NAME)) return text;
  return text.split(NAME).flatMap((part, index) =>
    index === 0
      ? [part]
      : [
          <span key={index} className={styles.name}>
            {NAME}
          </span>,
          part,
        ],
  );
}
