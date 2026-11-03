"use client";

/**
 * Old leads kept as history, in the import's Check step (owner, 2 Nov 2026; design
 * cleared by ux-audit): each stage word in the file, how many rows say it, and the
 * stage it becomes. Words the app recognises are filled in; the owner picks the rest,
 * and Import waits, with one plain reason, until every word has a stage. How the
 * file's dates read is said too. Nothing is written until Import.
 */

import { useEffect, useState } from "react";

import { Picker } from "../ui/picker";
import { readJourney, type StageView } from "./journey/journey-client";
import { stageName } from "./journey/stage-look";
import {
  checkHistory,
  LeadsError,
  type HistoryCheck,
  type ImportPreview,
} from "./leads-client";
import styles from "./import-check.module.css";

const DATE_WORDS: Record<NonNullable<HistoryCheck["dates_read_as"]>, string> = {
  dmy: "day/month/year",
  mdy: "month/day/year",
  ymd: "year-month-day",
};

export type OldLeads = {
  check: HistoryCheck | null;
  stages: StageView[];
  /** The stage key each word becomes: the owner's pick, else the app's. */
  chosen: Record<string, string>;
  /** Words with no stage yet. */
  unplaced: number;
  pick: (word: string, stage: string | null) => void;
  error: string | null;
};

/** "Pick a stage for 2 names": why Import waits, or null when it doesn't. */
export function waitReason(state: OldLeads): string | null {
  if (!state.check) return "Checking the file…";
  return state.unplaced
    ? `Pick a stage for ${state.unplaced} name${state.unplaced === 1 ? "" : "s"}`
    : null;
}

export function useOldLeads({
  on,
  preview,
  mapping,
  pipeline,
}: {
  /** The file is Old leads and the import is on its Check step. */
  on: boolean;
  preview: ImportPreview | null;
  mapping: Record<string, string>;
  pipeline: string;
}): OldLeads {
  const [check, setCheck] = useState<HistoryCheck | null>(null);
  const [stages, setStages] = useState<StageView[]>([]);
  const [picked, setPicked] = useState<Record<string, string | null>>({});
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!on || !preview) return;
    const controller = new AbortController();
    checkHistory(
      preview,
      mapping,
      {},
      pipeline || null,
      controller.signal,
    ).then(
      (next) => {
        setCheck(next);
        setError(null);
      },
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setError(
          reason instanceof LeadsError
            ? reason.message
            : "The file couldn't be checked.",
        );
      },
    );
    return () => controller.abort();
  }, [on, preview, mapping, pipeline]);
  useEffect(() => {
    if (!on) return;
    let live = true;
    readJourney(pipeline || undefined).then(
      (next) => {
        if (live) setStages(next.stages.filter((stage) => !stage.archived));
      },
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [on, pipeline]);
  const chosen: Record<string, string> = {};
  let unplaced = 0;
  for (const item of check?.stages ?? []) {
    const stage = item.word in picked ? picked[item.word] : item.stage;
    if (stage) chosen[item.word] = stage;
    else unplaced += 1;
  }
  return {
    check,
    stages,
    chosen,
    unplaced,
    error,
    pick: (word, stage) =>
      setPicked((current) => ({ ...current, [word]: stage })),
  };
}

/** The file's stage words, each with the stage it becomes, and how its dates read. */
export function OldLeadsCheck({ state }: { state: OldLeads }) {
  const { check, stages, chosen } = state;
  if (state.error)
    return (
      <p className={styles.oldNote} role="alert">
        {state.error}
      </p>
    );
  if (!check) return <p className={styles.oldNote}>Checking the file…</p>;
  const options = stages.map((stage) => ({
    key: stage.key,
    label: stageName(stage, "cold"),
  }));
  return (
    <div className={styles.oldLeads}>
      {check.stages.length ? (
        <>
          <p className={styles.oldTitle}>Stages in your file</p>
          <ul className={styles.words} aria-label="Stages in your file">
            {check.stages.map((item) => (
              <li key={item.word}>
                <span className={styles.word}>
                  {item.word}
                  <small>
                    {item.rows} row{item.rows === 1 ? "" : "s"}
                  </small>
                </span>
                <Picker
                  title={`Stage for ${item.word}`}
                  ariaLabel={`Stage for ${item.word}`}
                  mode="inline"
                  value={chosen[item.word] ?? null}
                  placeholder="Pick a stage"
                  invalid={!chosen[item.word]}
                  options={options}
                  onChange={(key) => state.pick(item.word, key)}
                />
              </li>
            ))}
          </ul>
          <p className={styles.oldNote}>
            Each lead also keeps the stage as written in the file.
          </p>
        </>
      ) : (
        <p className={styles.oldNote}>
          No stage column: they come in as the first stage.
        </p>
      )}
      <p className={styles.oldNote}>
        {check.dates_read_as
          ? `Enquiry dates read as ${DATE_WORDS[check.dates_read_as]}.`
          : "No enquiry dates: each keeps the day it is brought in."}
        {check.dates_read_as && check.undated
          ? ` ${check.undated} row${check.undated === 1 ? " has" : "s have"} no date we can read: ${check.undated === 1 ? "it keeps" : "they keep"} the day ${check.undated === 1 ? "it is" : "they are"} brought in.`
          : ""}
      </p>
      <p className={styles.oldNote}>
        Nobody is given them, and they stay out of every list until someone
        works one.
      </p>
    </div>
  );
}
