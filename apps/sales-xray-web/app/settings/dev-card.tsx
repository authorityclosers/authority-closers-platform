"use client";

/**
 * Developers' own section card (owner bugs #103-#105, 29 Oct 2026: "the
 * developers section is very niche and needs to have its own personality",
 * "information could be under tooltip"). A tinted icon tile names the
 * section at a glance, the title stays short, and the explanation waits
 * behind an (i) that opens a small bubble under the head. `InfoFold` does the
 * same for one line inside a section ("How to add it in ChatGPT").
 */
import { ChevronDown, Info } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import styles from "./dev-card.module.css";

/** A section's colour: its icon tile and the bubble's edge. */
export type DevTone = "violet" | "amber" | "blue" | "teal" | "slate";

export function DevCard({
  icon,
  tone,
  title,
  info,
  tools,
  children,
  className,
}: {
  icon: ReactNode;
  tone: DevTone;
  title: string;
  /** What the section is for and how to use it; behind the (i). */
  info?: ReactNode;
  /** The section's one or two actions, at the end of the head. */
  tools?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const tipId = useId();
  return (
    <section
      className={className ? `${styles.card} ${className}` : styles.card}
      data-tone={tone}
      aria-labelledby={titleId}
    >
      <div className={styles.head}>
        <span className={styles.tile} aria-hidden="true">
          {icon}
        </span>
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {info ? (
          <button
            type="button"
            className={styles.infoButton}
            aria-expanded={open}
            aria-controls={tipId}
            aria-label={`About ${title}`}
            onClick={() => setOpen((value) => !value)}
          >
            <Info size={17} aria-hidden="true" />
          </button>
        ) : null}
        {tools ? <span className={styles.tools}>{tools}</span> : null}
      </div>
      {info ? (
        <div id={tipId} className={styles.tip} role="note" hidden={!open}>
          {info}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** A whole section folded to its head until wanted (Try the API). */
export function DevFold({
  icon,
  tone,
  title,
  note,
  open = false,
  children,
}: {
  icon: ReactNode;
  tone: DevTone;
  title: string;
  note: string;
  open?: boolean;
  children: ReactNode;
}) {
  return (
    <details
      className={`${styles.card} ${styles.foldCard}`}
      data-tone={tone}
      open={open}
    >
      <summary className={styles.head}>
        <span className={styles.tile} aria-hidden="true">
          {icon}
        </span>
        <span className={styles.summaryText}>
          <strong className={styles.title}>{title}</strong>
          <small>{note}</small>
        </span>
        <ChevronDown size={18} aria-hidden="true" className={styles.chev} />
      </summary>
      <div className={styles.foldBody}>{children}</div>
    </details>
  );
}

/** One line of help, folded: a quiet (i) row that opens its words in place. */
export function InfoFold({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className={styles.fold}>
      <button
        type="button"
        className={styles.foldButton}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        <Info size={15} aria-hidden="true" />
        <span>{label}</span>
        <ChevronDown size={15} aria-hidden="true" className={styles.chev} />
      </button>
      <div id={id} className={styles.foldTip} hidden={!open}>
        {children}
      </div>
    </div>
  );
}
