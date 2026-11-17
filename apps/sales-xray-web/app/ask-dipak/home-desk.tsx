"use client";

/**
 * The Coach's desk (owner's pick H-A, 17 Nov 2026; redesign study §5 S1):
 * under Dipak's card, the lesson to Continue and today's Next-call mission
 * with its after-call check-in. Everything shown is real: the last lesson
 * this person opened on this device, and their own active missions and calls
 * from the coaching API (coaching-client.ts). A check-in is the seller's own
 * word, "tried" never "worked", and nothing here scores it.
 */

import {
  useEffect,
  useState,
  useSyncExternalStore,
  type MouseEvent,
} from "react";

import styles from "./ask-dipak.module.css";
import {
  answerCall,
  readCalls,
  readGrowth,
  type Calls,
  type Growth,
} from "./coaching-client";
import { COPY } from "./copy";
import { AskIcon } from "./icons";
import {
  CATEGORIES,
  QUESTIONS,
  lessonChip,
  questionById,
  questionLabel,
} from "./library";
import { viewHref, type AskView } from "./nav";
import { lastLesson } from "./recent";
import { toneOfCategory } from "./tones";

type Open = (view: AskView) => void;

function follow(open: Open, view: AskView) {
  return (event: MouseEvent<HTMLAnchorElement>) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    open(view);
  };
}

/** The last lesson changes only on another screen, which remounts the home. */
const noChange = () => () => undefined;

/** The lesson last opened here, or, on a first visit, the whole library. */
export function ContinueCard({ open }: { open: Open }) {
  // The server's page has none, so its paint and the first agree.
  const last = useSyncExternalStore(noChange, lastLesson, () => null);
  const question = last ? questionById(last) : null;
  if (!question) {
    const view: AskView = { kind: "topics" };
    return (
      <a
        className={styles.continueCard}
        href={viewHref(view)}
        onClick={follow(open, view)}
        data-continue="first"
      >
        <span className={styles.continueTitle}>{COPY.libraryTitle}</span>
        <span className={styles.continueMeta}>
          {COPY.libraryMeta(QUESTIONS.length, CATEGORIES.length)}
        </span>
        <span className={styles.continueGo}>
          {COPY.libraryGo}
          <AskIcon name="right" size={18} />
        </span>
      </a>
    );
  }
  const view: AskView = { kind: "lesson", id: question.id };
  return (
    <a
      className={styles.continueCard}
      href={viewHref(view)}
      onClick={follow(open, view)}
      data-continue={question.id}
    >
      <span
        className={`${styles.chip} ${styles[toneOfCategory(question.categoryId)]}`}
      >
        {lessonChip(question)}
      </span>
      <span className={styles.continueTitle}>{questionLabel(question)}</span>
      <span className={styles.continueFoot}>
        <span className={styles.continueMeta}>{COPY.parts}</span>
        <span className={styles.continueGo}>
          {COPY.continue}
          <AskIcon name="right" size={18} />
        </span>
      </span>
    </a>
  );
}

function when(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? ""
    : at.toLocaleString(undefined, {
        day: "numeric",
        month: "short",
        hour: "numeric",
        minute: "2-digit",
      });
}

/**
 * Today's mission, shown only while one is active. A call that waits for the
 * seller's answer on it asks right here; otherwise "Did you try it?" opens My
 * missions.
 */
export function MissionStrip({ open }: { open: Open }) {
  const [growth, setGrowth] = useState<Growth | null>(null);
  const [calls, setCalls] = useState<Calls | null>(null);
  const [busy, setBusy] = useState(false);
  const [answered, setAnswered] = useState<"yes" | "no" | null>(null);
  const [failed, setFailed] = useState(false);
  const [round, setRound] = useState(0);

  useEffect(() => {
    let live = true;
    Promise.all([readGrowth(), readCalls()]).then(
      ([mine, latest]) => {
        if (!live) return;
        setGrowth(mine);
        setCalls(latest);
      },
      // No strip when the coaching API can't be reached: My missions says why.
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [round]);

  const mission = growth?.missions.find((item) => item.active) ?? null;
  if (!growth || !mission) return null;
  const waiting =
    calls?.calls.find((call) => call.waiting.includes(mission.question_id)) ??
    null;
  const missions: AskView = { kind: "missions" };

  const answer = async (done: boolean) => {
    if (!waiting) return;
    setBusy(true);
    setFailed(false);
    try {
      await answerCall(waiting.call_id, mission.question_id, done);
      setAnswered(done ? "yes" : "no");
      setRound((value) => value + 1);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className={styles.missionStrip}
      aria-label={COPY.missionLabel}
      data-mission-strip={mission.question_id}
    >
      <div className={styles.missionBody}>
        <p className={styles.missionLabel}>
          <span className={styles.missionFlag} aria-hidden="true">
            <AskIcon name="flag" size={18} />
          </span>
          {COPY.missionLabel}
        </p>
        <p className={styles.missionLine}>{mission.mission ?? mission.title}</p>
        {waiting && !answered ? (
          <div className={styles.checkin} data-checkin={waiting.call_id}>
            <p className={styles.checkinAsk}>
              {COPY.checkinAsk(waiting.lead_name, when(waiting.called_at))}
            </p>
            <div className={styles.checkinButtons}>
              <button
                type="button"
                className={`${styles.smallBtn} ${styles.primary}`}
                disabled={busy}
                onClick={() => void answer(true)}
              >
                {COPY.checkinYes}
              </button>
              <button
                type="button"
                className={styles.smallBtn}
                disabled={busy}
                onClick={() => void answer(false)}
              >
                {COPY.checkinNo}
              </button>
            </div>
            <p className={styles.checkinNote}>
              {failed ? COPY.checkinFailed : COPY.checkinNote}
            </p>
          </div>
        ) : (
          <>
            {answered ? (
              <p className={styles.checkinNote} role="status">
                {COPY.checkinThanks(mission.done_calls)}
              </p>
            ) : mission.done_calls ? (
              <p className={styles.checkinNote}>
                {COPY.triedOn(mission.done_calls)}
              </p>
            ) : null}
            <a
              className={styles.missionAsk}
              href={viewHref(missions)}
              onClick={follow(open, missions)}
            >
              {COPY.missionAsk}
            </a>
          </>
        )}
      </div>
    </section>
  );
}
