"use client";

import {
  ArrowRight,
  AudioLines,
  Check,
  ChevronLeft,
  Quote,
  Target,
  X,
} from "lucide-react";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";

import type { GuideStep } from "./guide-registry";
import styles from "./guide.module.css";

export type CoachTarget = {
  left: number;
  top: number;
  width: number;
  height: number;
};

export function GuideOverlay({
  step,
  label,
  index,
  count,
  target,
  onNext,
  onBack,
  onSkip,
  onClose,
}: {
  step: GuideStep;
  label: string;
  index: number;
  count: number;
  target: CoachTarget | null;
  onNext: () => void;
  onBack: () => void;
  onSkip: () => void;
  /** Closes for good; the account menu turns it back on. */
  onClose: () => void;
}) {
  const heading = useId();
  const card = useRef<HTMLElement>(null);
  const skipRef = useRef(onSkip);
  // Auto-open never moves focus. Explicit dismissal releases focus only when
  // the removed card owns it, without disturbing someone using the page.
  const leave = useCallback((action: () => void) => {
    const focused = document.activeElement;
    if (focused instanceof HTMLElement && card.current?.contains(focused))
      focused.blur();
    action();
  }, []);
  useEffect(() => {
    skipRef.current = onSkip;
  }, [onSkip]);
  useEffect(() => {
    const dismiss = (event: KeyboardEvent) => {
      // Let an existing modal or popup own its Escape key first.
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        document.querySelector("dialog[open], [role='menu']")
      )
        return;
      leave(() => skipRef.current());
    };
    window.addEventListener("keydown", dismiss);
    return () => window.removeEventListener("keydown", dismiss);
  }, [leave]);
  const Icon =
    step.visual === "evidence"
      ? Quote
      : step.visual === "practice"
        ? Target
        : AudioLines;
  const above = target && target.top > window.innerHeight / 2;
  return createPortal(
    <>
      {target ? (
        <div
          className={styles.coach}
          aria-hidden="true"
          data-guide-coach
          style={{
            left: target.left,
            top: target.top,
            width: target.width,
            height: target.height,
          }}
        >
          <span>Click here</span>
        </div>
      ) : null}
      <aside
        ref={card}
        tabIndex={-1}
        className={styles.card}
        data-guide-card
        data-waiting={step.waitForPage || undefined}
        data-position={above ? "top" : "bottom"}
        aria-labelledby={heading}
      >
        <header className={styles.header}>
          <span>
            {label} · {index + 1} / {count}
          </span>
          <button
            type="button"
            onClick={() => leave(onClose)}
            aria-label="Close guide"
            title="Close guide. Turn it back on from the account menu."
          >
            <X size={16} />
          </button>
        </header>
        <div
          key={step.id}
          className={styles.content}
          data-guide-step={step.id}
          aria-live="polite"
        >
          <div className={styles.visual} aria-hidden="true">
            <span className={styles.icon}>
              <Icon size={30} strokeWidth={1.6} />
            </span>
            <div className={styles.wave}>
              {[18, 32, 23, 42, 28, 36, 16].map((height, i) => (
                <i key={i} style={{ height, "--bar": i } as CSSProperties} />
              ))}
            </div>
            <span className={styles.visualNote}>
              {step.visual === "welcome"
                ? "One conversation. One next step."
                : step.visual === "listen"
                  ? "Listen with context"
                  : step.visual === "evidence"
                    ? "Keep the source in view"
                    : "Put one insight into practice"}
            </span>
          </div>
          <h2 id={heading}>{step.title}</h2>
          <p>{step.body}</p>
          {!target && step.href ? (
            <Link className={styles.link} href={step.href}>
              {step.actionLabel}
              <ArrowRight size={15} aria-hidden="true" />
            </Link>
          ) : null}
          {step.waitForPage ? (
            <p className={styles.waiting}>
              Continue with the page. The guide follows along.
            </p>
          ) : null}
        </div>
        <footer className={styles.footer}>
          <button
            type="button"
            className={styles.skip}
            onClick={() => leave(onSkip)}
          >
            Skip guide
          </button>
          <div>
            {index > 0 ? (
              <button
                type="button"
                className={styles.back}
                aria-label="Previous guide step"
                onClick={() => {
                  card.current?.focus({ preventScroll: true });
                  onBack();
                }}
              >
                <ChevronLeft size={17} />
              </button>
            ) : null}
            {!step.waitForPage ? (
              <button
                type="button"
                className={styles.next}
                onClick={() => {
                  if (index === count - 1) leave(onNext);
                  else {
                    card.current?.focus({ preventScroll: true });
                    onNext();
                  }
                }}
              >
                {index === count - 1 ? "Finish" : "Next"}
                {index === count - 1 ? (
                  <Check size={16} />
                ) : (
                  <ArrowRight size={16} />
                )}
              </button>
            ) : null}
          </div>
        </footer>
      </aside>
    </>,
    document.body,
  );
}
