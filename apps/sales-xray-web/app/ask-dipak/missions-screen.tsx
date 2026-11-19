"use client";

/**
 * My Next-call missions (redesign study §5 S5, N-B; 13 Nov 2026 meeting,
 * section 5). One focal point: the calls that wait for the seller's answer
 * come first, as mint check-in cards ("… वाली call में try किया?"), one per
 * call from a lead, from the real coaching API (coaching-client.ts). Then the
 * active missions (up to three) with how many calls each was tried on, the
 * ticked ones to make active, and the calls already answered. A check-in is
 * the seller's own word, "tried" never "worked"; nothing here scores it and
 * "no chance" carries no penalty, so its count is not shown.
 */

import {
  useCallback,
  useEffect,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import styles from "./ask-dipak.module.css";
import {
  answerCall,
  CoachingError,
  readCalls,
  readGrowth,
  setActive,
  type Calls,
  type Growth,
  type Mission,
} from "./coaching-client";
import { COPY } from "./copy";
import { AskIcon } from "./icons";
import { lessonChip, questionById } from "./library";
import { viewHref, type AskView } from "./nav";
import { toneOfCategory } from "./tones";

const WORDS = {
  title: "My Next-call missions",
  sub: "Keep up to 3 active. After each call, say whether you did them.",
  waiting: "Waiting for your answer",
  active: "Active",
  ticked: "Ticked, not active",
  answered: "Answered",
  makeActive: "Make active",
  drop: "Drop",
  // The check-in's two answers (study §5 S4.7); the server keeps yes or no.
  did: COPY.checkinYes,
  didnt: COPY.checkinNo,
  // The empty state (study §5 S5, chat 2).
  none: "One idea can change your next call.",
  noneHint: "Find a useful question, then keep its next-call mission here.",
  explore: "Explore situations",
  noCalls: "Your calls from leads show here, to answer after each one.",
  noActive: "Make a mission active to be asked about it after calls.",
  full: "3 are active. Drop one to add another.",
  failed: "Couldn’t open your missions",
  retry: "Try again",
};

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

/** The lesson's topic, in its colour by meaning; none for an unknown code. */
function TopicChip({ code }: { code: string }) {
  const question = questionById(code);
  if (!question) return null;
  return (
    <span
      className={`${styles.chip} ${styles[toneOfCategory(question.categoryId)]}`}
    >
      {lessonChip(question)}
    </span>
  );
}

function MissionCard({
  mission,
  action,
  disabled,
  onAction,
}: {
  mission: Mission;
  action: string;
  disabled?: boolean;
  onAction: () => void;
}) {
  return (
    <article className={styles.mineCard} data-mission={mission.question_id}>
      <TopicChip code={mission.question_id} />
      <p className={styles.mineCardLine}>{mission.mission ?? mission.title}</p>
      <p className={styles.mineCardMeta}>
        {/* The lesson's title under its mission; never twice when the
            server has no mission words and the title is the line above. */}
        {mission.mission ? <span>{mission.title}</span> : null}
        {mission.done_calls ? (
          <span className={styles.figure}>
            {COPY.triedOn(mission.done_calls)}
          </span>
        ) : null}
      </p>
      <button
        type="button"
        className={styles.smallBtn}
        disabled={disabled}
        onClick={onAction}
      >
        {action}
      </button>
    </article>
  );
}

function TickedRow({
  mission,
  disabled,
  onAction,
}: {
  mission: Mission;
  disabled?: boolean;
  onAction: () => void;
}) {
  return (
    <div className={styles.mineRow} data-mission={mission.question_id}>
      <span className={styles.mineRowTitle}>{mission.title}</span>
      <button
        type="button"
        className={styles.smallBtn}
        disabled={disabled}
        onClick={onAction}
      >
        {WORDS.makeActive}
      </button>
    </div>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.mineSection} aria-labelledby={id}>
      <h3 id={id} className={styles.sectionH}>
        {title}
      </h3>
      {children}
    </section>
  );
}

export function MissionsScreen({ open }: { open?: (view: AskView) => void }) {
  const [growth, setGrowth] = useState<Growth | null>(null);
  const [recent, setRecent] = useState<Calls | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Each round reads both again: the first visit, Try again, and after a change.
  const [round, setRound] = useState(0);
  const reload = useCallback(() => setRound((value) => value + 1), []);

  useEffect(() => {
    let live = true;
    Promise.all([readGrowth(), readCalls()]).then(
      ([mine, latest]) => {
        if (!live) return;
        setGrowth(mine);
        setRecent(latest);
        setProblem(null);
      },
      (error: unknown) => {
        if (live)
          setProblem(
            error instanceof CoachingError ? error.message : WORDS.failed,
          );
      },
    );
    return () => {
      live = false;
    };
  }, [round]);

  const run = async (change: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await change();
    } catch (error) {
      setProblem(error instanceof CoachingError ? error.message : WORDS.failed);
    } finally {
      setBusy(false);
      reload();
    }
  };

  const title = <h2 className={styles.pageTitle}>{WORDS.title}</h2>;
  if (problem && !growth)
    return (
      <>
        {title}
        <div className={styles.empty}>
          <strong>{WORDS.failed}</strong>
          {problem}
          <button type="button" className={styles.smallBtn} onClick={reload}>
            {WORDS.retry}
          </button>
        </div>
      </>
    );
  if (!growth || !recent)
    return (
      <>
        {title}
        <div className={styles.mineSkeleton} aria-busy="true">
          <span />
          <span />
        </div>
      </>
    );

  const active = growth.missions.filter((mission) => mission.active);
  const ticked = growth.missions.filter(
    (mission) => mission.ticked && !mission.active,
  );
  const full = active.length >= growth.max_active;
  const titleOf = (code: string) =>
    growth.missions.find((mission) => mission.question_id === code)?.title ??
    code;
  const waiting = recent.calls.filter((call) => call.waiting.length > 0);
  const answered = recent.calls.filter(
    (call) => !call.waiting.length && call.answered.length > 0,
  );
  const explore: AskView = { kind: "topics" };
  const follow = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!open || event.button !== 0 || event.metaKey || event.ctrlKey) return;
    event.preventDefault();
    open(explore);
  };

  if (!active.length && !ticked.length)
    return (
      <>
        {title}
        <p className={styles.pageSub}>{WORDS.sub}</p>
        <div className={styles.empty} data-missions-empty="">
          <span className={styles.mineEmptyMark} aria-hidden="true">
            <AskIcon name="flag" size={22} />
          </span>
          <strong>{WORDS.none}</strong>
          {WORDS.noneHint}
          <a
            className={`${styles.smallBtn} ${styles.primary} ${styles.mineEmptyGo}`}
            href={viewHref(explore)}
            onClick={follow}
          >
            {WORDS.explore}
          </a>
        </div>
      </>
    );

  return (
    <>
      {title}
      <p className={styles.pageSub}>{WORDS.sub}</p>
      {problem ? (
        <p className={styles.mutedNote} role="alert">
          {problem}
        </p>
      ) : null}
      {waiting.length ? (
        <Section id="ad-missions-waiting" title={WORDS.waiting}>
          {waiting.map((call) => (
            <article
              className={styles.mineCheck}
              key={call.call_id}
              data-call={call.call_id}
            >
              <p className={styles.checkinAsk}>
                {COPY.checkinAsk(call.lead_name, when(call.called_at))}
              </p>
              {call.waiting.map((code) => (
                <div key={code} className={styles.checkRow}>
                  <span className={styles.mineCheckTitle}>{titleOf(code)}</span>
                  <span className={styles.checkButtons}>
                    <button
                      type="button"
                      className={`${styles.smallBtn} ${styles.primary}`}
                      disabled={busy}
                      onClick={() =>
                        void run(() => answerCall(call.call_id, code, true))
                      }
                    >
                      {WORDS.did}
                    </button>
                    <button
                      type="button"
                      className={styles.smallBtn}
                      disabled={busy}
                      onClick={() =>
                        void run(() => answerCall(call.call_id, code, false))
                      }
                    >
                      {WORDS.didnt}
                    </button>
                  </span>
                </div>
              ))}
              <p className={styles.checkinNote}>{COPY.checkinNote}</p>
            </article>
          ))}
        </Section>
      ) : null}
      <Section
        id="ad-missions-active"
        title={
          <>
            {WORDS.active}{" "}
            <span className={styles.figure}>
              ({active.length}/{growth.max_active})
            </span>
          </>
        }
      >
        {active.length ? (
          active.map((mission) => (
            <MissionCard
              key={mission.question_id}
              mission={mission}
              action={WORDS.drop}
              disabled={busy}
              onAction={() =>
                void run(() => setActive(mission.question_id, false))
              }
            />
          ))
        ) : (
          <p className={styles.mutedNote}>{WORDS.noActive}</p>
        )}
        {active.length && !recent.calls.length ? (
          <p className={styles.mutedNote}>{WORDS.noCalls}</p>
        ) : null}
      </Section>
      {ticked.length ? (
        <Section id="ad-missions-ticked" title={WORDS.ticked}>
          {full ? <p className={styles.mutedNote}>{WORDS.full}</p> : null}
          {ticked.map((mission) => (
            <TickedRow
              key={mission.question_id}
              mission={mission}
              disabled={busy || full}
              onAction={() =>
                void run(() => setActive(mission.question_id, true))
              }
            />
          ))}
        </Section>
      ) : null}
      {answered.length ? (
        <Section id="ad-missions-answered" title={WORDS.answered}>
          {answered.map((call) => (
            <div
              className={styles.mineDone}
              key={call.call_id}
              data-call={call.call_id}
            >
              <span className={styles.mineDoneLead}>
                {call.lead_name}
                <span className={styles.figure}> · {when(call.called_at)}</span>
              </span>
              <span className={styles.mineDoneWhat}>
                {WORDS.answered}:{" "}
                {call.answered.map((code) => titleOf(code)).join(", ")}
              </span>
            </div>
          ))}
        </Section>
      ) : null}
    </>
  );
}

export const MISSION_WORDS = WORDS;
