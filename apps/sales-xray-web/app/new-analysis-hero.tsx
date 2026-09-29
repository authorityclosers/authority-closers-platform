"use client";

import { ShieldCheck } from "lucide-react";

import styles from "./new-analysis-hero.module.css";
import { useProfileFirstName } from "./profile-first-name";

/** The welcome header above the upload card on New analysis. */
export function NewAnalysisHero() {
  const name = useProfileFirstName();
  return (
    <header className={styles.hero}>
      <h2 className={styles.title}>
        <span className={styles.line}>
          Let&apos;s analyse your next call
          {name ? (
            <>
              , <span className={styles.name}>{name}</span>
            </>
          ) : null}
        </span>
        <span className={styles.mark} aria-hidden="true">
          🎧
        </span>
      </h2>
      <p className={styles.subtitle}>
        Bring your conversation. Leave with a clearer next step.
      </p>
    </header>
  );
}

const STEPS = ["Upload", "We analyse", "Your report"] as const;

/** A quiet line under the upload card: the allowance and how it works. */
export function NewAnalysisFooter({
  allowanceLabel,
}: {
  allowanceLabel: string;
}) {
  return (
    <div className={styles.footer}>
      <span className={styles.allowance}>
        <ShieldCheck size={15} aria-hidden="true" />
        {allowanceLabel}
      </span>
      <ol className={styles.trail} aria-label="How it works">
        {STEPS.map((step, index) => (
          <li key={step}>
            <span className={styles.number} aria-hidden="true">
              {index + 1}
            </span>
            {step}
          </li>
        ))}
      </ol>
    </div>
  );
}
