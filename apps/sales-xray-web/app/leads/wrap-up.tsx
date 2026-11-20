"use client";

/**
 * The wrap-up screen after a call (round-2 board 1, the owner's pick B, 20 Nov 2026):
 * a focused screen of its own instead of a card loose on the lead page, so nothing
 * floats over it and the page's own buttons don't peek above it. Step 1 is "How did
 * the call go?" (four big answers and a real "I didn't call"), step 2 "What happens
 * next?" (CallOutcome, wrapUp), then "Saved" with the report on its way and "Call next
 * lead". The 19 Nov rules stay: while a call this phone placed waits for its answer
 * there is no way out but answering, and no "I didn't call" (lead-sheet.tsx).
 *
 * A phone shows it full screen; a computer shows it as a centred card over the page.
 */
import { CheckCircle2, ChevronLeft, FileText, PhoneCall } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Avatar } from "../ui/kit";
import { when, type LeadDetail } from "./leads-client";
import styles from "./wrap-up.module.css";

export function WrapUpFrame({
  name,
  line,
  onLater,
  asking = true,
  children,
}: {
  /** Still asking (not the Saved screen). */
  asking?: boolean;
  /** The lead's name, at the top: whose call this is. */
  name: string;
  /** "Talked 4 min 12 s · just now", when the phone said. */
  line?: string | null;
  /** Back to the lead with the question on it; absent while it must be answered. */
  onLater?: () => void;
  children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  // The page behind stays still while this is up (bug 172: the page behind
  // an open sheet scrolled).
  useEffect(() => {
    const root = document.documentElement;
    const was = root.style.overflow;
    root.style.overflow = "hidden";
    box.current
      ?.querySelector<HTMLElement>("button:not([disabled])")
      ?.focus({ preventScroll: true });
    return () => {
      root.style.overflow = was;
    };
  }, []);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      className={styles.scrim}
      // While it asks, the corner's news waits (notice-center.tsx); once
      // saved, the "Moved to" card with its Undo shows.
      data-after-call={asking ? "" : undefined}
      data-wrap-up=""
    >
      <div
        ref={box}
        className={styles.screen}
        role="dialog"
        aria-modal="true"
        aria-label={`After the call with ${name}`}
      >
        <header className={styles.head}>
          {onLater ? (
            <button
              type="button"
              className={styles.later}
              aria-label={`Back to ${name}`}
              data-sx-feature="wrap_up_later"
              onClick={onLater}
            >
              <ChevronLeft size={22} aria-hidden="true" />
            </button>
          ) : null}
          <Avatar name={name} size={44} />
          <span className={styles.who}>
            <strong>{name}</strong>
            {line ? <small>{line}</small> : null}
          </span>
        </header>
        <div className={styles.body}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}

/** After Save: where the lead went, the report on its way, and Call next lead. */
export function WrapUpDone({
  saved,
  talked,
  reportExpected,
  onCallNext,
  onBack,
}: {
  saved: LeadDetail;
  talked: boolean;
  /** A call the phone records: its report follows by itself. */
  reportExpected: boolean;
  onCallNext?: () => void;
  onBack: () => void;
}) {
  const first = saved.lead.name.split(" ")[0] ?? saved.lead.name;
  return (
    <section className={styles.done} aria-labelledby="wrap-up-done">
      <CheckCircle2 className={styles.doneMark} size={40} aria-hidden="true" />
      <h3 id="wrap-up-done" className={styles.doneTitle}>
        Saved
      </h3>
      <p className={styles.doneLine}>
        {saved.lead.stage_label}
        {saved.lead.next_action_at
          ? ` · next call ${when(saved.lead.next_action_at)}`
          : ""}
      </p>
      {talked && reportExpected ? (
        <div className={styles.report} role="status">
          <FileText size={20} aria-hidden="true" />
          <span>
            <strong>Your call report is on its way</strong>
            <small>
              Once the recording reaches Sales X-Ray it takes about 2 minutes.
              It shows on {first}&apos;s page and in Reports.
            </small>
          </span>
        </div>
      ) : null}
      <div className={styles.doneActions}>
        {onCallNext ? (
          <button
            type="button"
            className={styles.primary}
            data-sx-feature="wrap_up_call_next"
            onClick={onCallNext}
          >
            <PhoneCall size={20} aria-hidden="true" />
            Call next lead
          </button>
        ) : null}
        <button
          type="button"
          className={onCallNext ? styles.secondary : styles.primary}
          data-sx-feature="wrap_up_back"
          onClick={onBack}
        >
          Back to {first}
        </button>
      </div>
    </section>
  );
}
