"use client";

/**
 * A file of new leads in the import's Check step (owner's import study, 16 Nov 2026):
 * - each stage word in the file and the stage it becomes; a word that is no stage here
 *   is counted and said, with the stage it starts in, and the word stays on the lead;
 * - the owners the file names: rows naming a teammate keep that teammate, and only the
 *   rest are shared ("Share between my sellers" never overrides the file);
 * - every column: matched, kept on each lead as a detail, empty, or not imported.
 * Nothing is written until Import.
 */

import { useEffect, useRef, useState } from "react";

import { displayName } from "../display-name";
import {
  checkFile,
  LeadsError,
  type FileCheck,
  type ImportPreview,
} from "./leads-client";
import styles from "./import-check.module.css";

export type FileCheckState = {
  /** The check of the inputs on screen now; null while they are being checked. */
  check: FileCheck | null;
  error: string | null;
};

/** One key for everything a check reads: a check of other inputs is never shown
 *  as this one's (PR 634 P2: Import waits until the current inputs are checked). */
export function checkKey(parts: {
  preview: ImportPreview | null;
  mapping: Record<string, string>;
  side: string;
  step: string;
  pipeline: string;
  stages?: Record<string, string>;
  owners?: Record<string, string>;
  /** Bumped when a row is fixed in place (I3). */
  version?: number;
}): string {
  const sorted = (record: Record<string, string> | undefined) =>
    Object.entries(record ?? {}).sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify([
    parts.preview?.file_name ?? null,
    parts.preview?.sheet ?? null,
    parts.preview?.headers ?? null,
    parts.preview?.rows.length ?? 0,
    sorted(parts.mapping),
    parts.side,
    parts.step,
    parts.pipeline,
    sorted(parts.stages),
    sorted(parts.owners),
    parts.version ?? 0,
  ]);
}

export function useFileCheck({
  on,
  preview,
  mapping,
  side,
  step,
  pipeline,
  stages,
  owners,
  version = 0,
}: {
  /** New leads on Check or Assign, or any file on Match columns. */
  on: boolean;
  preview: ImportPreview | null;
  mapping: Record<string, string>;
  side: "live" | "cold";
  step: string;
  pipeline: string;
  /** The stage picked for each of the file's unknown stage words (I2). */
  stages?: Record<string, string>;
  /** The teammate picked for each of the file's unknown owner names (I2). */
  owners?: Record<string, string>;
  /** Bumped when a row is fixed in place (I3). */
  version?: number;
}): FileCheckState {
  const key = checkKey({
    preview,
    mapping,
    side,
    step,
    pipeline,
    stages,
    owners,
    version,
  });
  const [state, setState] = useState<{
    key: string;
    check: FileCheck | null;
    error: string | null;
  }>({ key: "", check: null, error: null });
  // The latest inputs, read when the key changes.
  const inputs = useRef({
    preview,
    mapping,
    side,
    step,
    pipeline,
    stages,
    owners,
  });
  useEffect(() => {
    inputs.current = { preview, mapping, side, step, pipeline, stages, owners };
  });
  useEffect(() => {
    const now = inputs.current;
    if (!on || !now.preview) return;
    const controller = new AbortController();
    checkFile(
      now.preview,
      now.mapping,
      now.side,
      now.step,
      now.pipeline || null,
      controller.signal,
      { stages: now.stages, owners: now.owners },
    ).then(
      (next) => setState({ key, check: next, error: null }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setState({
          key,
          check: null,
          error:
            reason instanceof LeadsError
              ? reason.message
              : "The file couldn't be checked.",
        });
      },
    );
    return () => controller.abort();
  }, [on, key]);
  return state.key === key
    ? { check: state.check, error: state.error }
    : { check: null, error: null };
}

/** New leads that keep an owner the file names: only the rest are shared. */
export const ownedByFile = (state: FileCheckState): number =>
  state.check?.owned_new ?? 0;

/** "Rohan Patil 3 · Farah Shaikh 2": the teammates the file names, by rows. */
export function fileOwnersLine(check: FileCheck | null): string {
  return (check?.owners ?? [])
    .filter((owner) => owner.person_id)
    .map(
      (owner) =>
        `${displayName(owner.person_name ?? owner.name)} ${owner.rows}`,
    )
    .join(" · ");
}

const list = (items: string[]) => items.join(", ");

/** The Check step's lines for the file's stages, owners and columns. */
export function FileCheckLines({
  state,
  stageColumn,
}: {
  state: FileCheckState;
  /** The file's column read as the stage ("Status"). */
  stageColumn?: string;
}) {
  const { check, error } = state;
  if (error)
    return (
      <p className={styles.help} role="status">
        {error}
      </p>
    );
  if (!check)
    return (
      <p className={styles.help} role="status">
        Checking the file…
      </p>
    );
  const unplaced = check.stages.filter((item) => !item.stage);
  const unplacedRows = unplaced.reduce((sum, item) => sum + item.rows, 0);
  const strangers = check.owners.filter((owner) => !owner.person_id);
  const by = (fate: FileCheck["columns"][number]["fate"]) =>
    check.columns.filter((column) => column.fate === fate);
  const matched = by("matched");
  const kept = by("kept");
  const empty = by("empty");
  const hidden = by("not_imported");
  const owners = fileOwnersLine(check);
  return (
    <>
      {check.stages.length ? (
        <dl
          className={styles.counts}
          aria-label="The file's stages"
          data-file-check="stages"
        >
          {check.stages.map((item) => (
            <div key={item.word} data-stage-matched={item.stage ? "" : "no"}>
              <dt>
                {item.word} →{" "}
                {item.stage
                  ? (item.label ?? item.stage)
                  : `no stage by that name: starts in ${check.unmatched_stage ?? "the first stage"}`}
              </dt>
              <dd>{item.rows}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {unplacedRows ? (
        <p className={styles.help} data-file-check="unplaced">
          {unplacedRows === 1
            ? "1 lead's stage isn't one of your stages"
            : `${unplacedRows} leads' stages aren't among your stages`}
          : the file&apos;s word stays on each lead
          {stageColumn ? `, under ${stageColumn}` : ""}.
        </p>
      ) : null}
      {owners || strangers.length ? (
        <p className={styles.help} data-file-check="owners">
          {owners ? `Owners from your file keep their leads: ${owners}.` : ""}
          {strangers.length
            ? `${owners ? " " : ""}Nobody on your team called ${list(
                strangers.map((owner) => owner.name),
              )}: those rows go the way you pick under Assign.`
            : ""}
        </p>
      ) : null}
      <p className={styles.help} data-file-check="columns">
        {`Your ${check.columns.length} columns: ${matched.length} matched`}
        {kept.length
          ? ` · ${kept.length} kept on each lead as details (${list(kept.map((column) => column.header))})`
          : ""}
        {empty.length
          ? ` · ${empty.length} empty, so not imported (${list(empty.map((column) => column.header))})`
          : ""}
        {hidden.length
          ? ` · ${hidden.length} not imported: another app's ids (${list(hidden.map((column) => column.header))})`
          : ""}
        .
      </p>
    </>
  );
}
