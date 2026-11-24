"use client";

import { ShieldCheck } from "lucide-react";
import Link from "next/link";

import styles from "./new-analysis-hero.module.css";
import { useProfileFirstName } from "./profile-first-name";

/** The welcome header above the upload card on New analysis, and the
 *  first-call guide's place in the page (guide-overlay.tsx; v1.96 device
 *  polish): under the header on a phone, a right column on a wide screen, so
 *  the guide never floats over the steps or Recent calls. Empty, it takes no
 *  room. */
export function NewAnalysisHero() {
  const name = useProfileFirstName();
  return (
    <>
      <NewAnalysisHeader name={name} />
      <div className={styles.guideSlot} data-guide-slot="" />
    </>
  );
}

function NewAnalysisHeader({ name }: { name: string | null }) {
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
  moreMinutesHref,
}: {
  allowanceLabel: string | null;
  /** Set when a signed-in seller is out of minutes: where to get more. */
  moreMinutesHref?: string;
}) {
  return (
    <div className={styles.footer}>
      {allowanceLabel && (
        <span className={styles.allowance}>
          <ShieldCheck size={15} aria-hidden="true" />
          {allowanceLabel}
          {moreMinutesHref ? (
            <Link className={styles.moreMinutes} href={moreMinutesHref}>
              Get more minutes
            </Link>
          ) : null}
        </span>
      )}
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
