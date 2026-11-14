"use client";

/**
 * My Next-call missions (13 Nov 2026 meeting, section 5): the minimal screen
 * the coaching loop needs until the owner redesigns it. The seller keeps up to
 * three ticked missions active and, after each call from a lead, says whether
 * they did each one. Counts are their own answers, never a score.
 */

import { useCallback, useEffect, useState } from "react";

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

const WORDS = {
  title: "My Next-call missions",
  sub: "Keep up to 3 active. After each call, say whether you did them.",
  active: "Active",
  ticked: "Ticked, not active",
  calls: "After your calls",
  makeActive: "Make active",
  drop: "Drop",
  did: "Did it",
  didnt: "Didn’t",
  none: "No missions yet",
  noneHint: "Tick a lesson’s Next-call mission to keep it here.",
  noCalls: "Your calls from leads show here, to answer after each one.",
  noActive: "Make a mission active to be asked about it after calls.",
  full: "3 are active. Drop one to add another.",
  failed: "Couldn’t open your missions",
  retry: "Try again",
};

const calls = (count: number) => `${count} ${count === 1 ? "call" : "calls"}`;

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

function MissionRow({
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
    <div className={styles.panel} data-mission={mission.question_id}>
      <p className={styles.copy}>{mission.mission ?? mission.title}</p>
      <p className={styles.mutedNote}>
        {mission.title} · Done on {calls(mission.done_calls)}
        {mission.not_done_calls
          ? `, not on ${calls(mission.not_done_calls)}`
          : ""}
      </p>
      <button
        type="button"
        className={styles.smallBtn}
        disabled={disabled}
        onClick={onAction}
      >
        {action}
      </button>
    </div>
  );
}

export function MissionsScreen() {
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
        <div className={styles.rowSkeleton} aria-busy="true" />
      </>
    );

  const active = growth.missions.filter((mission) => mission.active);
  const ticked = growth.missions.filter(
    (mission) => mission.ticked && !mission.active,
  );
  const full = active.length >= growth.max_active;
  const titleOf = new Map(
    growth.missions.map((mission) => [mission.question_id, mission.title]),
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
      {!active.length && !ticked.length ? (
        <div className={styles.empty}>
          <strong>{WORDS.none}</strong>
          {WORDS.noneHint}
        </div>
      ) : null}
      {active.length ? (
        <>
          <h3 className={styles.sectionH}>
            {WORDS.active} ({active.length}/{growth.max_active})
          </h3>
          {active.map((mission) => (
            <MissionRow
              key={mission.question_id}
              mission={mission}
              action={WORDS.drop}
              disabled={busy}
              onAction={() =>
                void run(() => setActive(mission.question_id, false))
              }
            />
          ))}
        </>
      ) : null}
      {ticked.length ? (
        <>
          <h3 className={styles.sectionH}>{WORDS.ticked}</h3>
          {full ? <p className={styles.mutedNote}>{WORDS.full}</p> : null}
          {ticked.map((mission) => (
            <MissionRow
              key={mission.question_id}
              mission={mission}
              action={WORDS.makeActive}
              disabled={busy || full}
              onAction={() =>
                void run(() => setActive(mission.question_id, true))
              }
            />
          ))}
        </>
      ) : null}
      <h3 className={styles.sectionH}>{WORDS.calls}</h3>
      {!active.length ? (
        <p className={styles.mutedNote}>{WORDS.noActive}</p>
      ) : !recent.calls.length ? (
        <p className={styles.mutedNote}>{WORDS.noCalls}</p>
      ) : (
        recent.calls.map((call) => (
          <div
            className={styles.panel}
            key={call.call_id}
            data-call={call.call_id}
          >
            <p className={styles.copy}>
              <strong>{call.lead_name}</strong> · {when(call.called_at)}
            </p>
            {call.waiting.map((code) => (
              <div key={code} className={styles.checkRow}>
                <span className={styles.mutedNote}>
                  {titleOf.get(code) ?? code}
                </span>
                <span className={styles.checkButtons}>
                  <button
                    type="button"
                    className={styles.smallBtn}
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
            {!call.waiting.length ? (
              <p className={styles.mutedNote}>
                Answered:{" "}
                {call.answered
                  .map((code) => titleOf.get(code) ?? code)
                  .join(", ")}
              </p>
            ) : null}
          </div>
        ))
      )}
    </>
  );
}

export const MISSION_WORDS = WORDS;
