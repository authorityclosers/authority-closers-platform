"use client";

import { ChevronRight, RotateCcw } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useSyncExternalStore,
  type MouseEvent,
} from "react";

import { Skeleton } from "../../ui/kit";
import type { Guide, GuideQuestion } from "./guide-content";
import styles from "./guide.module.css";

export const GUIDE = {
  title: "Dipak’s answers",
  back: "Coaching",
  welcome: "Tap a question to see Dipak’s answer.",
  starters: "People usually ask",
  followUps: "People also ask",
  trySaying: "Try saying",
  restart: "First questions",
  waiting: "Dipak’s answers are on their way",
  waitingText:
    "Dipak is writing the questions sellers ask most. They show here once they are in.",
  openCoaching: "Open Coaching",
} as const;

/** The step is the address (?q=<id>), so Back and the Android back gesture walk the journey. */
const STEP = "q";
const STEP_EVENT = "sx-guide-step";

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  window.addEventListener(STEP_EVENT, notify);
  return () => {
    window.removeEventListener("popstate", notify);
    window.removeEventListener(STEP_EVENT, notify);
  };
}

const currentStep = () => new URLSearchParams(window.location.search).get(STEP);
const serverStep = () => null;

export function stepHref(id: string | null): string {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set(STEP, id);
  else url.searchParams.delete(STEP);
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Each tap adds one history entry. A null state lets Next copy its own into
 * the entry and keep its router on the new address; one press of Back pops
 * one step.
 */
export function useGuideStep(): [string | null, (id: string | null) => void] {
  const step = useSyncExternalStore(subscribe, currentStep, serverStep);
  const go = useCallback((id: string | null) => {
    window.history.pushState(null, "", stepHref(id));
    window.dispatchEvent(new Event(STEP_EVENT));
  }, []);
  return [step, go];
}

/** "objection handling" reads as "Objection handling". */
const sentence = (value: string) =>
  value ? value.charAt(0).toUpperCase() + value.slice(1) : value;

/** Blank lines part paragraphs; single line breaks stay as Dipak wrote them. */
const paragraphs = (answer: string) =>
  answer
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean);

function QuestionList({
  label,
  ids,
  guide,
  onPick,
}: {
  label: string;
  ids: string[];
  guide: Guide;
  onPick: (id: string) => void;
}) {
  const heading = useId();
  const items = ids
    .map((id) => guide.questions.get(id))
    .filter((item): item is GuideQuestion => Boolean(item));
  if (!items.length) return null;
  return (
    <section className={styles.section} aria-labelledby={heading}>
      <h2 id={heading} className={styles.label}>
        {label}
      </h2>
      <ul className={styles.list}>
        {items.map((item) => (
          <li key={item.id}>
            <a
              href={`?${STEP}=${encodeURIComponent(item.id)}`}
              onClick={(event: MouseEvent<HTMLAnchorElement>) => {
                // A new tab or window opens the address as it is.
                if (
                  event.button !== 0 ||
                  event.metaKey ||
                  event.ctrlKey ||
                  event.shiftKey ||
                  event.altKey
                )
                  return;
                event.preventDefault();
                onPick(item.id);
              }}
            >
              <span>{item.question}</span>
              <ChevronRight size={18} aria-hidden="true" />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The journey: a welcome and the starters ("People usually ask"); a tap shows
 * that answer and its follow-ups ("People also ask"), and so on. A step the
 * content no longer has opens the starters.
 */
export function GuideView({ guide }: { guide: Guide }) {
  const [step, go] = useGuideStep();
  const current = step ? (guide.questions.get(step) ?? null) : null;
  const title = useRef<HTMLHeadingElement>(null);
  const top = useRef<HTMLDivElement>(null);

  // A new step starts at its question, read out by screen readers.
  // Only a change of step moves focus: not the first paint, nor Strict
  // Mode's second run of the same effect.
  const shownId = current?.id ?? null;
  const before = useRef(shownId);
  useEffect(() => {
    if (before.current === shownId) return;
    before.current = shownId;
    const target = title.current ?? top.current;
    target?.scrollIntoView?.({ block: "start" });
    target?.focus({ preventScroll: true });
  }, [shownId]);

  if (!current)
    return (
      <div className={styles.guide} ref={top} tabIndex={-1}>
        <div className={styles.welcome}>
          <span className={styles.face} aria-hidden="true" />
          <p>{guide.welcome || GUIDE.welcome}</p>
        </div>
        <QuestionList
          label={GUIDE.starters}
          ids={guide.starters}
          guide={guide}
          onPick={go}
        />
      </div>
    );

  const said = paragraphs(current.answer);
  return (
    <div className={styles.guide}>
      <article
        className={styles.answer}
        aria-labelledby={`guide-${current.id}`}
      >
        {current.category ? (
          <p className={styles.eyebrow}>{sentence(current.category)}</p>
        ) : null}
        <h2
          id={`guide-${current.id}`}
          ref={title}
          tabIndex={-1}
          className={styles.question}
        >
          {current.question}
        </h2>
        <div className={styles.text}>
          {said.map((part, index) => (
            <p key={index}>{part}</p>
          ))}
        </div>
        {current.example_line ? (
          <figure className={styles.say}>
            <figcaption>{GUIDE.trySaying}</figcaption>
            <blockquote>
              <p>{current.example_line}</p>
            </blockquote>
          </figure>
        ) : null}
      </article>
      <QuestionList
        label={GUIDE.followUps}
        ids={current.next}
        guide={guide}
        onPick={go}
      />
      <button type="button" className={styles.restart} onClick={() => go(null)}>
        <RotateCcw size={16} aria-hidden="true" />
        {GUIDE.restart}
      </button>
    </div>
  );
}

/** The loading outline, at the starters' sizes. */
export function GuideSkeleton() {
  return (
    <div className={styles.guide} aria-busy="true">
      <div className={styles.welcome}>
        <span className={styles.face} aria-hidden="true" />
        <Skeleton height={18} width="60%" />
      </div>
      <div className={styles.section}>
        <Skeleton height={14} width={120} />
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} height={56} radius={12} />
        ))}
      </div>
    </div>
  );
}
