import { RotateCcw } from "lucide-react";

import styles from "./result-seal.module.css";

/**
 * The moment a purchase lands: a teal seal whose tick draws itself once, with
 * one soft ring (owner, 23 Oct 2026: "nice looks and finished"). A refund gets
 * a quiet seal instead. Still when the person prefers reduced motion.
 */
export function ResultSeal({ tone = "good" }: { tone?: "good" | "refund" }) {
  return (
    <span className={styles.seal} data-tone={tone} aria-hidden="true">
      {tone === "good" ? (
        <svg viewBox="0 0 40 40" className={styles.svg}>
          <path className={styles.tick} d="M11.5 20.5 18 27 29 14" />
        </svg>
      ) : (
        <RotateCcw size={28} strokeWidth={2.2} />
      )}
    </span>
  );
}
